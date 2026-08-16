"""
Agente 1 - Data Profiler.

A parte deterministica do perfilamento (encoding, delimitador, tipos,
nulos, deteccao de familia conhecida) ja foi feita em src/profiling.py
sem uso de LLM, propositalmente: numeros e metadados nao devem
depender de geracao probabilistica.

Este agente usa a LLM apenas para a parte que exige linguagem/juizo:
- redigir um resumo do dataset em linguagem natural para o usuario
- quando o arquivo NAO bate com nenhuma familia conhecida (GENERICO),
  pedir para a LLM sugerir, com base nos nomes de coluna e amostras,
  do que provavelmente se trata o dataset.
"""

from __future__ import annotations

import json
from langchain_core.prompts import ChatPromptTemplate
from src.llm_client import get_llm
from src.profiling import build_minimal_profile_summary
from src.logging_config import get_logger

log = get_logger("agents.profiler")

_SUMMARY_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Voce e um agente de perfilamento de dados. Receba um perfil "
     "estatistico de um ou mais arquivos CSV e escreva um resumo curto, "
     "em portugues, em ate 6 linhas, explicando: do que provavelmente "
     "tratam os dados, quais arquivos existem e como parecem se "
     "relacionar, e um alerta se houver algo que mereça atencao do "
     "usuario (muitos nulos, encoding pouco comum, arquivo grande "
     "sendo tratado por amostragem etc). Nao invente numeros que nao "
     "estao no perfil."),
    ("human", "Perfil dos dados (JSON):\n{profile_json}"),
])

_CLASSIFY_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Voce e um classificador de dominio de dados tabulares. Com base "
     "nos nomes de coluna e exemplos de valores fornecidos, diga em uma "
     "frase curta a que tipo de negocio/dominio esses dados "
     "provavelmente pertencem (ex.: notas fiscais, seguros, folha de "
     "pagamento, vendas, logistica, saude). Responda apenas a frase, "
     "sem explicacoes adicionais."),
    ("human", "Colunas: {colunas}\nExemplos de valores: {exemplos}"),
])


def summarize_profile(dataset_profile: dict) -> str:
    minimal = build_minimal_profile_summary(dataset_profile)
    llm = get_llm(fast=True, temperature=0.2)
    chain = _SUMMARY_PROMPT | llm
    log.info("Chamando LLM (resumo do dataset) - %d arquivo(s)", len(minimal["arquivos"]))
    result = chain.invoke({"profile_json": json.dumps(minimal, ensure_ascii=False, default=str)})
    log.info("Resumo gerado com sucesso (%d caracteres)", len(result.content))
    return result.content.strip()


def classify_unknown_domain(file_profile: dict) -> str:
    """So deve ser chamado quando familia_reconhecida == 'GENERICO'."""
    colunas = file_profile["colunas"]
    exemplos = {
        c: file_profile["perfil_colunas"][c].get("exemplos", [])
        for c in colunas[:15]
        if "exemplos" in file_profile["perfil_colunas"].get(c, {})
    }
    llm = get_llm(fast=True, temperature=0.2)
    chain = _CLASSIFY_PROMPT | llm
    log.info("Classificando dominio desconhecido de %s", file_profile["arquivo"])
    result = chain.invoke({"colunas": ", ".join(colunas), "exemplos": json.dumps(exemplos, ensure_ascii=False, default=str)})
    return result.content.strip()


def run_profiler_agent(dataset_profile: dict) -> dict:
    """Enriquece o dataset_profile com resumo em linguagem natural e,
    para arquivos genericos, uma classificacao de dominio sugerida."""
    for file_profile in dataset_profile["arquivos"]:
        if file_profile["familia_reconhecida"] == "GENERICO":
            try:
                file_profile["dominio_sugerido_ia"] = classify_unknown_domain(file_profile)
            except Exception as exc:
                log.exception("Falha ao classificar dominio de %s", file_profile["arquivo"])
                file_profile["dominio_sugerido_ia"] = f"(nao foi possivel classificar: {exc})"

    try:
        dataset_profile["resumo_ia"] = summarize_profile(dataset_profile)
    except Exception as exc:
        log.exception("Falha ao gerar resumo do dataset")
        dataset_profile["resumo_ia"] = (
            f"Nao foi possivel gerar o resumo automatico ({exc}). "
            "Os dados foram carregados normalmente e podem ser consultados na aba de chat."
        )
    return dataset_profile
