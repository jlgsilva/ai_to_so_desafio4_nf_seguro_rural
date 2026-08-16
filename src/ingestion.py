"""
Camada de ingestao.

Responsavel por:
- extrair arquivos de um .zip enviado pelo usuario
- detectar automaticamente encoding, delimitador e separador decimal
  de cada CSV (sem assumir um formato fixo)
- normalizar cada arquivo para UTF-8 em disco, via transcodificacao em
  streaming (nao carrega o arquivo inteiro em memoria), para que o
  restante do pipeline (perfilamento, DuckDB, pandas) nunca precise se
  preocupar com encoding de novo
- ler uma amostra (para perfilamento e prompts de LLM), mantendo o
  arquivo completo em disco para consulta posterior via DuckDB

Este modulo nao usa LLM. E a parte deterministica do pipeline. A
decisao "o que fazer com os dados" fica com os agentes (src/agents).
"""

from __future__ import annotations

import io
import os
import csv
import codecs
import zipfile
import chardet
import pandas as pd
from dataclasses import dataclass
from src.logging_config import get_logger

log = get_logger("ingestion")

RAW_DIR = "data/raw"
LARGE_FILE_THRESHOLD_MB = 150
SAMPLE_ROWS_FOR_PROFILE = 5000
ENCODING_SNIFF_BYTES = 200_000
TRANSCODE_CHUNK_BYTES = 1_000_000


@dataclass
class LoadedFile:
    filename: str
    size_bytes: int
    encoding_original: str
    delimiter: str
    decimal: str
    is_large: bool
    normalized_path: str      # arquivo UTF-8, delimitador original preservado
    sample_df: pd.DataFrame
    row_count_estimate: int


def extract_zip(zip_bytes: bytes) -> dict[str, bytes]:
    """Extrai arquivos de um zip em memoria. Ignora pastas de sistema
    (__MACOSX) e arquivos ocultos."""
    files: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            name = info.filename
            base = name.split("/")[-1]
            if info.is_dir() or base.startswith(".") or "__MACOSX" in name:
                continue
            if not base.lower().endswith((".csv", ".txt", ".tsv")):
                continue
            files[base] = zf.read(info)
    return files


_PT_ACCENTED_CHARS = set("áàâãéêíóôõúüçÁÀÂÃÉÊÍÓÔÕÚÜÇñÑ")
_CHARDET_CONFIDENCE_MIN = 0.6


def _score_text_plausibility(text: str) -> int:
    """Pontua um texto decodificado: soma pontos por acentos comuns em
    portugues, subtrai pontos por caracteres fora de faixas usuais
    (sinal de decodificacao incorreta, ex.: cp1250 aplicado a bytes
    cp1252 produz caracteres do alfabeto centro-europeu no lugar de
    acentos)."""
    score = 0
    for ch in text:
        if ch in _PT_ACCENTED_CHARS:
            score += 2
        elif ord(ch) > 0x2500:
            score -= 3
    return score


def sniff_encoding(raw: bytes) -> str:
    chunk = raw[:ENCODING_SNIFF_BYTES]
    result = chardet.detect(chunk)
    detected = (result.get("encoding") or "utf-8").lower()
    confidence = result.get("confidence") or 0.0

    if detected == "ascii":
        return "utf-8"

    # candidatos comuns em bases de orgaos publicos brasileiros; usados
    # como desempate quando o chardet erra (o que acontece com
    # frequencia entre codepages Latin/Central-European de 1 byte,
    # quando a confianca da deteccao e baixa)
    candidates = [detected, "cp1252", "latin-1", "utf-8"]
    if confidence >= _CHARDET_CONFIDENCE_MIN:
        candidates = [detected] + [c for c in candidates if c != detected]

    best_enc, best_score = None, float("-inf")
    for enc in dict.fromkeys(candidates):
        try:
            text = chunk.decode(enc, errors="strict")
        except (UnicodeDecodeError, LookupError):
            continue
        score = _score_text_plausibility(text)
        if score > best_score:
            best_enc, best_score = enc, score

    enc = best_enc or detected
    if enc in ("iso-8859-1", "latin-1", "windows-1252", "cp1252", "iso8859-15"):
        enc = "cp1252"
    return enc


