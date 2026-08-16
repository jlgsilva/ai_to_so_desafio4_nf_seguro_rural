"""
Visao Geral automatica dos dados.

Gera um painel (KPIs, graficos, mapa quando disponivel, tabela de
qualidade de dados) sem depender de LLM e sem depender do formato
especifico do arquivo enviado. Funciona detectando, por heuristica de
nome de coluna e tipo, quais colunas provavelmente representam:

- uma dimensao categorica (ex.: UF, categoria, cultura)
- um valor numerico relevante (ex.: valor, premio, subvencao)
- uma data (para serie temporal)
- coordenadas geograficas (para mapa)

Essas heuristicas sao deliberadamente simples e nao usam IA: o
objetivo e que qualquer CSV enviado, mesmo sem bater com nenhum schema
conhecido, ja produza um painel util imediatamente apos o upload.
"""

from __future__ import annotations

import re
import pandas as pd
from src.query_engine import run_sql
from src.logging_config import get_logger

log = get_logger("overview")

_ID_LIKE_HINTS = [
    "ID", "CODIGO", "COD_", "CD_", "CNPJ", "CPF", "CEP", "CHAVE",
    "NUMERO", "APOLICE", "PROPOSTA", "PROCESSO", "GEOCMU", "GRAU",
    "MIN_LAT", "SEG_LAT", "MIN_LONG", "SEG_LONG", "SERIE", "MODELO",
]
_VALUE_HINTS_PRIORITARIOS = [
    "VL_", "VALOR", "PREMIO", "SUBVENCAO", "INDENIZ", "GARANTIA", "PRECO",
]
_VALUE_HINTS_SECUNDARIOS = ["AREA", "QUANTIDADE", "TOTAL", "ANIMAL"]
_DIM_PRIORITY_HINTS = ["UF", "ESTADO", "REGIAO", "MUNICIPIO", "CIDADE"]
_DATE_HINTS = ["DT_", "DATA", "DATE"]
_LAT_HINTS = ["LATITUDE", "LAT"]
_LON_HINTS = ["LONGITUDE", "LONG", "LON"]
_TEXTO_DTYPES = {"object", "str", "string"}
_NUMERO_DTYPES = {"int64", "float64", "Int64", "Float64"}
_UF_VALIDAS = {
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
    "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
    "SE", "SP", "TO",
}
_MUNICIPIO_NOME_HINTS = ["MUNICIPIO", "MUNICÍPIO", "CIDADE"]
_MUNICIPIO_GEOCODE_HINTS = ["GEOCMU", "COD_MUN", "CODIGO_MUNICIPIO", "CODMUN", "CD_MUN", "IBGE"]


def _name_has(nome: str, hints: list[str]) -> bool:
    nome_up = nome.upper()
    return any(h in nome_up for h in hints)


