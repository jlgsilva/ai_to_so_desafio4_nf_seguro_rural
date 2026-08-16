"""
Agente 2 - Strategy Planner.

Recebe o Data Profile (ja enriquecido pelo Profiler) e a pergunta do
usuario. Devolve um PLANO estruturado (JSON), nunca texto livre, para
que o Executor tenha algo determinístico para traduzir em codigo.

O plano nao contem numeros/resultados. Contem apenas a ESTRATEGIA:
quais arquivos usar, se precisa juncao, que tipo de operacao
(agregacao, filtro, ranking, serie temporal, comparacao), e se, dado o
tamanho dos arquivos, a resposta exige consulta no arquivo completo
(via DuckDB) em vez de trabalhar so com a amostra.
"""

from __future__ import annotations

import json
import re
from langchain_core.prompts import ChatPromptTemplate
from src.llm_client import get_llm
from src.profiling import build_llm_profile_summary
from src.logging_config import get_logger

log = get_logger("agents.planner")

_PLAN_SCHEMA_HINT = """
Responda SOMENTE com um JSON valido, sem texto antes ou depois, no formato:
{{
  "arquivos_necessarios": ["nome_do_arquivo.csv", ...],
  "precisa_juncao": true/false,
  "colunas_juncao": ["NOME_COLUNA", ...],
  "tipo_operacao": "agregacao" | "filtro" | "ranking" | "serie_temporal" | "comparacao" | "estatistica_descritiva" | "outro",
  "colunas_relevantes": ["NOME_COLUNA", ...],
  "metrica_derivada": "descricao curta se a pergunta exigir calculo derivado (ex.: sinistralidade), ou null",
  "precisa_dados_completos": true/false,
  "justificativa": "1-2 frases explicando o raciocinio",
  "sugestao_visualizacao": "tabela" | "grafico_barras" | "grafico_linha" | "grafico_pizza" | "texto"
}}
"""

_PLANNER_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Voce e um agente de planejamento de analise de dados. Voce NUNCA "
     "calcula o resultado, apenas decide a estrategia. Use o perfil dos "
     "dados (schema, familia de dominio, glossario de negocio, "
     "relacionamentos entre arquivos) para montar um plano preciso. "
     "Se a pergunta mencionar um termo do glossario de negocio (ex.: "
     "sinistralidade, subvencao, ticket medio), utilize a formula "
     "fornecida no glossario. Se algum arquivo estiver marcado como "
     "'arquivo_grande', marque precisa_dados_completos=true sempre que "
     "a pergunta pedir numero exato (total, media, contagem exata); "
     "amostra so e aceitavel para perguntas exploratorias vagas. " + _PLAN_SCHEMA_HINT),
    ("human",
     "Perfil dos dados:\n{profile_json}\n\nPergunta do usuario:\n{pergunta}"),
])


def _extract_json(text: str) -> dict:
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"A LLM nao retornou JSON valido:\n{text}")
    return json.loads(match.group(0))


def run_planner_agent(dataset_profile: dict, pergunta: str) -> dict:
    compact_profile = build_llm_profile_summary(dataset_profile)
    llm = get_llm(fast=False, temperature=0.0)
    chain = _PLANNER_PROMPT | llm
    log.info("Planejando resposta para: %s", pergunta)
    result = chain.invoke({
        "profile_json": json.dumps(compact_profile, ensure_ascii=False, default=str),
        "pergunta": pergunta,
    })
    plano = _extract_json(result.content)
    log.info("Plano gerado: %s", json.dumps(plano, ensure_ascii=False))
    return plano