def sniff_delimiter(text_sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(text_sample, delimiters=";,|\t")
        return dialect.delimiter
    except csv.Error:
        first_line = text_sample.split("\n", 1)[0]
        candidates = [";", ",", "\t", "|"]
        counts = {c: first_line.count(c) for c in candidates}
        return max(counts, key=counts.get)


def sniff_decimal(text_sample: str, delimiter: str) -> str:
    """Se o delimitador de campo NAO for virgula e boa parte dos campos
    numericos usar virgula como separador decimal (padrao
    numero,numero), assume decimal=','. Caso contrario, '.'."""
    if delimiter == ",":
        return "."
    import re
    pattern = re.compile(r"\b\d+,\d{1,4}\b")
    matches = len(pattern.findall(text_sample))
    return "," if matches > 3 else "."


def _read_text_sample(raw: bytes, encoding: str, n_lines: int = 80) -> str:
    text = raw.decode(encoding, errors="replace")
    return "\n".join(text.splitlines()[:n_lines])


def _transcode_to_utf8(raw: bytes, encoding_original: str, out_path: str) -> None:
    """Converte bytes -> UTF-8 em streaming, sem materializar a string
    inteira na memoria de uma vez (importante para arquivos grandes)."""
    decoder = codecs.getincrementaldecoder(encoding_original)(errors="replace")
    with open(out_path, "w", encoding="utf-8", newline="") as out:
        buf = io.BytesIO(raw)
        while True:
            chunk = buf.read(TRANSCODE_CHUNK_BYTES)
            if not chunk:
                out.write(decoder.decode(b"", final=True))
                break
            out.write(decoder.decode(chunk))


def load_csv_bytes(filename: str, raw: bytes, sample_rows: int = SAMPLE_ROWS_FOR_PROFILE) -> LoadedFile:
    size_bytes = len(raw)
    encoding_original = sniff_encoding(raw)
    text_sample = _read_text_sample(raw, encoding_original)
    delimiter = sniff_delimiter(text_sample)
    decimal = sniff_decimal(text_sample, delimiter)
    is_large = size_bytes > LARGE_FILE_THRESHOLD_MB * 1024 * 1024

    os.makedirs(RAW_DIR, exist_ok=True)
    normalized_path = os.path.join(RAW_DIR, filename)
    _transcode_to_utf8(raw, encoding_original, normalized_path)

    sample_df = pd.read_csv(
        normalized_path,
        sep=delimiter,
        decimal=decimal,
        encoding="utf-8",
        engine="python",
        on_bad_lines="skip",
        nrows=sample_rows,
    )

    # contagem de linhas e uma varredura simples (sem parsing de campos),
    # rapida mesmo para arquivos de centenas de MB
    with open(normalized_path, "r", encoding="utf-8", errors="replace") as f:
        row_count_estimate = max(sum(1 for _ in f) - 1, 0)

    log.info(
        "Arquivo '%s' processado: %.2f MB, encoding=%s, delimitador=%r, "
        "decimal=%r, linhas=%d, arquivo_grande=%s",
        filename, size_bytes / (1024 * 1024), encoding_original, delimiter,
        decimal, row_count_estimate, is_large,
    )

    return LoadedFile(
        filename=filename,
        size_bytes=size_bytes,
        encoding_original=encoding_original,
        delimiter=delimiter,
        decimal=decimal,
        is_large=is_large,
        normalized_path=normalized_path,
        sample_df=sample_df,
        row_count_estimate=row_count_estimate,
    )


def load_all(zip_bytes: bytes) -> dict[str, LoadedFile]:
    files = extract_zip(zip_bytes)
    if not files:
        log.warning("Nenhum arquivo .csv/.txt/.tsv encontrado dentro do .zip enviado.")
        raise ValueError("Nenhum arquivo .csv/.txt/.tsv encontrado dentro do .zip.")
    log.info("Zip extraido: %d arquivo(s) encontrado(s): %s", len(files), list(files.keys()))
    return {name: load_csv_bytes(name, raw) for name, raw in files.items()}