def choose_semantic_columns(file_profile: dict) -> dict:
    """Escolhe, por heuristica, colunas de dimensao, valor, data e
    geolocalizacao a partir do perfil de UM arquivo."""
    colunas = file_profile["perfil_colunas"]
    linhas = max(file_profile["linhas_totais"], 1)

    candidatos_dim, candidatos_valor, candidatos_data = [], [], []
    candidatos_lat, candidatos_lon = [], []
    candidatos_uf = []
    candidatos_municipio_nome, candidatos_municipio_geo = [], []

    for nome, stats in colunas.items():
        tipo = stats.get("dtype_pandas", "")
        is_texto = tipo in _TEXTO_DTYPES
        is_numero = tipo in _NUMERO_DTYPES
        is_id_like = _name_has(nome, _ID_LIKE_HINTS)
        pct_nulo = stats.get("pct_nulo", 100.0)

        if _name_has(nome, _LAT_HINTS) and not _name_has(nome, ["GRAU", "MIN", "SEG"]):
            candidatos_lat.append((-stats.get("n_unicos", 0), pct_nulo, nome))
        if _name_has(nome, _LON_HINTS) and not _name_has(nome, ["GRAU", "MIN", "SEG"]):
            candidatos_lon.append((-stats.get("n_unicos", 0), pct_nulo, nome))

        # deteccao de coluna de UF baseada nos VALORES reais da coluna,
        # nao apenas no nome: uma coluna so e considerada candidata a
        # mapa por estado se os exemplos observados forem, de fato,
        # siglas validas de UF brasileira. Isso evita mostrar um mapa
        # quando o arquivo enviado nao tem nenhuma informacao geografica
        # por estado, conforme exigido: o app nunca deve supor uma
        # coluna que nao existe ou nao contem esse tipo de dado.
        if is_texto and not is_id_like:
            n_unicos_uf = stats.get("n_unicos", 0)
            exemplos_uf = {str(v).strip().upper() for v in stats.get("exemplos", [])}
            if exemplos_uf and exemplos_uf.issubset(_UF_VALIDAS) and n_unicos_uf <= 27:
                prioridade_uf = 0 if _name_has(nome, ["UF", "ESTADO"]) else 1
                candidatos_uf.append((prioridade_uf, nome))

        # deteccao de coluna de codigo de municipio (IBGE, 7 digitos).
        # Diferente da UF, nao ha como validar o nome do municipio sem
        # uma base de referencia completa, mas o codigo IBGE e um numero
        # de 7 digitos com faixa de valores conhecida, o que permite
        # validar pelos VALORES reais tambem.
        if is_numero:
            minimo, maximo = stats.get("min"), stats.get("max")
            if (
                _name_has(nome, _MUNICIPIO_GEOCODE_HINTS)
                and minimo is not None and maximo is not None
                and 1_000_000 <= minimo and maximo <= 9_999_999
            ):
                candidatos_municipio_geo.append(nome)

        # coluna com o NOME do municipio (usada apenas como contexto,
        # ja que o mapa em si depende do codigo IBGE para ser preciso
        if is_texto and not is_id_like and _name_has(nome, _MUNICIPIO_NOME_HINTS):
            candidatos_municipio_nome.append(nome)

        if _name_has(nome, _DATE_HINTS):
            candidatos_data.append(nome)
            continue

        if is_texto and not is_id_like:
            n_unicos = stats.get("n_unicos", 0)
            if 1 < n_unicos <= 60 and n_unicos < 0.5 * min(linhas, file_profile["linhas_amostradas_para_perfil"]) + 1:
                prioridade = 0 if _name_has(nome, _DIM_PRIORITY_HINTS) else 1
                candidatos_dim.append((prioridade, nome))

        if is_numero and not is_id_like:
            if _name_has(nome, _VALUE_HINTS_PRIORITARIOS):
                prioridade = 0
            elif _name_has(nome, _VALUE_HINTS_SECUNDARIOS):
                prioridade = 1
            else:
                prioridade = 2
            candidatos_valor.append((prioridade, nome))

    candidatos_dim.sort(key=lambda x: x[0])
    candidatos_valor.sort(key=lambda x: x[0])
    candidatos_uf.sort(key=lambda x: x[0])
    # entre colunas candidatas a latitude/longitude, prefere a que tem
    # MAIS valores distintos: colunas de coordenada real tem alta
    # cardinalidade, enquanto colunas "mortas"/placeholder (ex.: uma
    # coluna LATITUDE preenchida so com "-") tem poucos valores unicos
    candidatos_lat.sort(key=lambda x: (x[0], x[1]))
    candidatos_lon.sort(key=lambda x: (x[0], x[1]))
    lat_col = candidatos_lat[0][2] if candidatos_lat else None
    lon_col = candidatos_lon[0][2] if candidatos_lon else None

    return {
        "coluna_dimensao": candidatos_dim[0][1] if candidatos_dim else None,
        "colunas_dimensao_alternativas": [c for _, c in candidatos_dim[1:6]],
        "coluna_valor": candidatos_valor[0][1] if candidatos_valor else None,
        "colunas_valor_alternativas": [c for _, c in candidatos_valor[1:6]],
        "coluna_data": candidatos_data[0] if candidatos_data else None,
        "coluna_lat": lat_col,
        "coluna_lon": lon_col,
        "coluna_uf": candidatos_uf[0][1] if candidatos_uf else None,
        "coluna_municipio_geocode": candidatos_municipio_geo[0] if candidatos_municipio_geo else None,
        "coluna_municipio_nome": candidatos_municipio_nome[0] if candidatos_municipio_nome else None,
    }


