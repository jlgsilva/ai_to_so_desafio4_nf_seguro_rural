"""
Testes da camada deterministica do pipeline (ingestao, perfilamento e
motor de consulta). Nao dependem de GROQ_API_KEY: nenhum destes testes
chama a LLM, propositalmente, para que possam rodar em qualquer
ambiente (inclusive CI) sem custo e sem rede.

Execucao:
    pytest tests/ -v
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.ingestion import load_all
from src.profiling import build_dataset_profile
from src.query_engine import build_connection, run_sql

SAMPLE_DIR = os.path.join(os.path.dirname(__file__), "..", "sample_data")


def _load_sample(name):
    path = os.path.join(SAMPLE_DIR, name)
    with open(path, "rb") as f:
        return load_all(f.read())


def test_nfe_encoding_e_delimitador():
    loaded = _load_sample("exemplo_nfe.zip")
    for lf in loaded.values():
        assert lf.encoding_original == "utf-8"
        assert lf.delimiter == ","
        assert lf.decimal == "."


def test_nfe_familia_reconhecida():
    loaded = _load_sample("exemplo_nfe.zip")
    profile = build_dataset_profile(loaded)
    familias = {f["arquivo"]: f["familia_reconhecida"] for f in profile["arquivos"]}
    assert familias["202401_NFs_Cabecalho.csv"] == "NFE_CABECALHO"
    assert familias["202401_NFs_Itens.csv"] == "NFE_ITENS"


def test_nfe_relacionamento_por_chave_de_acesso():
    loaded = _load_sample("exemplo_nfe.zip")
    profile = build_dataset_profile(loaded)
    assert len(profile["relacionamentos"]) == 1
    assert "CHAVE DE ACESSO" in profile["relacionamentos"][0]["colunas_em_comum"]


def test_nfe_join_via_duckdb():
    loaded = _load_sample("exemplo_nfe.zip")
    con, views = build_connection(loaded)
    cab = views["202401_NFs_Cabecalho.csv"]
    itens = views["202401_NFs_Itens.csv"]
    df = run_sql(con, f'''
        SELECT c."UF EMITENTE" AS uf, SUM(i."VALOR TOTAL") AS total
        FROM {cab} c JOIN {itens} i ON c."CHAVE DE ACESSO" = i."CHAVE DE ACESSO"
        GROUP BY 1 ORDER BY 2 DESC
    ''')
    assert len(df) > 0
    assert df["total"].sum() > 0


def test_sisser_encoding_normalizado_para_cp1252_ou_utf8():
    loaded = _load_sample("exemplo_sisser.zip")
    for lf in loaded.values():
        assert lf.encoding_original in ("cp1252", "utf-8")
        assert lf.delimiter == ";"
        assert lf.decimal == ","


def test_sisser_familia_reconhecida():
    loaded = _load_sample("exemplo_sisser.zip")
    profile = build_dataset_profile(loaded)
    for f in profile["arquivos"]:
        assert f["familia_reconhecida"] == "SISSER"


def test_sisser_valores_nulos_marcados_com_traco_viram_null():
    loaded = _load_sample("exemplo_sisser.zip")
    con, views = build_connection(loaded)
    v = list(views.values())[0]
    df = run_sql(con, f'''
        SELECT COUNT(*) AS n_com_indenizacao
        FROM {v} WHERE "VALOR_INDENIZAÇÃO" IS NOT NULL
    ''')
    total = run_sql(con, f'SELECT COUNT(*) AS n FROM {v}')
    # nem todas as apolices tem sinistro, entao o numero de indenizacoes
    # nao-nulas deve ser bem menor que o total de linhas
    assert df["n_com_indenizacao"].iloc[0] < total["n"].iloc[0]


def test_sisser_uniao_entre_anos_com_schema_identico():
    loaded = _load_sample("exemplo_sisser.zip")
    con, views = build_connection(loaded)
    view_list = list(views.values())
    union_sql = " UNION ALL BY NAME ".join(f"SELECT * FROM {v}" for v in view_list)
    df = run_sql(con, f'''
        WITH todos AS ({union_sql})
        SELECT "NM_CULTURA_GLOBAL" AS cultura, COUNT(*) AS n
        FROM todos GROUP BY 1 ORDER BY n DESC LIMIT 5
    ''')
    assert len(df) == 5
    assert df["n"].iloc[0] > 0


def test_perfil_compacto_fica_dentro_de_limite_de_tokens_seguro():
    """Regressao: o profile completo enviado direto para a LLM já
    causou erro 413 (tokens por minuto excedidos) em contas Groq com
    limites baixos (6000 TPM no modelo rapido). As versoes compact/
    minimal devem manter o payload bem abaixo desse teto mesmo com
    varios arquivos de muitas colunas (caso SISSER, 3 arquivos x 38
    colunas)."""
    from src.profiling import build_llm_profile_summary, build_minimal_profile_summary
    import json as _json

    loaded = _load_sample("exemplo_sisser.zip")
    profile = build_dataset_profile(loaded)

    compact = build_llm_profile_summary(profile)
    compact_tokens_estimado = len(_json.dumps(compact, ensure_ascii=False, default=str)) // 4
    assert compact_tokens_estimado < 5500, (
        f"Profile compacto muito grande ({compact_tokens_estimado} tokens estimados); "
        "risco de erro 413 em contas Groq com TPM baixo."
    )

    minimal = build_minimal_profile_summary(profile)
    minimal_tokens_estimado = len(_json.dumps(minimal, ensure_ascii=False, default=str)) // 4
    assert minimal_tokens_estimado < 2500


def test_planner_prompt_nao_quebra_com_chaves_literais_do_json_de_exemplo():
    """Regressao: o exemplo de JSON dentro do prompt do Planner Agent
    continha chaves { } literais nao escapadas, que o LangChain
    interpretava como variaveis de template, quebrando toda pergunta
    com KeyError. As chaves do exemplo devem estar escapadas ({{ }})."""
    from src.agents.planner_agent import _PLANNER_PROMPT

    msgs = _PLANNER_PROMPT.format_messages(
        profile_json='{"arquivos": []}', pergunta="qual estado teve mais seguro em 2024?"
    )
    assert len(msgs) == 2
    assert "arquivos_necessarios" in msgs[0].content


def test_overview_detecta_dimensao_valor_e_data_para_sisser():
    from src.overview import choose_semantic_columns

    loaded = _load_sample("exemplo_sisser.zip")
    profile = build_dataset_profile(loaded)
    fp = [f for f in profile["arquivos"] if f["arquivo"] == "dados_abertos_psr_2016a2024csv.csv"][0]
    semantic = choose_semantic_columns(fp)

    assert semantic["coluna_dimensao"] == "SG_UF_PROPRIEDADE"
    assert semantic["coluna_valor"] in ("VL_LIMITE_GARANTIA", "VL_SUBVENCAO_FEDERAL")
    assert semantic["coluna_data"] is not None


def test_overview_prefere_coluna_geografica_com_dados_reais():
    """Regressao: quando existe mais de uma coluna candidata a
    latitude/longitude (uma delas so com valores placeholder tipo '-'),
    a escolhida deve ser a que tem coordenadas reais, nao a primeira
    que bater o nome."""
    from src.overview import choose_semantic_columns

    loaded = _load_sample("exemplo_sisser.zip")
    profile = build_dataset_profile(loaded)
    fp = [f for f in profile["arquivos"] if f["arquivo"] == "dados_abertos_psr_2025csv.csv"][0]
    semantic = choose_semantic_columns(fp)

    assert semantic["coluna_lat"] == "NR_DECIMAL_LATITUDE"
    assert semantic["coluna_lon"] == "NR_DECIMAL_LONGITUDE"


def test_overview_compute_gera_amostra_geografica_valida():
    from src.overview import choose_semantic_columns, compute_overview

    loaded = _load_sample("exemplo_sisser.zip")
    profile = build_dataset_profile(loaded)
    con, views = build_connection(loaded)
    fp = [f for f in profile["arquivos"] if f["arquivo"] == "dados_abertos_psr_2025csv.csv"][0]
    semantic = choose_semantic_columns(fp)
    view = views[fp["arquivo"]]

    resultado = compute_overview(con, view, fp, semantic)
    geo = resultado.get("geo_amostra")
    assert geo is not None and len(geo) > 0
    assert geo["lat"].between(-90, 90).all()
    assert geo["lon"].between(-180, 180).all()


def test_suggestions_para_sisser_e_nfe_e_dados_genericos():
    from src.suggestions import suggest_questions

    loaded_sisser = _load_sample("exemplo_sisser.zip")
    profile_sisser = build_dataset_profile(loaded_sisser)
    perguntas_sisser = suggest_questions(profile_sisser)
    assert len(perguntas_sisser) > 0
    assert any("subvenc" in p.lower() for p in perguntas_sisser)

    loaded_nfe = _load_sample("exemplo_nfe.zip")
    profile_nfe = build_dataset_profile(loaded_nfe)
    perguntas_nfe = suggest_questions(profile_nfe)
    assert len(perguntas_nfe) > 0
    assert any("nota" in p.lower() or "valor" in p.lower() for p in perguntas_nfe)


def test_overview_detecta_coluna_uf_pelos_valores_reais():
    """A deteccao de UF deve se basear nos valores observados na
    coluna (siglas validas de estado), nao apenas no nome. Isso e o
    que garante que o mapa so aparece quando o dado de entrada
    realmente contem informacao geografica por estado."""
    from src.overview import choose_semantic_columns

    loaded = _load_sample("exemplo_sisser.zip")
    profile = build_dataset_profile(loaded)
    fp = [f for f in profile["arquivos"] if f["arquivo"] == "dados_abertos_psr_2016a2024csv.csv"][0]
    semantic = choose_semantic_columns(fp)
    assert semantic["coluna_uf"] == "SG_UF_PROPRIEDADE"

    loaded_nfe = _load_sample("exemplo_nfe.zip")
    profile_nfe = build_dataset_profile(loaded_nfe)
    fp_nfe = profile_nfe["arquivos"][0]
    semantic_nfe = choose_semantic_columns(fp_nfe)
    assert semantic_nfe["coluna_uf"] == "UF EMITENTE"


def test_overview_nao_detecta_uf_quando_nao_existe_no_dado():
    """Regressao: um CSV sem nenhuma coluna de estado nao deve gerar
    mapa. O app precisa sempre respeitar o dado de entrada."""
    import io
    import zipfile
    import pandas as pd
    from src.ingestion import load_all as _load_all
    from src.overview import choose_semantic_columns, compute_overview

    df = pd.DataFrame({
        "produto": ["A", "B", "C", "A", "B"] * 20,
        "categoria": ["X", "Y"] * 50,
        "valor": [10.5, 20.0, 15.3, 8.9, 22.1] * 20,
    })
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("vendas.csv", df.to_csv(index=False))

    loaded = _load_all(buf.getvalue())
    profile = build_dataset_profile(loaded)
    con, views = build_connection(loaded)
    fp = profile["arquivos"][0]
    semantic = choose_semantic_columns(fp)
    assert semantic["coluna_uf"] is None
    assert semantic["coluna_lat"] is None
    assert semantic["coluna_lon"] is None

    ov = compute_overview(con, views[fp["arquivo"]], fp, semantic)
    assert "mapa_uf" not in ov
    assert "geo_amostra" not in ov


def test_overview_filtro_de_ano_nao_quebra_serie_temporal_nem_mapa():
    """Regressao: quando um filtro (ex.: ano) esta ativo, as consultas
    de serie temporal e mapa geografico concatenavam duas clausulas
    WHERE em sequencia, o que e SQL invalido e derrubava o calculo. As
    consultas devem combinar as condicoes com AND em uma unica
    clausula WHERE."""
    from src.overview import choose_semantic_columns, compute_overview, build_where_clause

    loaded = _load_sample("exemplo_sisser.zip")
    profile = build_dataset_profile(loaded)
    con, views = build_connection(loaded)
    fp = [f for f in profile["arquivos"] if f["arquivo"] == "dados_abertos_psr_2016a2024csv.csv"][0]
    semantic = choose_semantic_columns(fp)
    view = views[fp["arquivo"]]

    where_clause = build_where_clause({"ano": {"coluna": semantic["coluna_data"], "valores": [2019]}})
    ov = compute_overview(con, view, fp, semantic, where_clause)

    assert ov["total_linhas"] > 0
    assert ov.get("serie_temporal") is not None
    assert len(ov["serie_temporal"]) == 1
    assert ov["serie_temporal"]["periodo"].iloc[0] == 2019
    assert ov.get("mapa_uf") is not None
    assert len(ov["mapa_uf"]) > 0


def test_geojson_estados_brasileiros_existe_e_cobre_27_uf():
    import json
    import os

    caminho = os.path.join(os.path.dirname(__file__), "..", "assets", "br_uf.geojson")
    assert os.path.exists(caminho), "assets/br_uf.geojson nao encontrado"
    with open(caminho, encoding="utf-8") as f:
        geo = json.load(f)
    siglas = {feat["properties"]["sigla"] for feat in geo["features"]}
    assert len(siglas) == 27


def test_query_engine_bloqueia_comandos_fora_de_select():
    loaded = _load_sample("exemplo_nfe.zip")
    con, views = build_connection(loaded)
    try:
        run_sql(con, "DROP TABLE " + list(views.values())[0])
        assert False, "deveria ter bloqueado comando fora de SELECT/WITH"
    except ValueError:
        pass
