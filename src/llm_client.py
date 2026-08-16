"""
Cliente de LLM via Groq (modelos gratuitos / production tier).

Dois modelos sao usados, com papeis diferentes:
- MODEL_RACIOCINIO: usado pelos agentes que precisam planejar e gerar
  codigo (Planner e Executor).
- MODEL_RAPIDO: usado para tarefas simples e baratas (classificacao de
  dominio, redacao final da resposta).

A escolha dos modelos prioriza o limite de tokens por dia (TPD) da
conta gratuita da Groq, nao apenas a qualidade bruta do modelo. O
Planner e o Executor sao os agentes que mais consomem tokens (enviam
o perfil dos dados e recebem respostas mais longas), entao usam um
modelo com folga de cota maior que o padrao llama-3.3-70b-versatile
(cujo limite diario de 100 mil tokens se esgota rapido em uma sessao
de poucas perguntas). Ver tabela oficial de limites em
https://console.groq.com/docs/rate-limits.

Os nomes de modelo sao lidos de variavel de ambiente para facilitar
troca sem alterar codigo, caso a Groq altere os limites ou deprecie
algum modelo.
"""

from __future__ import annotations

import os
from langchain_groq import ChatGroq

MODEL_RACIOCINIO = os.getenv("GROQ_MODEL_RACIOCINIO", "openai/gpt-oss-120b")
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
