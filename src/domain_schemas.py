"""
Catalogo de familias de schema conhecidas.

Cada familia guarda:
- colunas esperadas (usadas para calcular um score de similaridade contra
  o cabecalho do arquivo recebido)
- coluna(s) chave, usadas para detectar relacionamento entre arquivos
  (ex.: cabecalho + itens de NFe)
- glossario de negocio, injetado no prompt dos agentes para que a LLM
  entenda o significado de siglas e possa sugerir metricas relevantes
  (ex.: sinistralidade no SISSER)

Isso NAO restringe o app a esses formatos. Um arquivo com colunas
totalmente diferentes cai em "GENERICO" e o pipeline funciona do mesmo
jeito, apenas sem o glossario de dominio.
"""

from __future__ import annotations

SISSER = {
    "id": "SISSER",
    "nome": "SISSER - Subvencao ao Premio do Seguro Rural (MAPA)",
    "colunas_esperadas": [
        "NM_RAZAO_SOCIAL", "CD_PROCESSO_SUSEP", "NR_PROPOSTA", "ID_PROPOSTA",
        "DT_PROPOSTA", "DT_INICIO_VIGENCIA", "DT_FIM_VIGENCIA", "NM_SEGURADO",
        "NR_DOCUMENTO_SEGURADO", "NM_MUNICIPIO_PROPRIEDADE", "SG_UF_PROPRIEDADE",
        "NM_CLASSIF_PRODUTO", "NM_CULTURA_GLOBAL", "NR_AREA_TOTAL", "NR_ANIMAL",
        "NR_PRODUTIVIDADE_ESTIMADA", "NR_PRODUTIVIDADE_SEGURADA",
        "NivelDeCobertura", "VL_LIMITE_GARANTIA", "VL_PREMIO_LIQUIDO",
        "PE_TAXA", "VL_SUBVENCAO_FEDERAL", "NR_APOLICE", "DT_APOLICE",
        "ANO_APOLICE", "CD_GEOCMU", "VALOR_INDENIZAÇÃO", "EVENTO_PREPONDERANTE",
    ],
    "chave_primaria": ["NR_APOLICE", "ID_PROPOSTA"],
    "colunas_data": ["DT_PROPOSTA", "DT_INICIO_VIGENCIA", "DT_FIM_VIGENCIA", "DT_APOLICE"],
    "colunas_numericas_decimal_virgula": [
        "NR_AREA_TOTAL", "NR_ANIMAL", "NR_PRODUTIVIDADE_ESTIMADA",
        "NR_PRODUTIVIDADE_SEGURADA", "VL_LIMITE_GARANTIA", "VL_PREMIO_LIQUIDO",
        "PE_TAXA", "VL_SUBVENCAO_FEDERAL", "VALOR_INDENIZAÇÃO",
    ],
    "marcadores_nulo": ["-", "", "NA", "N/A"],
    "glossario": {
        "NM_RAZAO_SOCIAL": "Seguradora responsavel pela apolice",
        "NR_PROPOSTA": "Numero da proposta na seguradora",
        "DT_PROPOSTA": "Data em que a proposta foi contratada",
        "NM_SEGURADO": "Nome do produtor rural segurado",
        "NR_DOCUMENTO_SEGURADO": "CPF ou CNPJ do segurado (parcialmente mascarado)",
        "NM_MUNICIPIO_PROPRIEDADE": "Municipio onde fica a propriedade rural",
        "SG_UF_PROPRIEDADE": "UF da propriedade",
        "NM_CLASSIF_PRODUTO": "Tipo de seguro (ex.: CUSTEIO, PRODUTIVIDADE)",
        "NM_CULTURA_GLOBAL": "Cultura ou atividade segurada (ex.: Milho, Soja)",
        "NR_AREA_TOTAL": "Area total segurada, em hectares",
        "VL_LIMITE_GARANTIA": "Valor total segurado (Importancia Segurada)",
        "VL_PREMIO_LIQUIDO": "Valor do premio pago pelo produtor/seguradora",
        "PE_TAXA": "Taxa de premio (percentual sobre o valor segurado)",
        "VL_SUBVENCAO_FEDERAL": "Valor pago pelo governo federal como subvencao ao premio",
        "NR_APOLICE": "Numero da apolice emitida",
        "ANO_APOLICE": "Ano de contratacao da apolice",
        "VALOR_INDENIZAÇÃO": "Valor pago em caso de sinistro (indenizacao)",
        "EVENTO_PREPONDERANTE": "Causa principal do sinistro (ex.: seca, granizo, geada)",
        "_metricas_derivadas": {
            "taxa_sinistralidade": "VALOR_INDENIZAÇÃO / VL_PREMIO_LIQUIDO (quando premio > 0)",
            "indice_subvencao": "VL_SUBVENCAO_FEDERAL / VL_PREMIO_LIQUIDO",
            "ticket_medio_apolice": "VL_LIMITE_GARANTIA medio por apolice",
        },
    },
}

