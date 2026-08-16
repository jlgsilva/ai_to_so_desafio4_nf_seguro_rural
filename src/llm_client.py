"""
Cliente de LLM via Groq (modelos gratuitos / production tier).

Dois modelos sao usados, com papeis diferentes:
- MODEL_RACIOCINIO: usado pelos agentes que precisam planejar e gerar
  codigo (Planner e Executor). Modelo maior, mais preciso.
- MODEL_RAPIDO: usado para tarefas simples e baratas (classificacao de
  dominio, redacao final da resposta).

Os nomes de modelo sao lidos de variavel de ambiente para facilitar
troca sem alterar codigo, caso a Groq deprecie algum modelo.
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