def list_columns_by_type(file_profile: dict) -> dict:
    """Lista todas as colunas do arquivo separadas por tipo simples
    (texto/numero), para preencher os seletores de filtro na interface,
    permitindo ao usuario trocar livremente a coluna de dimensao e a
    coluna de valor usadas nos graficos da Visao Geral."""
    texto, numero = [], []
    for nome, stats in file_profile["perfil_colunas"].items():
        tipo = stats.get("dtype_pandas", "")
        if tipo in _TEXTO_DTYPES:
            texto.append(nome)
        elif tipo in _NUMERO_DTYPES:
            numero.append(nome)
    return {"texto": texto, "numero": numero}


def _q(nome_coluna: str) -> str:
    return f'"{nome_coluna}"'


def _sql_quote_list(valores: list[str]) -> str:
    escapados = [str(v).replace("'", "''") for v in valores]
    return ", ".join(f"'{v}'" for v in escapados)


def get_distinct_values(con, view: str, coluna: str, limite: int = 60) -> list:
    df = run_sql(con, f"SELECT DISTINCT {_q(coluna)} AS v FROM {view} WHERE {_q(coluna)} IS NOT NULL ORDER BY 1 LIMIT {limite}")
    return df["v"].tolist()


def get_distinct_years(con, view: str, coluna_data: str) -> list:
    try:
        df = run_sql(con, f"SELECT DISTINCT EXTRACT(YEAR FROM {_q(coluna_data)}) AS ano FROM {view} WHERE {_q(coluna_data)} IS NOT NULL ORDER BY 1")
        return [int(a) for a in df["ano"].dropna().tolist()]
    except Exception:
        log.exception("Falha ao extrair anos distintos da coluna %s", coluna_data)
        return []


def build_where_clause(filtros: dict) -> str:
    """filtros aceita as chaves 'dimensao', 'uf' e 'ano', cada uma no
    formato {'coluna': nome_da_coluna, 'valores': [lista]}. Todas as
    condicoes presentes sao combinadas com AND."""
    condicoes = []
    dim = filtros.get("dimensao")
    if dim and dim.get("valores"):
        condicoes.append(f"{_q(dim['coluna'])} IN ({_sql_quote_list(dim['valores'])})")
    uf = filtros.get("uf")
    if uf and uf.get("valores"):
        condicoes.append(f"UPPER({_q(uf['coluna'])}) IN ({_sql_quote_list(uf['valores'])})")
    ano = filtros.get("ano")
    if ano and ano.get("valores"):
        anos_str = ", ".join(str(int(a)) for a in ano["valores"])
        condicoes.append(f"EXTRACT(YEAR FROM {_q(ano['coluna'])}) IN ({anos_str})")
    if not condicoes:
        return ""
    return "WHERE " + " AND ".join(condicoes)


def _combine_where(where_clause: str, extra_condition: str) -> str:
    """Combina o WHERE de filtro (ja pronto, ex.: 'WHERE x IN (...)') com
    uma condicao adicional fixa da propria consulta (ex.: 'coluna IS NOT
    NULL'), gerando uma unica clausula WHERE valida. Nunca gera duas
    clausulas WHERE em sequencia."""
    if where_clause.strip():
        return f"{where_clause} AND {extra_condition}"
    return f"WHERE {extra_condition}"


