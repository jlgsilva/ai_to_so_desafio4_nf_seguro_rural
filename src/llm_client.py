"""
Cliente de LLM via Groq (modelos gratuitos / production tier).

============================================================
COMO TROCAR O MODELO (leia isto primeiro)
============================================================
As DUAS linhas abaixo (MODEL_RACIOCINIO e MODEL_RAPIDO) sao o
UNICO lugar do codigo que precisa ser editado para trocar de
modelo LLM. Nenhum outro arquivo faz referencia ao nome de um
modelo. Se a Groq depreciar um destes modelos de novo (ela avisa
por e-mail com ~2 meses de antecedencia e a lista atual sempre
fica em https://console.groq.com/docs/models), basta:

  1. Abrir a lista de modelos suportados em
     https://console.groq.com/docs/models e escolher o substituto
     (a Groq costuma indicar um "Recommended Replacement Model ID"
     na propria pagina/e-mail de deprecacao).
  2. Editar o valor da string abaixo (MODEL_RACIOCINIO e/ou
     MODEL_RAPIDO) neste arquivo, direto pelo GitHub.
  3. Commitar. O Streamlit Cloud faz redeploy automatico e a troca
     ja vale para todos os usuarios.

Alternativamente, sem tocar no codigo: defina as variaveis de
ambiente GROQ_MODEL_RACIOCINIO e GROQ_MODEL_RAPIDO (em `.env`
local ou em Secrets do Streamlit Cloud). Elas tem prioridade sobre
os valores abaixo - uteis para testar um modelo novo sem alterar o
repositorio.
============================================================

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

--------------------------------------------------------------
Atualizacao de 17/08/2026: llama-3.3-70b-versatile e
llama-3.1-8b-instant foram DEPRECIADOS pela Groq em 16/08/2026.
Os defaults abaixo foram trocados pelos modelos que a propria Groq
recomendou como substitutos (email de deprecacao, 17/06/2026):

  llama-3.1-8b-instant    -> openai/gpt-oss-20b   (MODEL_RAPIDO)
  llama-3.3-70b-versatile -> openai/gpt-oss-120b  (MODEL_RACIOCINIO)
    (a Groq tambem indicou qwen/qwen3.6-27b como alternativa para o
    raciocinio; gpt-oss-120b foi escolhido por ja ter numero de TPM
    conhecido e testado nesta aplicacao - ver tests/test_pipeline_
    deterministico.py - enquanto os limites de conta gratuita do
    qwen3.6-27b ainda nao estao documentados publicamente)

Tabela de referencia (conta gratuita; SEMPRE confirme os valores
atuais em https://console.groq.com/settings/limits, pois a Groq
altera esses numeros pela UI sem aviso - so a lista de MODELOS
deprecados costuma vir por e-mail):

  modelo                     RPM   RPD     TPM     TPD
  openai/gpt-oss-120b         30   1.000    8.000  200.000
  openai/gpt-oss-20b          30   1.000    8.000  200.000
  qwen/qwen3.6-27b            30   1.000        ?        ?

Atencao a uma mudanca de comportamento nesta migracao: o modelo
"rapido" antigo (llama-3.1-8b-instant) tinha RPD de 14.400 (chamadas
por dia), bem folgado. O substituto oficial (openai/gpt-oss-20b) tem
RPD de apenas 1.000 - o mesmo teto do modelo de raciocinio. Como o
MODEL_RAPIDO e chamado a cada pergunta (classificacao + redacao da
resposta final), o limite DIARIO DE REQUISICOES agora se esgota bem
mais rapido em uso intenso de testes do que esgotava antes. Se isso
virar um problema no dia a dia, o cache de perguntas repetidas (ja
implementado, ver app.py) ajuda a nao gastar cota de novo em
perguntas identicas.
--------------------------------------------------------------

Os nomes de modelo sao lidos de variavel de ambiente para facilitar
troca sem alterar codigo, caso a Groq altere os limites, deprecie
algum modelo, ou caso o usuario prefira outro equilibrio entre
qualidade e cota disponivel.
"""

from __future__ import annotations

import os
from langchain_groq import ChatGroq

# >>> EDITE AQUI para trocar de modelo (ver instrucoes no topo deste
# arquivo). Os valores abaixo sao usados sempre que as variaveis de
# ambiente GROQ_MODEL_RACIOCINIO / GROQ_MODEL_RAPIDO nao estiverem
# definidas.
MODEL_RACIOCINIO = os.getenv("GROQ_MODEL_RACIOCINIO", "openai/gpt-oss-120b")
MODEL_RAPIDO = os.getenv("GROQ_MODEL_RAPIDO", "openai/gpt-oss-20b")


def get_llm(fast: bool = False, temperature: float = 0.0):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY nao encontrada. Configure em .env (local) ou em "
            "Secrets do Streamlit Cloud."
        )
    model = MODEL_RAPIDO if fast else MODEL_RACIOCINIO
    return ChatGroq(model=model, temperature=temperature, api_key=api_key)
