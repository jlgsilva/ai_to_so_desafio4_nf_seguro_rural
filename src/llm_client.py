"""
Cliente de LLM via Groq (modelos gratuitos / production tier).

Dois modelos sao usados, com papeis diferentes:
- MODEL_RACIOCINIO: usado pelos agentes que precisam planejar e gerar
  codigo (Planner e Executor).
- MODEL_RAPIDO: usado para tarefas simples e baratas (classificacao de
  dominio, redacao final da resposta).

A escolha do modelo de raciocinio prioriza o limite de TOKENS POR
MINUTO (TPM), nao apenas o limite diario (TPD): o perfil dos dados
enviado ao Planner e ao Executor, mesmo apos compactado e deduplicado
(ver src/profiling.py), pode chegar a alguns milhares de tokens em
datasets com muitas colunas, e o Planner + Executor costumam disparar
mais de uma chamada dentro do mesmo minuto (planejamento, geracao de
SQL e, eventualmente, correcao de erro). Um modelo com TPM baixo pode
rejeitar uma unica chamada mesmo estando bem abaixo do limite diario.

Tabela de referencia (conta gratuita, ver
https://console.groq.com/docs/rate-limits):

  modelo                     RPM   RPD     TPM     TPD
  llama-3.3-70b-versatile     30   1.000   12.000  100.000
  openai/gpt-oss-120b         30   1.000    8.000  200.000
  openai/gpt-oss-20b          30   1.000    8.000  200.000
  llama-3.1-8b-instant        30  14.400    6.000  500.000

llama-3.3-70b-versatile tem o maior TPM (12.000) entre os modelos de
uso geral, o que reduz bastante a chance de erro 413 numa unica
chamada grande. Seu TPD mais baixo (100.000) e um risco menor, pois a
compactacao do perfil ja cortou o consumo por pergunta em mais da
metade.

Os nomes de modelo sao lidos de variavel de ambiente para facilitar
troca sem alterar codigo, caso a Groq altere os limites, deprecie
algum modelo, ou caso o usuario prefira outro equilibrio entre
qualidade e cota disponivel.
"""

from __future__ import annotations

import os
from langchain_groq import ChatGroq

MODEL_RACIOCINIO = os.getenv("GROQ_MODEL_RACIOCINIO", "llama-3.3-70b-versatile")
MODEL_RAPIDO = os.getenv("GROQ_MODEL_RAPIDO", "llama-3.1-8b-instant")


def get_llm(fast: bool = False, temperature: float = 0.0):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY nao encontrada. Configure em .env (local) ou em "
            "Secrets do Streamlit Cloud."
        )
    model = MODEL_RAPIDO if fast else MODEL_RACIOCINIO
    return ChatGroq(model=model, temperature=temperature, api_key=api_key)
