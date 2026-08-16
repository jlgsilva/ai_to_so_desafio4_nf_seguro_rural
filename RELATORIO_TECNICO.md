# Relatorio Tecnico - Desafio 4
## Interface Inteligente para Consulta de Arquivos CSV

**Curso:** InsurMinds (I2A2)
**Grupo:** ai_to_so
**Data de entrega:** [preencher data]

---

## 1. Objetivo

Este relatorio descreve o desenvolvimento da solucao do Desafio 4, cujo objetivo e
construir um agente inteligente capaz de responder perguntas em linguagem natural
sobre arquivos CSV enviados pelo usuario.

A aplicacao foi construida e validada a partir dos arquivos de Nota Fiscal
Eletronica (NFe) fornecidos como exemplo pelo curso, mas foi desenhada desde o
inicio para funcionar como ferramenta de analise do **SISSER (Sistema de
Subvencao Economica ao Premio do Seguro Rural)**, base de dados publica mantida
pelo Ministerio da Agricultura, Pecuaria e Abastecimento. Essa escolha reflete o
contexto do curso (InsurMinds, aplicado ao mercado de seguros) e demonstra que a
arquitetura de agentes construida nao depende de um formato fixo de entrada.

Os arquivos de NFe serviram como primeiro caso de teste por serem mais simples
(dois arquivos relacionados por uma chave, poucas colunas). O SISSER foi usado
como caso de teste principal por ser mais complexo (arquivo unico com 38
colunas, tres periodos historicos com pequenas variacoes de encoding, valores
faltantes representados de formas diferentes) e por ser o dominio de negocio
real que a ferramenta deve atender.

## 2. Framework escolhido

O framework de agentes utilizado foi o **LangChain**, um dos frameworks
aceitos pelo enunciado do desafio. O LangChain foi usado para estruturar cada
agente como uma cadeia (prompt template mais chamada de modelo), permitindo
compor as quatro etapas do pipeline (perfilamento, planejamento, execucao e
apresentacao) de forma modular e testavel.

O modelo de linguagem usado pelos agentes e fornecido pela **Groq**, atraves
da biblioteca `langchain-groq`, com dois modelos gratuitos (production tier):

- `llama-3.3-70b-versatile`: usado nas etapas que exigem raciocinio mais
  apurado (planejamento da consulta e geracao de SQL).
- `llama-3.1-8b-instant`: usado nas etapas mais simples e de menor custo
  (resumo do dataset e redacao da resposta final).

## 3. Arquitetura da solucao

A solucao segue um pipeline de quatro agentes especializados, cada um com uma
responsabilidade unica. Os agentes nao trabalham sobre o arquivo bruto
completo: um perfil resumido dos dados (schema, tipos, estatisticas, amostra)
e o que circula entre as etapas, o que mantem o consumo de tokens sob controle
mesmo em contas gratuitas com limites de taxa restritivos.

```
Upload do arquivo .zip
        |
        v
Agente 1: Perfilador de Dados (Data Profiler)
        |
        v
Agente 2: Planejador de Estrategia (Strategy Planner)
        |
        v
Agente 3: Executor de Consulta (Executor)
        |
        v
Agente 4: Apresentador (Presenter)
        |
        v
Resposta em texto, tabela ou grafico
```

Antes do primeiro agente, uma camada de ingestao (sem uso de IA) faz a leitura
do arquivo: deteccao automatica de encoding, delimitador de campo e separador
decimal, alem da normalizacao de todos os arquivos para UTF-8. Essa etapa foi
necessaria porque os proprios arquivos de exemplo fornecidos ja vieram em
formatos diferentes entre si (a NFe em UTF-8 com virgula como separador de
campo, o SISSER em CP1252 com ponto e virgula como separador de campo e
virgula como separador decimal), confirmando que a solucao nao poderia assumir
um formato fixo.

Depois da execucao da consulta, os resultados (sempre um recorte pequeno de
dados, nunca a base inteira) sao armazenados em um historico persistente em
SQLite, junto com o plano gerado, o SQL executado e o tempo de resposta, para
fins de auditoria.

## 4. Descricao dos agentes desenvolvidos

### Agente 1: Perfilador de Dados (Data Profiler)