def compute_overview(con, view: str, file_profile: dict, semantic: dict, where_clause: str = "") -> dict:
    resultado = {}

    total = run_sql(con, f"SELECT COUNT(*) AS n FROM {view} {where_clause}")
    resultado["total_linhas"] = int(total["n"].iloc[0])

    dim = semantic.get("coluna_dimensao")
    valor = semantic.get("coluna_valor")
    data_col = semantic.get("coluna_data")
    lat, lon = semantic.get("coluna_lat"), semantic.get("coluna_lon")
    uf_col = semantic.get("coluna_uf")

    if dim:
        try:
            resultado["top_categoria"] = run_sql(con, f"""
                SELECT {_q(dim)} AS categoria, COUNT(*) AS contagem
                FROM {view} {where_clause}
                GROUP BY 1 ORDER BY 2 DESC LIMIT 15
            """)
        except Exception:
            log.exception("Falha ao calcular top_categoria para %s", dim)

        if valor:
            try:
                resultado["valor_por_categoria"] = run_sql(con, f"""
                    SELECT {_q(dim)} AS categoria, SUM({_q(valor)}) AS total
                    FROM {view} {where_clause}
                    GROUP BY 1 ORDER BY 2 DESC LIMIT 15
                """)
            except Exception:
                log.exception("Falha ao calcular valor_por_categoria (%s, %s)", dim, valor)

    if data_col:
        try:
            agg = f"SUM({_q(valor)})" if valor else "COUNT(*)"
            where_serie = _combine_where(where_clause, f"{_q(data_col)} IS NOT NULL")
            resultado["serie_temporal"] = run_sql(con, f"""
                SELECT EXTRACT(YEAR FROM {_q(data_col)}) AS periodo, {agg} AS total
                FROM {view} {where_serie}
                GROUP BY 1 ORDER BY 1
            """)
        except Exception:
            log.exception("Falha ao calcular serie_temporal para %s", data_col)

    if lat and lon:
        try:
            condicao_geo = (
                f"TRY_CAST({_q(lat)} AS DOUBLE) IS NOT NULL "
                f"AND TRY_CAST({_q(lon)} AS DOUBLE) IS NOT NULL "
                f"AND TRY_CAST({_q(lat)} AS DOUBLE) BETWEEN -90 AND 90 "
                f"AND TRY_CAST({_q(lon)} AS DOUBLE) BETWEEN -180 AND 180"
            )
            where_geo = _combine_where(where_clause, condicao_geo)
            resultado["geo_amostra"] = run_sql(con, f"""
                SELECT {_q(lat)} AS lat, {_q(lon)} AS lon
                FROM {view} {where_geo}
                LIMIT 3000
            """)
        except Exception:
            log.exception("Falha ao amostrar coordenadas (%s, %s)", lat, lon)

    if uf_col:
        try:
            agg_uf = f"SUM({_q(valor)})" if valor else "COUNT(*)"
            where_uf = _combine_where(where_clause, f"{_q(uf_col)} IS NOT NULL")
            resultado["mapa_uf"] = run_sql(con, f"""
                SELECT UPPER({_q(uf_col)}) AS uf, {agg_uf} AS valor
                FROM {view} {where_uf}
                GROUP BY 1
            """)
            resultado["mapa_uf_metrica"] = valor if valor else "quantidade de registros"
        except Exception:
            log.exception("Falha ao calcular mapa por UF (%s)", uf_col)

    municipio_geo = semantic.get("coluna_municipio_geocode")
    if municipio_geo:
        try:
            agg_mun = f"SUM({_q(valor)})" if valor else "COUNT(*)"
            where_mun = _combine_where(where_clause, f"{_q(municipio_geo)} IS NOT NULL")
            resultado["mapa_municipio"] = run_sql(con, f"""
                SELECT CAST({_q(municipio_geo)} AS VARCHAR) AS geocodigo, {agg_mun} AS valor
                FROM {view} {where_mun}
                GROUP BY 1
            """)
            resultado["mapa_municipio_metrica"] = valor if valor else "quantidade de registros"
        except Exception:
            log.exception("Falha ao calcular mapa por municipio (%s)", municipio_geo)

    nulos = []
    for nome, stats in file_profile["perfil_colunas"].items():
        nulos.append({"coluna": nome, "pct_nulo": stats.get("pct_nulo", 0.0)})
    df_nulos = pd.DataFrame(nulos).sort_values("pct_nulo", ascending=False)
    resultado["qualidade_dados"] = df_nulos
    resultado["pct_nulo_medio"] = round(df_nulos["pct_nulo"].mean(), 1) if len(df_nulos) else 0.0

    resultado["semantic"] = semantic
    return resultado
