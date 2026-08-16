"""
Motor de consulta.

Usa DuckDB para consultar os arquivos normalizados (UTF-8) em disco,
independente do tamanho. Isso evita carregar arquivos grandes inteiros
na memoria do processo Streamlit: o DuckDB le o CSV diretamente do
disco e so materializa em pandas o RESULTADO da consulta (que deve ser
pequeno, ja que e uma agregacao/filtro, nunca o dataset bruto inteiro).

Cada arquivo carregado vira uma VIEW nomeada a partir do nome do
arquivo (sem extensao, caracteres nao alfanumericos viram "_"). Essa
e a unica interface que o codigo gerado pela LLM (Executor Agent)
enxerga: nomes de view + SQL.
"""

from __future__ import annotations

import re
import duckdb
from src.logging_config import get_logger

log = get_logger("query_engine")


def _view_name(filename: str) -> str:
    base = filename.rsplit(".", 1)[0]
    clean = re.sub(r"[^0-9a-zA-Z_]", "_", base).lower()
    # identificadores SQL nao podem comecar com digito
    if clean[0].isdigit():
        clean = f"t_{clean}"
    return clean


def build_connection(loaded_files: dict) -> tuple[duckdb.DuckDBPyConnection, dict[str, str]]:
    """Retorna uma conexao DuckDB com uma VIEW por arquivo, e o mapa
    filename -> nome_da_view (usado nos prompts)."""
    con = duckdb.connect(database=":memory:")
    view_names = {}
    for filename, lf in loaded_files.items():
        view = _view_name(filename)
        view_names[filename] = view
        con.execute(f"""
            CREATE OR REPLACE VIEW {view} AS
            SELECT * FROM read_csv(
                '{lf.normalized_path}',
                delim='{lf.delimiter}',
                decimal_separator='{lf.decimal}',
                header=true,
                encoding='utf-8',
                ignore_errors=true,
                all_varchar=false,
                nullstr=['-', '', 'NA', 'N/A', 'null', 'NULL']
            )
        """)
        log.info("View criada: '%s' -> %s", filename, view)
    return con, view_names


MAX_RESULT_ROWS = 6000


def run_sql(con: duckdb.DuckDBPyConnection, sql: str):
    """Executa SQL gerado pelo Executor Agent e retorna um DataFrame.
    Aplica um teto de linhas de retorno para proteger a memoria da
    aplicacao Streamlit contra consultas mal formuladas (ex.: SELECT *
    em um arquivo de milhoes de linhas sem agregacao)."""
    sql_clean = sql.strip().rstrip(";")
    if not sql_clean.lower().startswith(("select", "with")):
        log.warning("SQL rejeitado (nao e SELECT/WITH): %s", sql_clean[:200])
        raise ValueError("Apenas consultas SELECT/WITH sao permitidas.")
    limited_sql = f"SELECT * FROM ({sql_clean}) AS _q LIMIT {MAX_RESULT_ROWS}"
    try:
        return con.execute(limited_sql).fetchdf()
    except Exception:
        log.exception("Erro ao executar SQL: %s", limited_sql[:500])
        raise