Responsavel por entender do que se trata o arquivo enviado antes de qualquer
outra decisao. Parte do trabalho e deterministica (sem IA): deteccao de
schema, tipos de coluna, percentual de valores nulos, cardinalidade e
identificacao de relacionamento entre arquivos (por exemplo, a coluna que liga
cabecalho e itens de uma NFe). A parte que usa IA e a redacao de um resumo em
linguagem natural do que foi encontrado, e, quando o arquivo nao corresponde a
nenhum formato conhecido pela aplicacao, uma classificacao do provavel dominio
de negocio a partir dos nomes de coluna.

Esse agente tambem reconhece automaticamente quando o arquivo enviado
corresponde ao padrao do SISSER ou da NFe, casos em que aplica um glossario de
negocio especifico (por exemplo, a formula de sinistralidade no caso do
SISSER) usado depois pelos demais agentes.

### Agente 2: Planejador de Estrategia (Strategy Planner)

Recebe a pergunta do usuario e o perfil dos dados, e decide a estrategia de
resposta antes de qualquer calculo. A decisao e sempre estruturada em um
formato fixo (JSON), nunca em texto livre: quais arquivos sao necessarios, se
e preciso juncao entre eles, que tipo de operacao a pergunta exige (agregacao,
ranking, serie temporal, comparacao), se a pergunta usa algum termo do
glossario de negocio, e qual tipo de visualizacao e mais adequado para a
resposta. Esse agente nunca calcula o resultado, apenas planeja como
calcula-lo.

### Agente 3: Executor de Consulta (Executor)

Traduz o plano do agente anterior em uma consulta SQL real, no dialeto do
DuckDB, e executa essa consulta contra os dados. O numero final que aparece na
resposta sempre vem da execucao real dessa consulta, nunca de um valor gerado
pela IA. Se a consulta falhar (erro de sintaxe, nome de coluna incorreto),
o erro e devolvido ao modelo, que tenta corrigir o SQL, em ate tres tentativas.

Esse agente tambem e responsavel por lidar com arquivos grandes: as consultas
rodam diretamente contra o arquivo em disco atraves do DuckDB, sem carregar o
arquivo inteiro em memoria, o que permite consultar arquivos de centenas de
megabytes sem esgotar os recursos disponiveis.

### Agente 4: Apresentador (Presenter)

Recebe o resultado ja calculado pelo Executor (uma tabela pequena, geralmente
com poucas linhas) e escreve a resposta final em linguagem natural, citando os
numeros exatos que estao na tabela. Tambem decide o formato de visualizacao
mais adequado (texto simples, tabela, grafico de barras, linha ou pizza), com
base na sugestao do Planejador e no formato dos dados retornados.

## 5. Fluxo de funcionamento da aplicacao

A aplicacao e organizada em cinco telas dentro do Streamlit:

1. **Carga de dados**: o usuario envia um arquivo .zip contendo um ou mais
   CSV. A aplicacao processa o arquivo automaticamente (deteccao de formato,
   perfilamento) e mostra um resumo do que foi encontrado.

2. **Visao geral**: um painel automatico, gerado sem uso de IA, com
   indicadores principais, grafico de distribuicao por categoria e grafico de
   valor por categoria (as colunas usadas nesses dois graficos podem ser
   trocadas livremente pelo usuario para qualquer outra coluna do arquivo),
   serie temporal quando ha coluna de data, mapa de dispersao quando ha
   coordenadas geograficas, mapa por UF e mapa por municipio (cada um
   aparece apenas quando o arquivo contem, respectivamente, uma coluna de
   sigla de estado ou uma coluna de codigo IBGE de municipio), alem de um
   raio-x de qualidade de dados (percentual de valores nulos por coluna).
   Ha tambem um filtro dedicado por UF: ao selecionar um estado, o mapa por
   municipio passa a mostrar apenas os municipios daquele estado, com zoom
   automatico. Essa tela existe para que o usuario entenda os dados antes
   mesmo de perguntar qualquer coisa, e para orientar que tipo de pergunta
   faz sentido fazer.

3. **Perguntas**: interface de chat. Antes da primeira pergunta, a aplicacao
   sugere perguntas relevantes com base no tipo de dado identificado (por
   exemplo, perguntas sobre subvencao e sinistralidade quando reconhece dados
   do SISSER). O usuario tambem pode digitar qualquer pergunta livre.

4. **Historico**: lista de arquivos processados e perguntas feitas em sessoes
   anteriores, junto com o log tecnico completo da aplicacao (util para
   diagnostico).

5. **Sobre / Arquitetura**: documentacao tecnica completa da solucao.

[PRINT 1: capturar a tela inicial da aba "Carga de dados", com um arquivo do
SISSER ja carregado e o resumo gerado pelo agente visivel]

