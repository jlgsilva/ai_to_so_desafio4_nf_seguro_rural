"""
InsurMinds - Desafio 4
Interface Inteligente para Consulta de Arquivos CSV

Aplicacao construida para o Desafio 4 do curso InsurMinds (I2A2).
Cumpre os requisitos minimos do desafio (upload de .zip, agente
inteligente respondendo perguntas em linguagem natural, respostas em
texto/tabela/grafico) e foi direcionada, como estudo de caso
principal, para analise de dados do SISSER - Sistema de Subvencao
Economica ao Premio do Seguro Rural (MAPA). Tambem funciona com
arquivos de Nota Fiscal Eletronica (NFe/NFCe), usados como exemplo de
validacao no desenvolvimento, e com qualquer outro CSV tabular, gracas
ao agente de perfilamento automatico.

Ver README.md para detalhes de arquitetura e instrucoes de uso.
"""

from __future__ import annotations

import os
import streamlit as st
import plotly.express as px
from dotenv import load_dotenv

from src.ingestion import load_all
from src.profiling import build_dataset_profile
from src.agents.profiler_agent import run_profiler_agent
from src.agents.pipeline import answer_question
from src.query_engine import build_connection
from src.overview import (
    choose_semantic_columns, compute_overview, build_where_clause,
    get_distinct_values, get_distinct_years, list_columns_by_type,
)
from src.suggestions import suggest_questions
from src import storage
from src.logging_config import get_logger, read_recent_logs

log = get_logger("app")

load_dotenv()


