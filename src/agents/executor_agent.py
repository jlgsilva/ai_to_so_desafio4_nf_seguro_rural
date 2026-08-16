"""
Agente 3 - Executor.

Traduz o plano do Planner Agent em SQL (dialeto DuckDB) e executa
contra as views registradas em src/query_engine. O resultado numerico
SEMPRE vem da execucao real do SQL, nunca de texto gerado pela LLM.

Loop de auto-correcao: se a consulta falhar (erro de sintaxe, coluna
inexistente etc.), o erro e devolvido a LLM, que tenta corrigir, ate
MAX_TENTATIVAS vezes.
"""

from __future__ import annotations

import re
import json
from langchain_core.prompts import ChatPromptTemplate
from src.llm_client import get_llm
from src.profiling import build_llm_profile_summary
from src.query_engine import run_sql
from src.logging_config import get_logger

log = get_logger("agents.executor")

MAX_TENTATIVAS = 3

_SYSTEM = """Voce e um agente que escreve SQL no dialeto DuckDB para responder
perguntas sobre dados tabulares. Regras obrigatorias:
- Use APENAS os nomes de view fornecidos (nunca invente nomes de tabela).
- Use APENAS as colunas que aparecem no perfil fornecido.
- Gere uma unica instrucao SELECT (pode usar CTE/WITH), sem ponto e virgula no final.
- Se o plano indicar juncao entre arquivos, use JOIN pelas colunas indicadas.
- Se o plano indicar uma metrica derivada (ex.: sinistralidade), calcule-a
  explicitamente na propria consulta (ex.: SUM(a) / NULLIF(SUM(b), 0)).
- Trate divisao por zero com NULLIF no denominador.
- Datas no formato dd/mm/aaaa devem ser convertidas com
  strptime(coluna, '%d/%m/%Y') antes de comparar ou extrair ano/mes.
- Nunca use SELECT * em tabelas grandes sem LIMIT ou agregacao.
- Responda APENAS com o SQL, sem explicacoes, sem markdown, sem crases.
"""

_GENERATE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM),
    ("human",
     "Views disponiveis (nome_arquivo -> nome_view): {view_names}\n\n"
     "Perfil dos dados:\n{profile_json}\n\n"
     "Plano de analise:\n{plan_json}\n\n"
     "Pergunta original do usuario:\n{pergunta}\n\n"
     "Escreva o SQL."),
])

_FIX_PROMPT = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM),
    ("human",
     "O SQL abaixo falhou. Corrija-o mantendo a mesma intencao.\n\n"
     "SQL com erro:\n{sql}\n\n"
     "Mensagem de erro:\n{erro}\n\n"
     "Views disponiveis: {view_names}\n"
     "Perfil dos dados:\n{profile_json}\n\n"
     "Responda apenas com o SQL corrigido."),
])


def _clean_sql(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```sql", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"^```", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


def run_executor_agent(con, view_names: dict, dataset_profile: dict, plan: dict, pergunta: str) -> dict:
    llm = get_llm(fast=False, temperature=0.0)
    gen_chain = _GENERATE_PROMPT | llm
    fix_chain = _FIX_PROMPT | llm

    compact_profile = build_llm_profile_summary(dataset_profile)
    profile_json = json.dumps(compact_profile, ensure_ascii=False, default=str)
    plan_json = json.dumps(plan, ensure_ascii=False, default=str)
    views_str = json.dumps(view_names, ensure_ascii=False)

    log.info("Gerando SQL para: %s", pergunta)
    sql = _clean_sql(gen_chain.invoke({
        "view_names": views_str,
        "profile_json": profile_json,
        "plan_json": plan_json,
        "pergunta": pergunta,
    }).content)
    log.info("SQL gerado (tentativa 1): %s", sql)

    last_error = None
    for attempt in range(1, MAX_TENTATIVAS + 1):
        try:
            df_result = run_sql(con, sql)
            log.info("SQL executado com sucesso na tentativa %d (%d linhas retornadas)", attempt, len(df_result))
            return {
                "sucesso": True,
                "sql_final": sql,
                "tentativas": attempt,
                "resultado": df_result,
                "erro": None,
            }
        except Exception as exc:
            last_error = str(exc)
            log.warning("Falha na tentativa %d de execucao do SQL: %s", attempt, last_error)
            if attempt == MAX_TENTATIVAS:
                break
            sql = _clean_sql(fix_chain.invoke({
                "sql": sql,
                "erro": last_error,
                "view_names": views_str,
                "profile_json": profile_json,
            }).content)
            log.info("SQL corrigido (tentativa %d): %s", attempt + 1, sql)

    log.error("Todas as %d tentativas falharam. Ultimo erro: %s", MAX_TENTATIVAS, last_error)
    return {
        "sucesso": False,
        "sql_final": sql,
        "tentativas": MAX_TENTATIVAS,
        "resultado": None,
        "erro": last_error,
    }
