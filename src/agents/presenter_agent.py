"""
Agente 4 - Presenter.

Recebe o resultado JA CALCULADO (DataFrame pequeno, produto do
Executor Agent) e:
- escreve a resposta em linguagem natural, ancorada nos numeros reais
  do resultado (a LLM recebe o resultado como tabela, nao gera os
  numeros)
- decide o tipo de grafico mais adequado (barra, linha, pizza, tabela
  simples ou nenhum), quando o Planner nao tiver decidido isso via
  regra fixa

A LLM aqui nunca recalcula nada: apenas descreve o que ja veio pronto.
"""

from __future__ import annotations

import json
import pandas as pd
from langchain_core.prompts import ChatPromptTemplate
from src.llm_client import get_llm
from src.logging_config import get_logger

log = get_logger("agents.presenter")

_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Voce e um agente que explica resultados de analise de dados para "
     "um publico de negocio, sem jargao tecnico desnecessario. Voce "
     "recebe uma pergunta e uma tabela de resultado (ja calculada, "
     "correta). Escreva uma resposta objetiva em portugues, em "
     "paragrafo curto (ate 5 linhas), citando os numeros exatos que "
     "aparecem na tabela. Nao invente numeros que nao estejam na "
     "tabela. Se a tabela tiver uma unica linha/valor, responda de "
     "forma direta."),
    ("human",
     "Pergunta: {pergunta}\n\nResultado (JSON, ate 15 linhas):\n{resultado_json}"),
])


def _suggest_chart_type(df: pd.DataFrame, plan_hint: str | None) -> str:
    if plan_hint in ("grafico_barras", "grafico_linha", "grafico_pizza", "tabela", "texto"):
        pass
    if df.shape[0] == 1 and df.shape[1] <= 2:
        return "texto"
    if df.shape[1] < 2:
        return "tabela"
    numeric_cols = df.select_dtypes(include="number").columns
    if len(numeric_cols) == 0:
        return "tabela"
    if plan_hint == "grafico_linha":
        return "grafico_linha"
    if plan_hint == "grafico_pizza" and df.shape[0] <= 12:
        return "grafico_pizza"
    if df.shape[0] <= 30:
        return "grafico_barras"
    return "tabela"


def run_presenter_agent(pergunta: str, df_result: pd.DataFrame, plan_hint: str | None) -> dict:
    # limite conservador de linhas/tamanho de texto, para nao estourar
    # o limite de tokens por minuto de contas Groq gratuitas
    preview = df_result.head(15).copy()
    for col in preview.select_dtypes(include="object").columns:
        preview[col] = preview[col].astype(str).str.slice(0, 60)

    chart_type = _suggest_chart_type(df_result, plan_hint)

    try:
        llm = get_llm(fast=True, temperature=0.1)
        chain = _PROMPT | llm
        log.info("Redigindo resposta final para: %s", pergunta)
        resposta = chain.invoke({
            "pergunta": pergunta,
            "resultado_json": preview.to_json(orient="records", force_ascii=False),
        }).content.strip()
    except Exception as exc:
        log.exception("Falha ao gerar texto de resposta; usando fallback simples")
        if df_result.shape == (1, 1):
            resposta = f"Resultado: {df_result.iloc[0, 0]}"
        else:
            resposta = (
                "Nao foi possivel gerar a explicacao em linguagem natural "
                f"({exc}). O resultado calculado esta na tabela abaixo."
            )

    return {
        "texto": resposta,
        "tipo_visualizacao": chart_type,
        "tabela": df_result,
    }
