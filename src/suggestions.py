"""
Sugestao de perguntas.

Gera exemplos de perguntas relevantes para os dados carregados, sem
usar LLM (rapido, sem custo, sem risco de limite de tokens). Para os
dominios conhecidos (SISSER, NFe), usa uma lista curada com base no
glossario de negocio. Para dados nao reconhecidos, monta perguntas por
combinacao das colunas de dimensao/valor/data detectadas em
src.overview, o que garante que o recurso funcione com qualquer CSV,
nao apenas os formatos usados no desenvolvimento.
"""

from __future__ import annotations

from src.overview import choose_semantic_columns

_SISSER_PERGUNTAS = [
    "Qual o total de subvencao federal pago por UF?",
    "Qual a taxa de sinistralidade (indenizacao dividida por premio) por cultura?",
    "Quais as cinco seguradoras com maior valor de premio liquido?",
    "Qual foi a evolucao do numero de apolices por ano?",
    "Qual UF teve a maior area total segurada?",
    "Quais os cinco municipios com maior valor de indenizacao?",
]

_NFE_PERGUNTAS = [
    "Qual o valor total de notas fiscais emitidas por UF?",
    "Quais os cinco produtos com maior valor total vendido?",
    "Qual emitente teve o maior faturamento no periodo?",
    "Qual o valor medio das notas fiscais?",
    "Quais os cinco destinatarios que mais compraram?",
]


def _heuristic_questions(file_profile: dict) -> list[str]:
    semantic = choose_semantic_columns(file_profile)
    dim = semantic.get("coluna_dimensao")
    valor = semantic.get("coluna_valor")
    data = semantic.get("coluna_data")

    perguntas = []
    if dim and valor:
        perguntas.append(f"Qual o total de {valor} por {dim}?")
        perguntas.append(f"Quais os cinco maiores valores de {valor} agrupados por {dim}?")
    if dim:
        perguntas.append(f"Quais os valores mais frequentes de {dim}?")
    if valor:
        perguntas.append(f"Qual a media, o minimo e o maximo de {valor}?")
    if data and valor:
        perguntas.append(f"Qual foi a evolucao de {valor} ao longo dos anos?")
    elif data:
        perguntas.append("Quantos registros existem por ano?")
    if not perguntas:
        perguntas.append("Quantas linhas e colunas tem este arquivo?")
    return perguntas


def suggest_questions(dataset_profile: dict, max_perguntas: int = 6) -> list[str]:
    familias = {fp["familia_reconhecida"] for fp in dataset_profile["arquivos"]}

    if "SISSER" in familias:
        return _SISSER_PERGUNTAS[:max_perguntas]
    if familias & {"NFE_CABECALHO", "NFE_ITENS"}:
        return _NFE_PERGUNTAS[:max_perguntas]

    perguntas: list[str] = []
    for fp in dataset_profile["arquivos"]:
        perguntas.extend(_heuristic_questions(fp))
    # remove duplicatas preservando ordem
    vistas = set()
    unicas = []
    for p in perguntas:
        if p not in vistas:
            vistas.add(p)
            unicas.append(p)
    return unicas[:max_perguntas]