[PRINT 2: capturar a aba "Visao geral" mostrando os indicadores, o grafico de
distribuicao por UF e o mapa de dispersao por coordenadas]

[PRINT 2b: capturar o mapa por UF e o mapa por municipio lado a lado, e em
seguida capturar a mesma tela apos aplicar o filtro de UF (ex.: selecionar
"GO"), mostrando o mapa por municipio focado apenas nos municipios daquele
estado]

## 6. Perguntas realizadas e respostas obtidas

As perguntas abaixo foram testadas com os dados do SISSER (arquivos historicos
de apolices do Programa de Subvencao ao Premio do Seguro Rural).

### Pergunta 1

**Pergunta:** Qual o total de subvencao federal pago por UF?

**Resposta:** [colar aqui o texto de resposta gerado pela aplicacao]

[PRINT 3: capturar a pergunta e a resposta completa na aba "Perguntas",
incluindo o grafico gerado]

### Pergunta 2

**Pergunta:** Qual a taxa de sinistralidade (indenizacao dividida por premio)
por cultura?

**Resposta:** [colar aqui o texto de resposta gerado pela aplicacao]

[PRINT 4: capturar a pergunta e a resposta, e tambem abrir o expander
"Detalhes tecnicos" para mostrar o SQL gerado pelo agente Executor]

### Pergunta 3

**Pergunta:** Quais as cinco seguradoras com maior valor de premio liquido?

**Resposta:** [colar aqui o texto de resposta gerado pela aplicacao]

[PRINT 5: capturar a pergunta e a resposta em formato de tabela ou grafico
de barras]

### Pergunta 4

**Pergunta:** Qual foi a evolucao do numero de apolices por ano?

**Resposta:** [colar aqui o texto de resposta gerado pela aplicacao]

[PRINT 6: capturar a pergunta e o grafico de linha gerado como resposta]

### Pergunta 5 (NFe, arquivo de exemplo do curso)

**Pergunta:** Qual o valor total de notas fiscais emitidas por UF?

**Resposta:** [colar aqui o texto de resposta gerado pela aplicacao]

[PRINT 7: capturar a pergunta rodando sobre o arquivo de exemplo de NFe, para
demonstrar que a mesma aplicacao funciona nos dois dominios]

### Pergunta 6 (NFe, arquivo de exemplo do curso)

**Pergunta:** Quais os cinco produtos com maior valor total vendido?

**Resposta:** [colar aqui o texto de resposta gerado pela aplicacao]

[PRINT 8: capturar a pergunta e a resposta]

## 7. Fontes de dados utilizadas

**SISSER (dado principal, foco da ferramenta):**
Sistema de Subvencao Economica ao Premio do Seguro Rural, mantido pela
Coordenacao-Geral de Seguro Rural do Ministerio da Agricultura, Pecuaria e
Abastecimento. Disponivel em
https://dados.agricultura.gov.br/dataset/sisser3, contendo apolices
recepcionadas pelo PSR (Programa de Subvencao ao Premio do Seguro Rural),
divididas em tres periodos historicos (2006 a 2015, 2016 a 2024 e 2025). O
dicionario de dados oficial foi consultado para a construcao do glossario de
negocio usado pelos agentes.

**NFe (dado de exemplo, fornecido pelo curso):**
Dois conjuntos de arquivos de Nota Fiscal Eletronica fornecidos como material
de apoio do Desafio 4, cada um dividido em cabecalho e itens, relacionados
pela coluna Chave de Acesso.

Ambos os conjuntos de dados foram usados apenas como amostras reduzidas para
desenvolvimento e teste, mantendo a estrutura e as inconsistencias reais dos
arquivos originais (encoding, delimitador, formato de data e de numero
decimal).

## 8. Tecnologias utilizadas

- **Python** como linguagem principal.
- **Streamlit** para a interface web.
- **LangChain** e **langchain-groq** para a orquestracao dos agentes.
- **Groq** como provedor de LLM (modelos gratuitos `llama-3.3-70b-versatile`
  e `llama-3.1-8b-instant`).
- **DuckDB** como motor de consulta sobre os arquivos CSV, permitindo
  trabalhar com arquivos grandes sem carrega-los inteiramente em memoria.
- **pandas** para perfilamento e manipulacao de amostras de dados.
- **Plotly** para os graficos interativos, o mapa de dispersao geografica e
  os mapas coropleticos por UF e por municipio.
- **SQLite** para o historico persistente de datasets processados e
  perguntas realizadas.
