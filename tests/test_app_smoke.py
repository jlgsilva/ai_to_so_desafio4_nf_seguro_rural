"""
Testes de fumaca da interface (Streamlit AppTest).

Carregam o app.py de verdade, simulam o clique nos botoes de exemplo
e verificam que nenhuma excecao e lancada ao renderizar as abas de
Carga de dados, Visao geral e Perguntas. Nao dependem de GROQ_API_KEY:
o resumo em linguagem natural falha graciosamente sem chave (com
fallback tratado no proprio codigo) e isso e esperado aqui.
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from streamlit.testing.v1 import AppTest


def _fresh_app():
    at = AppTest.from_file(
        os.path.join(os.path.dirname(__file__), "..", "app.py"),
        default_timeout=120,
    )
    at.run()
    return at


def test_app_carrega_sem_excecoes():
    at = _fresh_app()
    assert not at.exception
    assert len(at.tabs) == 5


def test_upload_exemplo_sisser_sem_excecoes():
    at = _fresh_app()
    btn = [b for b in at.tabs[0].button if "SISSER" in b.label][0]
    btn.click().run()
    assert not at.exception

    overview_tab = at.tabs[1]
    assert len(overview_tab.selectbox) == 3
    assert not at.exception

    chat_tab = at.tabs[2]
    labels = [b.label for b in chat_tab.button]
    assert any("subvenc" in l.lower() for l in labels)


def test_upload_exemplo_nfe_sem_excecoes():
    at = _fresh_app()
    btn = [b for b in at.tabs[0].button if "NFe" in b.label][0]
    btn.click().run()
    assert not at.exception

    chat_tab = at.tabs[2]
    labels = [b.label for b in chat_tab.button]
    assert len(labels) > 0
    assert not at.exception


def test_rerun_nao_reprocessa_upload_nem_apaga_historico_do_chat():
    """Regressao: apos responder uma pergunta, o app chama st.rerun(),
    o que reexecuta o script inteiro do zero. Antes da correcao, isso
    fazia o bloco de upload rodar de novo (reprocessando os arquivos
    inteiros) e resetava st.session_state.chat_history = [], apagando
    a resposta que acabara de ser calculada. O usuario via a pergunta
    "ficar processando" e depois nao retornar nada. Este teste simula
    exatamente esse rerun (sem clicar em nenhum botao de novo) e
    confirma que o dataset carregado e o historico de chat permanecem
    intactos."""
    at = _fresh_app()
    btn = [b for b in at.tabs[0].button if "SISSER" in b.label][0]
    btn.click().run()
    assert not at.exception

    dataset_id_antes = at.session_state["dataset_id"]
    assinatura_antes = at.session_state["last_upload_signature"]

    # simula uma resposta ja registrada no historico, como aconteceria
    # apos o pipeline de agentes responder uma pergunta
    at.session_state["chat_history"] = [{
        "sucesso": True, "pergunta": "pergunta de teste",
        "texto_resposta": "resposta de teste", "tipo_visualizacao": "texto",
        "plano": {}, "sql_final": "SELECT 1", "tempo_segundos": 1.0,
        "tabela_resultado": __import__("pandas").DataFrame({"resultado": [42]}),
    }]

    # simula o rerun disparado pelo st.rerun() apos responder, sem
    # nenhum clique novo em botao ou uploader
    at.run()

    assert not at.exception
    assert at.session_state["dataset_id"] == dataset_id_antes
    assert at.session_state["last_upload_signature"] == assinatura_antes
    assert len(at.session_state["chat_history"]) == 1
    assert at.session_state["chat_history"][0]["pergunta"] == "pergunta de teste"


def test_mapa_por_uf_e_municipio_aparecem_para_sisser_sem_excecoes():
    """O SISSER tem coluna de UF (SG_UF_PROPRIEDADE) e coluna de codigo
    IBGE de municipio (CD_GEOCMU), entao os dois mapas devem aparecer
    na Visao Geral sem erro, e um filtro por UF deve continuar
    funcionando (drill-down para os municipios daquele estado)."""
    at = _fresh_app()
    btn = [b for b in at.tabs[0].button if "SISSER" in b.label][0]
    btn.click().run()
    assert not at.exception

    overview_tab = at.tabs[1]
    # arquivo 2016-2024 tem os campos mais completos; troca a selecao
    arquivo_select = overview_tab.selectbox[0]
    arquivo_select.set_value("dados_abertos_psr_2016a2024csv.csv").run()
    assert not at.exception

    overview_tab = at.tabs[1]
    n_plotly_antes = len(overview_tab.get("plotly_chart"))
    assert n_plotly_antes > 0

    # filtra por UF = GO usando o multiselect dedicado de UF, dentro do
    # expander de filtros
    multiselects = overview_tab.multiselect
    uf_multiselect = [m for m in multiselects if "UF" in m.label][0]
    uf_multiselect.set_value(["GO"]).run()
    assert not at.exception
