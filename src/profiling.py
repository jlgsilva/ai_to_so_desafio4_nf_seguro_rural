"""
Perfilamento de dados.

A partir dos arquivos carregados (ingestion.LoadedFile), monta um
"Data Profile" estruturado (dict serializavel em JSON) com:
- schema de cada arquivo (colunas, tipos, nulos, cardinalidade)
- familia de dominio reconhecida (SISSER, NFE_CABECALHO, NFE_ITENS ou
  GENERICO)
- relacionamento sugerido entre arquivos (colunas em comum, candidatas
  a chave de juncao)

Esse profile e o que vai para o prompt dos agentes. Nunca os dados
brutos completos.
"""

from __future__ import annotations

import pandas as pd
from src.domain_schemas import match_schema


def _column_profile(series: pd.Series) -> dict:
    n = len(series)
    n_null = int(series.isna().sum())
    dtype = str(series.dtype)
    profile = {
        "dtype_pandas": dtype,
        "pct_nulo": round(100 * n_null / n, 2) if n else 0.0,
        "n_unicos": int(series.nunique(dropna=True)),
    }
    non_null = series.dropna()
    if pd.api.types.is_numeric_dtype(series) and len(non_null) > 0:
        profile["min"] = float(non_null.min())
        profile["max"] = float(non_null.max())
        profile["media"] = round(float(non_null.mean()), 4)
    else:
        sample_vals = non_null.astype(str).unique()[:5].tolist()
        profile["exemplos"] = sample_vals
    return profile


def profile_file(loaded_file) -> dict:
    df = loaded_file.sample_df
    schema_match = match_schema(list(df.columns))

    columns_profile = {col: _column_profile(df[col]) for col in df.columns}

    return {
        "arquivo": loaded_file.filename,
        "tamanho_mb": round(loaded_file.size_bytes / (1024 * 1024), 2),
        "encoding_detectado": loaded_file.encoding_original,
        "delimitador_detectado": loaded_file.delimiter,
        "decimal_detectado": loaded_file.decimal,
        "arquivo_grande": loaded_file.is_large,
        "linhas_totais": loaded_file.row_count_estimate,
        "caminho_normalizado": loaded_file.normalized_path,
        "linhas_amostradas_para_perfil": len(df),
        "colunas": list(df.columns),
        "perfil_colunas": columns_profile,
        "familia_reconhecida": schema_match["id"] if schema_match else "GENERICO",
        "familia_nome": schema_match["nome"] if schema_match else "Formato nao catalogado",
        "glossario": schema_match.get("glossario") if schema_match else {},
        "chave_primaria_sugerida": schema_match.get("chave_primaria") if schema_match else [],
    }


def detect_relationships(profiles: list[dict]) -> list[dict]:
    """Detecta colunas em comum entre pares de arquivos, candidatas a
    chave de juncao (ex.: CHAVE DE ACESSO entre cabecalho e itens)."""
    rels = []
    for i in range(len(profiles)):
        for j in range(i + 1, len(profiles)):
            cols_i = {c.strip().upper() for c in profiles[i]["colunas"]}
            cols_j = {c.strip().upper() for c in profiles[j]["colunas"]}
            common = cols_i & cols_j
            if common:
                rels.append({
                    "arquivo_a": profiles[i]["arquivo"],
                    "arquivo_b": profiles[j]["arquivo"],
                    "colunas_em_comum": sorted(common),
                })
    return rels


def build_dataset_profile(loaded_files: dict) -> dict:
    profiles = [profile_file(lf) for lf in loaded_files.values()]
    relationships = detect_relationships(profiles)
    return {
        "arquivos": profiles,
        "relacionamentos": relationships,
        "quantidade_arquivos": len(profiles),
    }


_DTYPE_SIMPLES = {
    "object": "texto",
    "str": "texto",
    "string": "texto",
    "int64": "numero_inteiro",
    "Int64": "numero_inteiro",
    "float64": "numero_decimal",
    "Float64": "numero_decimal",
    "bool": "booleano",
    "datetime64[ns]": "data",
}


def _simplify_dtype(dtype_pandas: str) -> str:
    return _DTYPE_SIMPLES.get(dtype_pandas, dtype_pandas)


def build_llm_profile_summary(dataset_profile: dict, max_colunas_exemplo: int = 3) -> dict:
    """Versao COMPACTA do dataset_profile, usada em todos os prompts
    enviados a LLM (Profiler, Planner, Executor).

    O profile completo (com estatisticas detalhadas por coluna, minimo,
    maximo, media e ate 5 exemplos de valor por coluna) e util para a
    interface e para o historico, mas e grande demais para caber
    dentro dos limites de tokens por minuto das contas gratuitas da
    Groq quando ha varios arquivos com muitas colunas. Esta versao
    mantem apenas o que os agentes realmente precisam para planejar e
    gerar SQL: nome, tipo simplificado e percentual de nulos de cada
    coluna, mais o glossario de negocio (quando reconhecido) e os
    relacionamentos entre arquivos. Estatisticas numericas (min/max/
    media) sao mantidas, pois ajudam a validar faixas de valores; as
    listas de exemplos de texto sao cortadas para no maximo
    `max_colunas_exemplo` valores curtos."""
    arquivos_compactos = []
    for fp in dataset_profile["arquivos"]:
        colunas_compactas = {}
        for nome_col, stats in fp["perfil_colunas"].items():
            entrada = {
                "tipo": _simplify_dtype(stats.get("dtype_pandas", "")),
                "pct_nulo": stats.get("pct_nulo", 0.0),
            }
            if "min" in stats:
                entrada["min"] = stats["min"]
                entrada["max"] = stats["max"]
            elif "exemplos" in stats:
                exemplos = stats["exemplos"][:max_colunas_exemplo]
                entrada["exemplos"] = [str(v)[:40] for v in exemplos]
            colunas_compactas[nome_col] = entrada

        arquivos_compactos.append({
            "arquivo": fp["arquivo"],
            "familia": fp["familia_reconhecida"],
            "linhas_totais": fp["linhas_totais"],
            "arquivo_grande": fp["arquivo_grande"],
            "chave_primaria_sugerida": fp.get("chave_primaria_sugerida", []),
            "colunas": colunas_compactas,
            "glossario": fp.get("glossario", {}),
        })

    return {
        "arquivos": arquivos_compactos,
        "relacionamentos": dataset_profile.get("relacionamentos", []),
    }


def build_minimal_profile_summary(dataset_profile: dict) -> dict:
    """Versao MINIMA do profile, usada apenas para o resumo em
    linguagem natural (Profiler Agent, modelo rapido/pequeno). Nao
    inclui estatisticas por coluna nem glossario, apenas o essencial:
    nomes de arquivo, familia reconhecida, quantidade de linhas e a
    lista de nomes de coluna. Isso mantem o consumo de tokens baixo o
    suficiente mesmo para contas Groq com limites de tokens por minuto
    bastante restritivos."""
    arquivos = []
    for fp in dataset_profile["arquivos"]:
        arquivos.append({
            "arquivo": fp["arquivo"],
            "familia": fp["familia_nome"],
            "linhas_totais": fp["linhas_totais"],
            "colunas": fp["colunas"],
        })
    return {
        "arquivos": arquivos,
        "relacionamentos": dataset_profile.get("relacionamentos", []),
    }