- **GitHub** para hospedagem do codigo-fonte e da documentacao.
- **Streamlit Community Cloud** para publicacao da aplicacao online.

## 9. Uso de IA no desenvolvimento

E importante separar dois usos distintos de inteligencia artificial neste
projeto.

O primeiro e o uso de IA **dentro da aplicacao em producao**: os quatro
agentes descritos nas secoes 3 e 4, que rodam sobre a API da Groq e sao
responsaveis por interpretar as perguntas do usuario e gerar as respostas. E
esse uso que atende ao requisito do desafio.

O segundo e o uso de IA **como ferramenta de apoio ao desenvolvimento**: o
codigo desta aplicacao foi construido com o auxilio do Claude (Anthropic),
usado como assistente de programacao ao longo do processo. O Claude ajudou na
definicao da arquitetura de agentes, na escrita do codigo Python, na
identificacao e correcao de erros encontrados durante os testes com os dados
reais (por exemplo, problemas de encoding especificos dos arquivos do SISSER e
um erro de formatacao de prompt que quebrava o agente de planejamento), e na
redacao desta documentacao. Esse uso e equivalente ao de qualquer outra
ferramenta de apoio ao desenvolvimento de software e nao substitui, em nenhum
momento, o funcionamento dos agentes em tempo de execucao: nenhuma pergunta
feita pelo usuario dentro da aplicacao e respondida pelo Claude, apenas pelos
agentes construidos com LangChain e Groq, conforme exigido pelo enunciado do
desafio.

## 10. Limitacoes conhecidas e possibilidades de evolucao

- O historico armazenado em SQLite nao e permanente quando a aplicacao roda
  no Streamlit Community Cloud, ja que o armazenamento em disco da plataforma
  gratuita nao persiste entre reinicializacoes do servico.
- Contas gratuitas da Groq tem limite de tokens por minuto relativamente
  baixo, o que exigiu compactar bastante o volume de informacao enviado nos
  prompts. Perguntas muito complexas, ou o uso simultaneo por varios usuarios,
  podem esbarrar nesse limite.
- A deteccao automatica de colunas relevantes (dimensao, valor, data,
  coordenadas, UF, municipio) usada na Visao Geral e nas sugestoes de
  pergunta e baseada em heuristicas de nome, tipo e valor de coluna (por
  exemplo, uma coluna so e considerada candidata a mapa por UF quando os
  valores nela observados sao, de fato, siglas validas de estado
  brasileiro, e o mapa por municipio depende de uma coluna de codigo IBGE
  de 7 digitos, nao apenas do nome do municipio). Funciona bem para os
  formatos testados, mas pode nao identificar corretamente colunas de
  datasets com nomenclatura muito diferente.
- O mapa geografico cobre visualizacao por coordenadas (latitude/longitude),
  por UF e por municipio, com os contornos correspondentes incluidos no
  repositorio (`assets/br_uf.geojson` e `assets/br_municipios.geojson`, este
  ultimo com cerca de 8,5 MB apos simplificacao). O mapa por municipio so
  aparece quando o arquivo tem uma coluna de codigo IBGE; uma coluna apenas
  com o nome do municipio nao e suficiente, pois nomes de cidade se repetem
  entre estados diferentes e um casamento so por nome poderia gerar um mapa
  incorreto.
- Durante os testes com os tres arquivos completos do SISSER (juntos,
  ultrapassam 400 MB), foram identificados e corrigidos dois problemas: as
  consultas de serie temporal e mapa geografico geravam SQL invalido quando
  um filtro estava ativo (duas clausulas WHERE em sequencia), e o botao de
  atualizacao da tela apos responder uma pergunta reprocessava o arquivo
  inteiro de novo, apagando a resposta que acabara de ser calculada. Ambas
  as correcoes estao cobertas por testes automatizados que reproduzem os
  cenarios exatos em que os problemas ocorriam.
- Evolucoes futuras possiveis incluem: suporte a mais de um arquivo na Visao
  Geral simultaneamente (hoje a analise e feita por arquivo), cache de
  respostas para perguntas repetidas, casamento de municipio por nome+UF
  quando nao houver codigo IBGE disponivel, e um mecanismo de autenticacao
  para uso compartilhado do historico entre membros do grupo.

## 11. Repositorio e licenca

Codigo-fonte disponivel em: [preencher link do repositorio GitHub]

O projeto e distribuido sob licenca MIT, conforme arquivo LICENSE no
repositorio.
