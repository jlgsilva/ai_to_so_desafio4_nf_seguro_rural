"""
Orquestrador do ciclo completo de agentes:

  Profiler -> Planner -> Executor (com auto-correcao) -> Presenter

Cada etapa e isolada e testavel separadamente (ver src/agents/*.py).
Este modulo apenas encadeia as chamadas e monta o objeto de resposta
final que a interface Streamlit consome, alem de gravar cada etapa no
historico (src/storage.py) para auditoria.
"""

from __future__ import annotations

import time
from src.agents.planner_agent import run_planner_agent
from src.agents.executor_agent import run_executor_agent
from src.agents.presenter_agent import run_presenter_agent
from src.logging_config import get_logger

log = get_logger("agents.pipeline")


def answer_question(con, view_names: dict, dataset_profile: dict, pergunta: str) -> dict:
    t0 = time.time()
    log.info("=== Nova pergunta: %s ===", pergunta)

    plan = run_planner_agent(dataset_profile, pergunta)

    exec_result = run_executor_agent(con, view_names, dataset_profile, plan, pergunta)

    if not exec_result["sucesso"]:
        log.error("Pipeline encerrado com falha para a pergunta: %s | erro: %s", pergunta, exec_result["erro"])
        return {
            "sucesso": False,
            "pergunta": pergunta,
            "plano": plan,
            "sql_final": exec_result["sql_final"],
            "erro": exec_result["erro"],
            "tempo_segundos": round(time.time() - t0, 2),
        }

    df_result = exec_result["resultado"]
    apresentacao = run_presenter_agent(pergunta, df_result, plan.get("sugestao_visualizacao"))

    tempo_total = round(time.time() - t0, 2)
    log.info("Pergunta respondida com sucesso em %.2fs (%d tentativas de SQL)", tempo_total, exec_result["tentativas"])

    return {
        "sucesso": True,
        "pergunta": pergunta,
        "plano": plan,
        "sql_final": exec_result["sql_final"],
        "tentativas_execucao": exec_result["tentativas"],
        "texto_resposta": apresentacao["texto"],
        "tipo_visualizacao": apresentacao["tipo_visualizacao"],
        "tabela_resultado": df_result,
        "tempo_segundos": tempo_total,
    }
