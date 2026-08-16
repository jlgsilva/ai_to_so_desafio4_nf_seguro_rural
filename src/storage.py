"""
Historico persistente da aplicacao.

Usa SQLite (um unico arquivo, sem infraestrutura externa) para
registrar:
- datasets: cada upload processado (nome dos arquivos, perfil, resumo)
- queries: cada pergunta feita, o plano gerado, o SQL executado e o
  resultado (resumido), com timestamp

Isso atende ao pedido de manter historico de dados/analises entre
sessoes, e tambem serve como trilha de auditoria de como os agentes
decidiram cada resposta (util para o relatorio tecnico do desafio).
"""

from __future__ import annotations

import json
import sqlite3
import datetime
import pandas as pd
from src.logging_config import get_logger

log = get_logger("storage")

DB_PATH = "data/history.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TEXT NOT NULL,
    nome_zip TEXT,
    arquivos TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    resumo_ia TEXT
);

CREATE TABLE IF NOT EXISTS queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    criado_em TEXT NOT NULL,
    pergunta TEXT NOT NULL,
    plano_json TEXT,
    sql_final TEXT,
    sucesso INTEGER NOT NULL,
    erro TEXT,
    tipo_visualizacao TEXT,
    resposta_texto TEXT,
    resultado_preview_json TEXT,
    tempo_segundos REAL,
    FOREIGN KEY (dataset_id) REFERENCES datasets (id)
);
"""


def _connect() -> sqlite3.Connection:
    import os
    os.makedirs("data", exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(_SCHEMA)
    return con


def save_dataset(nome_zip: str, arquivos: list[str], profile: dict) -> int:
    con = _connect()
    cur = con.execute(
        "INSERT INTO datasets (criado_em, nome_zip, arquivos, profile_json, resumo_ia) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            datetime.datetime.now().isoformat(timespec="seconds"),
            nome_zip,
            json.dumps(arquivos, ensure_ascii=False),
            json.dumps(profile, ensure_ascii=False, default=str),
            profile.get("resumo_ia", ""),
        ),
    )
    con.commit()
    dataset_id = cur.lastrowid
    con.close()
    log.info("Dataset salvo no historico: id=%d, zip=%s, arquivos=%s", dataset_id, nome_zip, arquivos)
    return dataset_id


def save_query(dataset_id: int, result: dict) -> int:
    con = _connect()
    tabela = result.get("tabela_resultado")
    preview_json = tabela.head(30).to_json(orient="records", force_ascii=False) if isinstance(tabela, pd.DataFrame) else None
    cur = con.execute(
        "INSERT INTO queries (dataset_id, criado_em, pergunta, plano_json, sql_final, "
        "sucesso, erro, tipo_visualizacao, resposta_texto, resultado_preview_json, tempo_segundos) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            dataset_id,
            datetime.datetime.now().isoformat(timespec="seconds"),
            result.get("pergunta"),
            json.dumps(result.get("plano"), ensure_ascii=False, default=str),
            result.get("sql_final"),
            1 if result.get("sucesso") else 0,
            result.get("erro"),
            result.get("tipo_visualizacao"),
            result.get("texto_resposta"),
            preview_json,
            result.get("tempo_segundos"),
        ),
    )
    con.commit()
    query_id = cur.lastrowid
    con.close()
    log.info(
        "Query salva no historico: id=%d, dataset_id=%d, sucesso=%s",
        query_id, dataset_id, result.get("sucesso"),
    )
    return query_id


def list_datasets(limit: int = 50) -> pd.DataFrame:
    con = _connect()
    df = pd.read_sql_query(
        "SELECT id, criado_em, nome_zip, arquivos, resumo_ia FROM datasets "
        "ORDER BY id DESC LIMIT ?", con, params=(limit,),
    )
    con.close()
    return df


def list_queries(dataset_id: int | None = None, limit: int = 200) -> pd.DataFrame:
    con = _connect()
    if dataset_id is not None:
        df = pd.read_sql_query(
            "SELECT * FROM queries WHERE dataset_id = ? ORDER BY id DESC LIMIT ?",
            con, params=(dataset_id, limit),
        )
    else:
        df = pd.read_sql_query(
            "SELECT * FROM queries ORDER BY id DESC LIMIT ?", con, params=(limit,),
        )
    con.close()
    return df