@st.cache_data(show_spinner=False)
def _load_br_uf_geojson():
    import json
    with open("assets/br_uf.geojson", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(show_spinner=False)
def _load_br_municipios_geojson():
    import json
    with open("assets/br_municipios.geojson", encoding="utf-8") as f:
        return json.load(f)

st.set_page_config(
    page_title="InsurMinds - Desafio 4",
    page_icon=":bar_chart:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

if not os.getenv("GROQ_API_KEY"):
    try:
        os.environ["GROQ_API_KEY"] = st.secrets["GROQ_API_KEY"]
    except Exception:
        pass

_CUSTOM_CSS = """
<style>
.im-header {
    padding: 1.1rem 1.4rem;
    border-radius: 10px;
    background: linear-gradient(135deg, #1F4E79 0%, #2E6DA4 100%);
    color: white;
    margin-bottom: 1.2rem;
}
.im-header h1 { font-size: 1.5rem; margin: 0 0 0.25rem 0; color: white; }
.im-header p { margin: 0; opacity: 0.9; font-size: 0.92rem; }
.im-card {
    background: var(--secondary-background-color, #F0F2F6);
    border: 1px solid rgba(31, 78, 121, 0.12);
    border-left: 4px solid #1F4E79;
    border-radius: 8px;
    padding: 0.85rem 1rem;
    margin-bottom: 0.6rem;
}
.im-card h4 { margin: 0 0 0.2rem 0; font-size: 0.82rem; color: #5b6b7a; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; }
.im-card .im-value { font-size: 1.5rem; font-weight: 700; color: #1F4E79; }
div.stButton > button[kind="secondary"] {
    border-radius: 20px;
    border: 1px solid #1F4E79;
    color: #1F4E79;
    padding: 0.25rem 0.9rem;
    font-size: 0.85rem;
}
</style>
"""
st.markdown(_CUSTOM_CSS, unsafe_allow_html=True)


def _plot_bar_ajustavel(df, x_col, y_col, orientation="v", key_prefix="bar", height=320):
    """Grafico de barras que evita o problema classico de dados reais
    distorcidos: quando uma categoria concentra um valor muito maior
    que as demais, o eixo linear "esmaga" as barras pequenas ate
    ficarem invisiveis. Esta funcao sempre mostra o valor de cada barra
    como rotulo (visivel mesmo quando a barra e minuscula) e sugere
    escala logaritmica automaticamente quando detecta essa distorcao
    (razao entre o maior e o menor valor positivo acima de 50x),
    deixando o usuario alternar livremente."""
    valor_col = y_col if orientation == "v" else x_col
    valores = df[valor_col]
    positivos = valores[valores > 0]
    todos_positivos = len(positivos) == len(valores) and len(positivos) > 0
    razao = (positivos.max() / positivos.min()) if len(positivos) > 1 else 1

    usar_log = False
    if todos_positivos and razao > 50:
        usar_log = st.checkbox(
            "Escala logaritmica (ha valores muito diferentes entre si nesta coluna)",
            value=True, key=f"log_{key_prefix}",
        )

    fmt = "{text:.2s}"
    if orientation == "v":
        fig = px.bar(df, x=x_col, y=y_col, text=y_col)
        fig.update_traces(texttemplate=fmt, textposition="outside")
        if usar_log:
            fig.update_yaxes(type="log")
    else:
        fig = px.bar(df, x=x_col, y=y_col, orientation="h", text=x_col)
        fig.update_traces(texttemplate=fmt, textposition="outside")
        if usar_log:
            fig.update_xaxes(type="log")

    fig.update_layout(margin=dict(t=10, b=10), height=height, uniformtext_minsize=8)
    st.plotly_chart(fig, width='stretch')


def _init_state():
    defaults = {
        "loaded_files": None,
        "dataset_profile": None,
        "duckdb_con": None,
        "view_names": None,
        "dataset_id": None,
        "chat_history": [],
        "pending_question": None,
        "last_upload_signature": None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


_init_state()

st.markdown(
    """
    <div class="im-header">
        <h1>InsurMinds - Interface Inteligente para Consulta de Arquivos CSV</h1>
        <p>Direcionado para analise de dados do SISSER (Seguro Rural). Tambem funciona com
        Nota Fiscal Eletronica (NFe/NFCe) e outros CSVs tabulares.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

if not os.getenv("GROQ_API_KEY"):
    st.error(
        "GROQ_API_KEY nao configurada. Defina em um arquivo .env local "
        "(GROQ_API_KEY=sua_chave) ou em Settings > Secrets no Streamlit Cloud."
    )

tab_upload, tab_overview, tab_chat, tab_historico, tab_sobre = st.tabs(
    ["Carga de dados", "Visao geral", "Perguntas", "Historico", "Sobre / Arquitetura"]
)

# ---------------------------------------------------------------------------
# Interface A - Carga dos dados
# ---------------------------------------------------------------------------
with tab_upload:
    st.subheader("Envio do arquivo .zip")
    st.write(
        "Envie um arquivo .zip contendo um ou mais arquivos .csv. Se houver um "
        "dicionario de dados (PDF, TXT ou CSV descrevendo as colunas), ele pode "
        "ser incluido no mesmo .zip; o agente de perfilamento tentara reconhecer "
        "automaticamente o formato mesmo sem ele."
    )

    uploaded_zip = st.file_uploader("Arquivo .zip", type=["zip"])

    col_a, col_b = st.columns([1, 1])
    with col_a:
        exemplo_sisser = st.button("Usar exemplo SISSER (Seguro Rural)", width='stretch')
    with col_b:
        exemplo_nfe = st.button("Usar exemplo NFe", width='stretch')

    zip_bytes = None
    zip_name = None
    signature = None

    if uploaded_zip is not None:
        signature = ("upload", uploaded_zip.name, uploaded_zip.size)
        if st.session_state.get("last_upload_signature") != signature:
            zip_bytes = uploaded_zip.read()
            zip_name = uploaded_zip.name
    elif exemplo_sisser:
        signature = ("exemplo_sisser",)
        with open("sample_data/exemplo_sisser.zip", "rb") as f:
            zip_bytes = f.read()
        zip_name = "exemplo_sisser.zip"
    elif exemplo_nfe:
        signature = ("exemplo_nfe",)
        with open("sample_data/exemplo_nfe.zip", "rb") as f:
            zip_bytes = f.read()
        zip_name = "exemplo_nfe.zip"

    if zip_bytes is not None:
        with st.spinner("Processando arquivos: detectando encoding, delimitador e schema..."):
            try:
                log.info("Upload recebido: %s (%.2f MB)", zip_name, len(zip_bytes) / (1024 * 1024))
                loaded_files = load_all(zip_bytes)
                dataset_profile = build_dataset_profile(loaded_files)
                dataset_profile = run_profiler_agent(dataset_profile)
                con, view_names = build_connection(loaded_files)

                dataset_id = storage.save_dataset(
                    zip_name, list(loaded_files.keys()), dataset_profile
                )

                st.session_state.loaded_files = loaded_files
                st.session_state.dataset_profile = dataset_profile
                st.session_state.duckdb_con = con
                st.session_state.view_names = view_names
                st.session_state.dataset_id = dataset_id
                st.session_state.chat_history = []
                st.session_state.last_upload_signature = signature

                st.success(f"{len(loaded_files)} arquivo(s) processado(s) com sucesso. Veja a aba 'Visao geral'.")
            except Exception as exc:
                log.exception("Falha ao processar upload %s", zip_name)
                st.error(f"Falha ao processar o arquivo: {exc}")
                with st.expander("Detalhes tecnicos do erro"):
                    st.exception(exc)

    if st.session_state.dataset_profile:
        profile = st.session_state.dataset_profile
        st.markdown("### Resumo gerado pelo agente")
        st.write(profile.get("resumo_ia", ""))

        for fp in profile["arquivos"]:
            with st.expander(f"{fp['arquivo']} - familia: {fp['familia_nome']}"):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Linhas", f"{fp['linhas_totais']:,}".replace(",", "."))
                c2.metric("Tamanho (MB)", fp["tamanho_mb"])
                c3.metric("Encoding original", fp["encoding_detectado"])
                c4.metric("Delimitador", repr(fp["delimitador_detectado"]))
                if fp["arquivo_grande"]:
                    st.info(
                        "Arquivo grande: o perfilamento usou amostra, mas as respostas "
                        "do chat consultam o arquivo completo via DuckDB."
                    )
                if fp.get("dominio_sugerido_ia"):
                    st.write(f"**Dominio sugerido pela IA:** {fp['dominio_sugerido_ia']}")
                st.dataframe(
                    [{"coluna": c, **stats} for c, stats in fp["perfil_colunas"].items()],
                    width='stretch',
                )

        if profile["relacionamentos"]:
            st.markdown("### Relacionamento entre arquivos")
            for rel in profile["relacionamentos"]:
                st.write(
                    f"`{rel['arquivo_a']}` e `{rel['arquivo_b']}` compartilham as "
                    f"colunas: {', '.join(rel['colunas_em_comum'])}"
                )

# ---------------------------------------------------------------------------
# Visao geral (dashboard automatico, sem LLM)
# ---------------------------------------------------------------------------
with tab_overview:
    if not st.session_state.dataset_profile:
        st.info("Envie um arquivo .zip na aba 'Carga de dados' para ver a visao geral.")
    else:
        profile = st.session_state.dataset_profile
        con = st.session_state.duckdb_con
        view_names = st.session_state.view_names
        arquivos = profile["arquivos"]

        nomes_arquivo = [f["arquivo"] for f in arquivos]
        arquivo_escolhido = st.selectbox("Arquivo para explorar", nomes_arquivo)
        fp = next(f for f in arquivos if f["arquivo"] == arquivo_escolhido)
        view = view_names[arquivo_escolhido]
        semantic = choose_semantic_columns(fp)
        colunas_disponiveis = list_columns_by_type(fp)

        with st.expander("Filtros e colunas exibidas", expanded=False):
            st.caption(
                "As colunas de dimensao e valor abaixo definem os graficos de "
                "distribuicao. Por padrao usam a deteccao automatica, mas podem "
                "ser trocadas para qualquer outra coluna do arquivo."
            )
            col_sel1, col_sel2 = st.columns(2)
            with col_sel1:
                opcoes_dim = ["(nenhuma)"] + colunas_disponiveis["texto"]
                indice_dim = opcoes_dim.index(semantic["coluna_dimensao"]) if semantic["coluna_dimensao"] in opcoes_dim else 0
                dim_escolhida = st.selectbox("Coluna de dimensao (categoria)", opcoes_dim, index=indice_dim)
                dim_escolhida = None if dim_escolhida == "(nenhuma)" else dim_escolhida
            with col_sel2:
                opcoes_valor = ["(contagem de registros)"] + colunas_disponiveis["numero"]
                indice_valor = opcoes_valor.index(semantic["coluna_valor"]) if semantic["coluna_valor"] in opcoes_valor else 0
                valor_escolhido = st.selectbox("Coluna de valor (numerica)", opcoes_valor, index=indice_valor)
                valor_escolhido = None if valor_escolhido == "(contagem de registros)" else valor_escolhido

            filtros = {}
            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                if dim_escolhida:
                    valores_disponiveis = get_distinct_values(con, view, dim_escolhida)
                    selecionados = st.multiselect(f"Filtrar por {dim_escolhida}", valores_disponiveis)
                    if selecionados:
                        filtros["dimensao"] = {"coluna": dim_escolhida, "valores": selecionados}
            with col_f2:
                if semantic["coluna_uf"]:
                    ufs_disponiveis = get_distinct_values(con, view, semantic["coluna_uf"])
                    ufs_selecionadas = st.multiselect(f"Filtrar por UF ({semantic['coluna_uf']})", ufs_disponiveis)
                    if ufs_selecionadas:
                        filtros["uf"] = {"coluna": semantic["coluna_uf"], "valores": ufs_selecionadas}
            with col_f3:
                if semantic["coluna_data"]:
                    anos_disponiveis = get_distinct_years(con, view, semantic["coluna_data"])
                    anos_selecionados = st.multiselect("Filtrar por ano", anos_disponiveis)
                    if anos_selecionados:
                        filtros["ano"] = {"coluna": semantic["coluna_data"], "valores": anos_selecionados}

        semantic_efetivo = dict(semantic)
        semantic_efetivo["coluna_dimensao"] = dim_escolhida
        semantic_efetivo["coluna_valor"] = valor_escolhido
        where_clause = build_where_clause(filtros)

        with st.spinner("Calculando indicadores..."):
            try:
                ov = compute_overview(con, view, fp, semantic_efetivo, where_clause)
            except Exception as exc:
                log.exception("Falha ao calcular visao geral para %s", arquivo_escolhido)
                st.error(f"Nao foi possivel calcular a visao geral: {exc}")
                ov = None

        if ov:
            k1, k2, k3, k4 = st.columns(4)
            with k1:
                st.markdown(f'<div class="im-card"><h4>Linhas (filtro atual)</h4><div class="im-value">{ov["total_linhas"]:,}</div></div>'.replace(",", "."), unsafe_allow_html=True)
            with k2:
                st.markdown(f'<div class="im-card"><h4>Total de arquivos</h4><div class="im-value">{len(arquivos)}</div></div>', unsafe_allow_html=True)
            with k3:
                st.markdown(f'<div class="im-card"><h4>% nulo medio</h4><div class="im-value">{ov["pct_nulo_medio"]}%</div></div>', unsafe_allow_html=True)
            with k4:
                dim_label = dim_escolhida or "-"
                st.markdown(f'<div class="im-card"><h4>Dimensao exibida</h4><div class="im-value" style="font-size:1.1rem">{dim_label}</div></div>', unsafe_allow_html=True)

            col_g1, col_g2 = st.columns(2)
            with col_g1:
                if ov.get("top_categoria") is not None and len(ov["top_categoria"]):
                    st.markdown(f"**Registros por {dim_escolhida}**")
                    _plot_bar_ajustavel(ov["top_categoria"], "categoria", "contagem", key_prefix="top_categoria")
            with col_g2:
                if ov.get("valor_por_categoria") is not None and len(ov["valor_por_categoria"]):
                    st.markdown(f"**{valor_escolhido} por {dim_escolhida}**")
                    _plot_bar_ajustavel(ov["valor_por_categoria"], "categoria", "total", key_prefix="valor_categoria")

            if ov.get("serie_temporal") is not None and len(ov["serie_temporal"]) > 1:
                st.markdown("**Evolucao ao longo do tempo**")
                fig = px.line(ov["serie_temporal"], x="periodo", y="total", markers=True)
                fig.update_layout(margin=dict(t=10, b=10), height=300)
                st.plotly_chart(fig, width='stretch')

            if ov.get("geo_amostra") is not None and len(ov["geo_amostra"]) > 0:
                st.markdown(f"**Distribuicao geografica** (amostra de {len(ov['geo_amostra']):,} pontos)".replace(",", "."))
                fig = px.scatter_mapbox(
                    ov["geo_amostra"], lat="lat", lon="lon", zoom=3, height=420,
                    opacity=0.5,
                )
                fig.update_layout(mapbox_style="open-street-map", margin=dict(t=10, b=10, l=0, r=0))
                st.plotly_chart(fig, width='stretch')

            tem_mapa_uf = ov.get("mapa_uf") is not None and len(ov["mapa_uf"]) > 0
            tem_mapa_municipio = ov.get("mapa_municipio") is not None and len(ov["mapa_municipio"]) > 0

            if tem_mapa_uf or tem_mapa_municipio:
                st.markdown("**Mapas geograficos**")
                st.caption(
                    "Filtre por UF acima para ver o detalhamento por municipio "
                    "dentro do estado selecionado."
                    if tem_mapa_municipio else ""
                )
                col_m1, col_m2 = st.columns(2) if (tem_mapa_uf and tem_mapa_municipio) else (st.container(), None)

                if tem_mapa_uf:
                    with col_m1:
                        metrica_label = ov.get("mapa_uf_metrica", "quantidade de registros")
                        st.markdown(f"Por UF ({metrica_label})")
                        try:
                            geojson_uf = _load_br_uf_geojson()
                            fig = px.choropleth(
                                ov["mapa_uf"], geojson=geojson_uf, locations="uf",
                                featureidkey="properties.sigla", color="valor",
                                color_continuous_scale="Blues", height=420,
                            )
                            fig.update_geos(fitbounds="locations", visible=False)
                            fig.update_layout(margin=dict(t=10, b=10, l=0, r=0))
                            st.plotly_chart(fig, width='stretch')
                        except Exception as exc:
                            log.exception("Falha ao renderizar mapa por UF")
                            st.caption(f"Nao foi possivel renderizar o mapa por UF: {exc}")

                if tem_mapa_municipio:
                    destino = col_m2 if col_m2 is not None else col_m1
                    with destino:
                        metrica_label = ov.get("mapa_municipio_metrica", "quantidade de registros")
                        st.markdown(f"Por municipio ({metrica_label})")
                        try:
                            geojson_mun = _load_br_municipios_geojson()
                            fig = px.choropleth(
                                ov["mapa_municipio"], geojson=geojson_mun, locations="geocodigo",
                                featureidkey="properties.id", color="valor",
                                color_continuous_scale="Oranges", height=420,
                            )
                            fig.update_geos(fitbounds="locations", visible=False)
                            fig.update_layout(margin=dict(t=10, b=10, l=0, r=0))
                            st.plotly_chart(fig, width='stretch')
                        except Exception as exc:
                            log.exception("Falha ao renderizar mapa por municipio")
                            st.caption(f"Nao foi possivel renderizar o mapa por municipio: {exc}")

            st.markdown("**Qualidade dos dados (percentual de valores nulos por coluna)**")
            df_qualidade = ov["qualidade_dados"]
            colunas_com_nulo = df_qualidade[df_qualidade["pct_nulo"] > 0]
            if len(colunas_com_nulo):
                altura = max(250, 22 * len(colunas_com_nulo.head(20)))
                _plot_bar_ajustavel(
                    colunas_com_nulo.head(20), "pct_nulo", "coluna",
                    orientation="h", key_prefix="qualidade_dados", height=altura,
                )
            else:
                st.caption("Nenhuma coluna com valores nulos detectados na amostra perfilada.")

# ---------------------------------------------------------------------------
# Interface B - Consulta em linguagem natural
# ---------------------------------------------------------------------------
def _process_question(pergunta: str):
    with st.spinner("Planejando, gerando consulta e calculando..."):
        try:
            result = answer_question(
                st.session_state.duckdb_con,
                st.session_state.view_names,
                st.session_state.dataset_profile,
                pergunta,
            )
            storage.save_query(st.session_state.dataset_id, result)
            st.session_state.chat_history.append(result)
        except Exception as exc:
            log.exception("Erro inesperado no pipeline de agentes para a pergunta: %s", pergunta)
            st.session_state.chat_history.append({
                "sucesso": False, "pergunta": pergunta,
                "sql_final": "", "erro": str(exc),
            })


with tab_chat:
    if not st.session_state.dataset_profile:
        st.info("Envie um arquivo .zip na aba 'Carga de dados' para comecar.")
    else:
        if not st.session_state.chat_history:
            st.markdown("**Sugestoes de perguntas para estes dados**")
            sugestoes = suggest_questions(st.session_state.dataset_profile)
            n_cols = 2
            cols = st.columns(n_cols)
            for i, sugestao in enumerate(sugestoes):
                if cols[i % n_cols].button(sugestao, key=f"sugestao_{i}", type="secondary", width='stretch'):
                    st.session_state.pending_question = sugestao
            st.divider()

        st.subheader("Pergunte em linguagem natural")

        for idx_turno, turno in enumerate(st.session_state.chat_history):
            with st.chat_message("user"):
                st.write(turno.get("pergunta", ""))
            with st.chat_message("assistant"):
                df_res = turno.get("tabela_resultado")
                if turno.get("sucesso") and df_res is not None:
                    st.write(turno.get("texto_resposta", ""))
                    tipo = turno.get("tipo_visualizacao", "texto")
                    if tipo == "grafico_barras" and df_res.shape[1] >= 2:
                        _plot_bar_ajustavel(
                            df_res, df_res.columns[0], df_res.columns[1],
                            key_prefix=f"chat_{idx_turno}",
                        )
                    elif tipo == "grafico_linha" and df_res.shape[1] >= 2:
                        fig = px.line(df_res, x=df_res.columns[0], y=df_res.columns[1])
                        st.plotly_chart(fig, width='stretch')
                    elif tipo == "grafico_pizza" and df_res.shape[1] >= 2:
                        fig = px.pie(df_res, names=df_res.columns[0], values=df_res.columns[1])
                        st.plotly_chart(fig, width='stretch')
                    if tipo != "texto":
                        with st.expander("Ver tabela de resultado"):
                            st.dataframe(df_res, width='stretch')
                    with st.expander("Detalhes tecnicos (plano e SQL gerados pelos agentes)"):
                        st.json(turno.get("plano", {}))
                        st.code(turno.get("sql_final", ""), language="sql")
                        st.caption(f"Tempo total: {turno.get('tempo_segundos', '-')}s")
                else:
                    st.error(f"Nao foi possivel responder: {turno.get('erro', 'erro desconhecido')}")
                    if turno.get("sql_final"):
                        with st.expander("SQL que falhou"):
                            st.code(turno["sql_final"], language="sql")

        if st.session_state.pending_question:
            pergunta = st.session_state.pending_question
            st.session_state.pending_question = None
            with st.chat_message("user"):
                st.write(pergunta)
            with st.chat_message("assistant"):
                _process_question(pergunta)
            st.rerun()

        pergunta_digitada = st.chat_input("Ex.: qual foi o total de subvencao federal pago em 2024 por UF?")
        if pergunta_digitada:
            with st.chat_message("user"):
                st.write(pergunta_digitada)
            with st.chat_message("assistant"):
                _process_question(pergunta_digitada)
            st.rerun()

# ---------------------------------------------------------------------------
# Historico
# ---------------------------------------------------------------------------
with tab_historico:
    st.subheader("Datasets processados anteriormente")
    st.dataframe(storage.list_datasets(), width='stretch')

    st.subheader("Perguntas realizadas")
    st.dataframe(
        storage.list_queries().drop(columns=["plano_json", "resultado_preview_json"], errors="ignore"),
        width='stretch',
    )

    st.subheader("Log da aplicacao")
    st.caption(
        "Registro tecnico de tudo que a aplicacao executou nesta instalacao "
        "(ingestao, chamadas aos agentes, planos, SQL gerado e erros com "
        "detalhe completo). Util para diagnosticar problemas."
    )
    n_linhas = st.slider("Linhas mais recentes a exibir", 50, 1000, 300, step=50)
    log_text = read_recent_logs(n_linhas)
    st.text_area("logs/app.log", log_text, height=300)
    st.download_button(
        "Baixar log completo",
        data=log_text,
        file_name="app.log",
        mime="text/plain",
    )

# ---------------------------------------------------------------------------
# Sobre / arquitetura
# ---------------------------------------------------------------------------
with tab_sobre:
    st.markdown(open("README.md", encoding="utf-8").read())