NFE_CABECALHO = {
    "id": "NFE_CABECALHO",
    "nome": "Nota Fiscal Eletronica - Cabecalho",
    "colunas_esperadas": [
        "CHAVE DE ACESSO", "MODELO", "SÉRIE", "NÚMERO", "NATUREZA DA OPERAÇÃO",
        "DATA EMISSÃO", "CPF/CNPJ Emitente", "RAZÃO SOCIAL EMITENTE",
        "UF EMITENTE", "MUNICÍPIO EMITENTE", "CNPJ DESTINATÁRIO",
        "NOME DESTINATÁRIO", "UF DESTINATÁRIO", "VALOR NOTA FISCAL",
    ],
    "chave_primaria": ["CHAVE DE ACESSO"],
    "colunas_data": ["DATA EMISSÃO", "DATA/HORA EVENTO MAIS RECENTE"],
    "colunas_numericas_decimal_virgula": ["VALOR NOTA FISCAL"],
    "marcadores_nulo": ["", "NA"],
    "glossario": {
        "CHAVE DE ACESSO": "Identificador unico da nota fiscal (chave para juncao com itens)",
        "RAZÃO SOCIAL EMITENTE": "Empresa que emitiu a nota fiscal",
        "NOME DESTINATÁRIO": "Empresa ou pessoa que recebeu a nota fiscal",
        "VALOR NOTA FISCAL": "Valor total da nota fiscal",
        "UF EMITENTE": "Estado do emitente",
        "UF DESTINATÁRIO": "Estado do destinatario",
    },
}

NFE_ITENS = {
    "id": "NFE_ITENS",
    "nome": "Nota Fiscal Eletronica - Itens",
    "colunas_esperadas": [
        "CHAVE DE ACESSO", "NÚMERO PRODUTO", "DESCRIÇÃO DO PRODUTO/SERVIÇO",
        "CÓDIGO NCM/SH", "NCM/SH (TIPO DE PRODUTO)", "CFOP", "QUANTIDADE",
        "UNIDADE", "VALOR UNITÁRIO", "VALOR TOTAL",
    ],
    "chave_primaria": ["CHAVE DE ACESSO", "NÚMERO PRODUTO"],
    "colunas_data": ["DATA EMISSÃO"],
    "colunas_numericas_decimal_virgula": ["QUANTIDADE", "VALOR UNITÁRIO", "VALOR TOTAL"],
    "marcadores_nulo": ["", "NA"],
    "glossario": {
        "CHAVE DE ACESSO": "Identificador unico da nota fiscal (chave para juncao com cabecalho)",
        "DESCRIÇÃO DO PRODUTO/SERVIÇO": "Descricao do item vendido",
        "VALOR TOTAL": "Valor total do item (quantidade x valor unitario)",
        "CFOP": "Codigo Fiscal de Operacoes e Prestacoes",
    },
}

KNOWN_SCHEMAS = [SISSER, NFE_CABECALHO, NFE_ITENS]


def _normalize(col: str) -> str:
    return col.strip().upper().replace("Ç", "C").replace("Ã", "A").replace("É", "E")


def match_schema(columns: list[str], min_score: float = 0.55) -> dict | None:
    """Retorna a familia de schema conhecida mais proxima das colunas
    recebidas, ou None se nenhuma bater um score minimo de sobreposicao."""
    cols_norm = {_normalize(c) for c in columns}
    best, best_score = None, 0.0
    for schema in KNOWN_SCHEMAS:
        expected = {_normalize(c) for c in schema["colunas_esperadas"]}
        if not expected:
            continue
        overlap = len(cols_norm & expected) / len(expected)
        if overlap > best_score:
            best, best_score = schema, overlap
    if best and best_score >= min_score:
        return best
    return None
