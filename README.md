# InsurMinds - Desafio 4: Interface Inteligente para Consulta de Arquivos CSV

Aplicação desenvolvida para o Desafio 4 do curso InsurMinds (I2A2). Permite enviar
arquivos CSV compactados em .zip e fazer perguntas em linguagem natural sobre os
dados, respondidas por um pipeline de agentes de IA que planeja a análise, gera e
executa a consulta, e apresenta o resultado em texto, tabela ou gráfico.

A ferramenta foi desenvolvida e testada com dois exemplos de dados fornecidos no
curso (Notas Fiscais Eletrônicas - NFe) e foi direcionada, como estudo de caso
principal, para análise de dados do **SISSER - Sistema de Subvenção Econômica ao
Prêmio do Seguro Rural**, mantido pelo Ministério da Agricultura, Pecuária e
Abastecimento. A ferramenta não fica restrita a esses dois formatos: qualquer CSV
tabular pode ser enviado, pois o primeiro agente do pipeline identifica
automaticamente o schema e o domínio dos dados antes de decidir a estratégia de
análise.

Aplicação publicada em: https://agrochat-seguro-rural.streamlit.app/

## Sumário

- [O que o desafio exige](#o-que-o-desafio-exige)
- [Arquitetura da solução](#arquitetura-da-solução)
- [Por que agentes, e não um script fixo](#por-que-agentes-e-não-um-script-fixo)
- [Interface e navegação](#interface-e-navegação)
- [Correções de bugs relevantes](#correções-de-bugs-relevantes)
- [Estrutura do repositório](#estrutura-do-repositório)
- [Como rodar localmente (Windows)](#como-rodar-localmente-windows)
- [Como publicar (GitHub + Streamlit Cloud)](#como-publicar-github--streamlit-cloud)
- [Formato esperado dos dados de entrada](#formato-esperado-dos-dados-de-entrada)
- [Exemplos de perguntas](#exemplos-de-perguntas)
- [Tratamento de arquivos grandes](#tratamento-de-arquivos-grandes)
- [Log da aplicação](#log-da-aplicação)
- [Limites de tokens da conta Groq](#limites-de-tokens-da-conta-groq)
- [Limitações conhecidas](#limitações-conhecidas)
- [Testes](#testes)
- [Tecnologias utilizadas](#tecnologias-utilizadas)
- [Licença](#licença)

## O que o desafio exige

O Desafio 4 pede uma aplicação com duas interfaces:

1. **Carga de dados**: upload de um arquivo .zip contendo um ou mais CSV (e,
   opcionalmente, um dicionário de dados).
2. **Consulta**: perguntas em linguagem natural, respondidas por pelo menos um
   agente inteligente, com resposta em texto, tabela, gráfico ou combinação.

É obrigatório usar pelo menos um framework de agentes apresentado no curso
(AutoGen, Pydantic AI, LangChain, LangFlow, LlamaIndex, CrewAI ou n8n) e não é
permitido responder às perguntas manualmente via ChatGPT/Claude/Gemini: a resposta
precisa sair da própria aplicação.

Esta aplicação usa **LangChain** para orquestrar os agentes e **Groq** (modelos
gratuitos) como provedor de LLM.

## Arquitetura da solução

O pipeline segue um ciclo de quatro agentes, cada um com uma responsabilidade
única:

```
Upload (.zip)
     |
     v
[1] DATA PROFILER
    - detecção determinística de encoding, delimitador e separador decimal
    - normalização de todos os arquivos para UTF-8 em disco
    - perfilamento estatístico (tipos, nulos, cardinalidade) por coluna
    - reconhecimento de família de dados conhecida (SISSER, NFe) ou
      classificação de domínio via LLM quando o formato é desconhecido
    - detecção de relacionamento entre arquivos (colunas em comum)
    - detecção heurística (sem LLM) de colunas de dimensão, valor, data
      e geolocalização, usada no painel de Visão Geral
     |
     v
[2] STRATEGY PLANNER  (LLM)
    - recebe o perfil dos dados + a pergunta do usuário
    - decide, em formato estruturado (JSON): quais arquivos usar, se
      precisa junção, que tipo de operação (agregação, ranking, série
      temporal etc.), se a pergunta exige uma métrica derivada do
      glossário de negócio (ex.: sinistralidade), e o tipo de
      visualização mais adequado
     |
     v
[3] EXECUTOR  (LLM + DuckDB)
    - traduz o plano em uma consulta SQL (dialeto DuckDB)
    - executa a consulta contra os arquivos (via DuckDB, sem carregar
      o CSV inteiro em memória)
    - se a consulta falhar, devolve o erro para a LLM e tenta
      novamente (até 3 tentativas) - o número final sempre vem da
      execução real do SQL, nunca de texto gerado pela LLM
     |
     v
[4] PRESENTER  (LLM)
    - recebe o resultado já calculado (uma tabela pequena) e escreve a
      resposta em linguagem natural, ancorada nos números reais
    - decide o tipo de gráfico (barras, linha, pizza, tabela ou texto)
     |
     v
Resposta (texto + gráfico/tabela) + registro no histórico (SQLite)
```

Cada etapa grava seu resultado (perfil, plano, SQL gerado, resposta) no histórico,
o que permite auditar exatamente como cada agente decidiu.

Além do pipeline de agentes, a aplicação tem uma camada de **Visão Geral**
totalmente determinística (sem LLM), que gera automaticamente KPIs, gráficos de
distribuição, série temporal, mapas (por UF e por município, quando aplicável) e
um raio-x de qualidade dos dados (percentual de nulos por coluna), a partir de
qualquer arquivo enviado. Essa camada existe para que o usuário tenha uma visão
útil dos dados imediatamente após o upload, mesmo antes de formular qualquer
pergunta, e para orientar quais perguntas fazer no chat. As sugestões de
perguntas exibidas na aba "Perguntas" também são geradas por essa mesma lógica
heurística (curada para SISSER e NFe, genérica por detecção de colunas para
qualquer outro formato).

### Por que agentes, e não um script fixo

Um pipeline de código fixo (ex.: `if pergunta contém "total" então soma coluna X`)
só funciona para o formato de dados específico para o qual foi escrito. Os dados
enviados durante o desenvolvimento (dois anos de NFe e três períodos do SISSER)
já mostraram schemas, encodings, delimitadores e convenções numéricas diferentes
entre si; qualquer novo dataset enviado por um usuário pode variar ainda mais.
Por isso, a arquitetura separa:

- **O que é determinístico e não deve depender de IA**: detecção de encoding,
  parsing de CSV, execução de SQL, contagem de linhas. Esses cálculos usam
  bibliotecas padrão (pandas, DuckDB), não a LLM.
- **O que exige julgamento e deve usar IA**: entender o que a pergunta do
  usuário significa, decidir qual estratégia de consulta responde a ela, e
  redigir a explicação final. Isso é delegado aos agentes.

Essa separação também é o que torna a arquitetura auditável: é possível verificar
o SQL exato que gerou cada resposta (aba "Perguntas", seção "Detalhes técnicos").

## Interface e navegação

A aplicação é organizada em cinco abas:

1. **Carga de dados**: upload do .zip, ou um dos dois exemplos embutidos
   (SISSER e NFe). Mostra o resumo gerado pelo Profiler Agent e o perfil
   detalhado de cada arquivo (schema, encoding, delimitador, relacionamentos).
2. **Visão geral**: um painel automático, gerado sem uso de IA, com
   indicadores principais, gráfico de distribuição por categoria e gráfico de
   valor por categoria (as colunas usadas nesses dois gráficos podem ser
   trocadas livremente pelo usuário para qualquer outra coluna do arquivo),
   série temporal quando há coluna de data, mapa de dispersão quando há
   coordenadas geográficas, mapa por UF e mapa por município (cada um aparece
   apenas quando o arquivo contém, respectivamente, uma coluna de sigla de
   estado ou uma coluna de código IBGE de município), e um raio-x de qualidade
   de dados (percentual de valores nulos por coluna). Há também um filtro
   dedicado por UF: ao selecionar um estado, o mapa por município passa a
   mostrar apenas os municípios daquele estado, com zoom automático. Os
   gráficos de barra sempre exibem o valor de cada barra como rótulo, e
   sugerem escala logarítmica automaticamente quando uma categoria concentra
   um valor muito maior que as demais (evitando que barras pequenas fiquem
   invisíveis por causa de um valor discrepante).
3. **Perguntas**: chat em linguagem natural. Antes da primeira pergunta,
   mostra sugestões clicáveis geradas a partir dos dados carregados. Perguntas
   idênticas feitas mais de uma vez na mesma sessão reaproveitam a resposta
   anterior em cache, sem gastar tokens de novo.
4. **Histórico**: datasets e perguntas anteriores (SQLite), além do log
   completo da aplicação com opção de download.
5. **Sobre / Arquitetura**: este próprio README, renderizado dentro do app.

A lógica de detecção de colunas usada na Visão Geral e nas sugestões de
perguntas (`src/overview.py`, `src/suggestions.py`) é deliberadamente
determinística (sem LLM): ela funciona antes mesmo de qualquer chamada de
agente, e usa nomes, tipos e valores de coluna para identificar candidatos a
dimensão categórica (ex.: UF), valor monetário, data e coordenadas
geográficas. Quando mais de uma coluna poderia servir (por exemplo, um
dataset com uma coluna de coordenadas quase vazia e outra populada), a
escolha usa como critério a coluna com mais valores distintos e menos nulos,
não a primeira que bater o nome. O mesmo vale para o mapa por UF: uma coluna
só é considerada candidata quando os valores observados nela são, de fato,
siglas válidas de estado brasileiro (não apenas quando o nome da coluna
sugere isso). O mapa por município depende da presença de uma coluna de
código IBGE do município (7 dígitos, dentro da faixa de valores reais dos
códigos existentes); sem esse código, o mapa por município não é exibido,
mesmo que exista uma coluna com o nome do município, porque casar nomes de
cidade sem o código é sujeito a erro (vários municípios brasileiros têm nomes
iguais em estados diferentes). Se o arquivo enviado não tiver nenhuma coluna
com esse tipo de informação, nenhum mapa é exibido; o painel nunca assume ou
inventa uma dimensão geográfica que não esteja presente nos dados.

## Correções de bugs relevantes

Durante os testes com os arquivos completos do SISSER (superiores a 400 MB no
total) e com filtros ativos na Visão Geral, os seguintes problemas foram
identificados e corrigidos:

- **Consultas com filtro ativo falhavam**: quando um filtro (ex.: ano) estava
  selecionado, as consultas de série temporal e de mapa geográfico geravam
  duas cláusulas `WHERE` em sequência no SQL, o que é inválido. A correção
  combina o filtro do usuário com as condições próprias da consulta em uma
  única cláusula `WHERE ... AND ...`.
- **Perguntas no chat pareciam nunca terminar**: após responder uma pergunta,
  a aplicação chama `st.rerun()` para atualizar a tela. Como o arquivo
  carregado pelo `st.file_uploader` continua presente no widget entre
  execuções, o bloco de upload era executado de novo a cada rerun,
  reprocessando o dataset inteiro (levando dezenas de segundos em arquivos
  grandes) e resetando o histórico do chat exatamente quando a resposta
  estava pronta para aparecer. A correção guarda uma assinatura do último
  arquivo processado (nome e tamanho) e só reprocessa quando essa assinatura
  muda de fato, isto é, quando um arquivo novo é enviado.
- **Gráficos de barra ficavam "vazios" com colunas de valores pequenos**:
  quando uma categoria concentra um valor muito maior que as demais, o eixo
  linear padrão do gráfico esmaga as barras menores até torná-las invisíveis.
  A correção adiciona o valor de cada barra como rótulo (sempre legível,
  mesmo quando a barra é minúscula) e sugere escala logarítmica
  automaticamente quando detecta essa distorção.
- **Limite de tokens da Groq esgotado (dois episódios distintos)**: o modelo
  padrão original para os agentes de raciocínio (`llama-3.3-70b-versatile`)
  tem um limite diário de 100 mil tokens, que se esgota rapidamente. A
  primeira correção trocou o modelo para `openai/gpt-oss-120b`, que tem
  limite diário maior (200 mil tokens), mas esse modelo tem um limite POR
  MINUTO mais baixo (8.000 tokens); como o SISSER é enviado em três arquivos
  (2006-2015, 2016-2024, 2025) com o schema de 38 colunas **idêntico** entre
  eles, o perfil compacto enviado à LLM repetia esse schema três vezes,
  gerando uma única chamada de mais de 8 mil tokens e estourando o limite por
  minuto mesmo estando longe do limite diário. A correção definitiva foi
  detectar arquivos com schema idêntico e agrupá-los em uma única entrada do
  perfil (função `_agrupar_arquivos_com_schema_identico` em
  `src/profiling.py`), o que reduziu o tamanho do perfil compacto do SISSER
  em mais da metade, e voltar a usar `llama-3.3-70b-versatile` para o agente
  de raciocínio, por ter o maior limite por minuto (12.000 tokens) entre os
  modelos gratuitos avaliados. Ver detalhes na seção "Limites de tokens da
  conta Groq".
- **Perguntas repetidas consumiam tokens de novo**: a aplicação agora guarda
  em cache, por sessão, o resultado de cada pergunta respondida com sucesso
  (chave: dataset carregado + texto da pergunta). Se a mesma pergunta for
  feita de novo (por exemplo, ao testar após um erro de limite de taxa), a
  resposta anterior é reaproveitada sem nenhuma nova chamada à LLM, o que
  ajuda a esticar a cota disponível durante uma sessão de testes.

## Estrutura do repositório

```
insurminds-desafio4/
  app.py                        interface Streamlit (upload, chat, histórico)
  requirements.txt
  .env.example                  modelo de variáveis de ambiente
  .gitignore
  LICENSE                       MIT
  .streamlit/config.toml        limite de upload e tema
  assets/
    br_uf.geojson                contorno dos 27 estados brasileiros, usado no
                                 mapa coroplético por UF na Visão Geral
    br_municipios.geojson         contorno dos municípios brasileiros (código
                                  IBGE), usado no mapa coroplético por município
  src/
    ingestion.py                extração do zip, detecção de encoding/delimitador,
                                 normalização para UTF-8
    profiling.py                perfilamento estatístico e detecção de família
    domain_schemas.py           schemas conhecidos (SISSER, NFe) e glossário
    query_engine.py             views DuckDB e execução segura de SQL
    overview.py                  detecção heurística de colunas e cálculo do
                                 painel de Visão Geral (sem LLM)
    suggestions.py               sugestão de perguntas por domínio ou heurística
    storage.py                  histórico em SQLite
    logging_config.py           configuração central de logging (logs/app.log)
    llm_client.py                cliente Groq (langchain-groq)
    agents/
      profiler_agent.py         resumo em linguagem natural + classificação
                                 de domínio desconhecido
      planner_agent.py          gera o plano de análise (JSON)
      executor_agent.py         gera e executa o SQL, com auto-correção
      presenter_agent.py        redige a resposta final e escolhe o gráfico
      pipeline.py                orquestra os quatro agentes em sequência
  tests/
    test_pipeline_deterministico.py   testes que não dependem de LLM/API
    test_app_smoke.py                 testes de fumaça da interface (Streamlit AppTest)
  sample_data/
    exemplo_nfe.zip              cabeçalho + itens de NFe (fornecido no curso)
    exemplo_sisser.zip           três períodos do SISSER (2006-2015, 2016-2024,
                                  2025), usados como caso de uso principal
```

## Como rodar localmente (Windows)

1. Crie a pasta do projeto e entre nela:

   ```
   mkdir C:\Users\jeff_\Documents\i2a2_insurminds_2026\desafio4\app
   cd C:\Users\jeff_\Documents\i2a2_insurminds_2026\desafio4\app
   ```

2. Copie todos os arquivos deste projeto para essa pasta (ou clone o
   repositório, ver seção seguinte).

3. Crie e ative um ambiente virtual dedicado a este projeto:

   ```
   python -m venv .venv
   .venv\Scripts\activate
   ```

4. Instale as dependências:

   ```
   pip install -r requirements.txt
   ```

5. Crie o arquivo `.env` a partir do modelo e preencha sua chave da Groq
   (obtida em https://console.groq.com):

   ```
   copy .env.example .env
   ```

   Edite `.env` e defina `GROQ_API_KEY=sua_chave_aqui`.

6. Rode a aplicação:

   ```
   streamlit run app.py
   ```

   O navegador abrirá automaticamente em `http://localhost:8501`.

## Como publicar (GitHub + Streamlit Cloud)

1. Dentro da pasta do projeto (com o ambiente virtual já configurado), faça o
   commit das alterações:

   ```
   git add .
   git commit -m "Descrição das mudanças"
   ```

   O arquivo `.gitignore` já impede que a pasta `data/` (uploads e histórico) e
   o arquivo `.env` (chave de API) sejam enviados ao GitHub.

2. Envie para o repositório remoto:

   ```
   git push
   ```

3. No painel do Streamlit Cloud (https://share.streamlit.io/), a aplicação
   conectada ao repositório é atualizada automaticamente a cada push na branch
   principal. Se ainda não publicou, clique em "New app", selecione o
   repositório e a branch, e o arquivo principal `app.py`.

4. Antes do primeiro deploy, abra "Advanced settings" > "Secrets" e adicione:

   ```
   GROQ_API_KEY = "sua_chave_aqui"
   ```

   A aplicação lê a chave automaticamente de `st.secrets` quando publicada no
   Streamlit Cloud, sem necessidade do arquivo `.env` (que só existe
   localmente).

## Formato esperado dos dados de entrada

Não há um formato único exigido. O agente de perfilamento detecta
automaticamente:

- **Encoding**: UTF-8, CP1252/Latin-1, entre outros.
- **Delimitador**: vírgula, ponto e vírgula, tabulação.
- **Separador decimal**: ponto ou vírgula.
- **Marcadores de valor nulo**: célula vazia, `-`, `NA`, `N/A`.

Dois formatos foram reconhecidos nativamente (o app aplica um glossário de
negócio específico quando os identifica), mas qualquer outro CSV também
funciona, apenas sem o glossário:

**SISSER** (foco principal): arquivo único por período, com colunas como
`NM_SEGURADO`, `VL_PREMIO_LIQUIDO`, `VL_SUBVENCAO_FEDERAL`,
`VALOR_INDENIZAÇÃO`, entre outras (ver dicionário de dados oficial em
https://dados.agricultura.gov.br/dataset/sisser3). Vários arquivos de
períodos diferentes (ex.: 2006-2015, 2016-2024, 2025) são automaticamente
unidos pelo agente quando a pergunta exigir uma visão consolidada.

**NFe/NFCe**: par de arquivos Cabeçalho + Itens, relacionados pela coluna
`CHAVE DE ACESSO`. Usado durante o desenvolvimento como exemplo de validação
fornecido no material do curso.

## Exemplos de perguntas

Testados contra os dados de exemplo incluídos em `sample_data/`:

**SISSER:**
- Qual o total de subvenção federal pago por UF em 2024?
- Qual a taxa de sinistralidade (indenização dividida por prêmio) por cultura?
- Quais as cinco seguradoras com maior valor de prêmio líquido?
- Qual foi a evolução do número de apólices por ano?
- Qual UF teve a maior área total segurada?

**NFe:**
- Qual o valor total de notas fiscais emitidas por UF?
- Quais os cinco produtos com maior valor total vendido?
- Qual emitente teve o maior faturamento no período?

## Tratamento de arquivos grandes

Os datasets originais do SISSER (fonte oficial) ultrapassam 200 MB por período,
e o requisito do projeto previa a possibilidade de arquivos acima de 500 MB.
Para suportar esse cenário sem esgotar a memória disponível no Streamlit Cloud
(tipicamente limitada a cerca de 1 GB), a aplicação:

1. Nunca carrega o CSV inteiro em um DataFrame pandas quando o arquivo é
   grande. A transcodificação para UTF-8 é feita em streaming (por blocos), e
   a leitura final é feita pelo DuckDB diretamente do arquivo em disco.
2. Usa apenas uma **amostra** (5.000 linhas) para perfilamento e para os
   prompts enviados à LLM. A LLM nunca vê o dataset completo, apenas
   metadados e uma amostra pequena.
3. Os **cálculos finais** (somas, médias, contagens) sempre rodam via SQL no
   DuckDB contra o arquivo completo, garantindo exatidão mesmo quando a
   amostra de perfilamento é pequena.
4. Toda consulta gerada pelos agentes passa por um limite de linhas de
   retorno, para evitar que uma consulta mal formulada (ex.: `SELECT *` sem
   filtro) traga milhões de linhas de volta para a interface.

## Log da aplicação

Todo o processamento (ingestão de arquivos, parâmetros detectados, cada
chamada aos agentes, planos gerados, SQL executado, tentativas de
auto-correção e qualquer erro com detalhe completo) é gravado em
`logs/app.log` (arquivo rotacionado automaticamente, mantendo até 5 arquivos
de 2 MB). O log também pode ser consultado dentro da própria aplicação, na
aba "Histórico", com opção de download. Esse registro é a primeira coisa a
consultar em caso de erro.

## Limites de tokens da conta Groq

Contas gratuitas da Groq têm dois tipos de limite que importam aqui, e cada
modelo tem uma cota própria, independente dos demais:

- **TPM (tokens por minuto)**: limite por chamada/janela curta. Excedê-lo
  retorna HTTP 413 ("Request too large"), mesmo que o restante do dia esteja
  livre. É o limite mais fácil de estourar com uma única chamada grande.
- **TPD (tokens por dia)**: limite acumulado ao longo do dia. Excedê-lo
  retorna HTTP 429 ("Rate limit exceeded") e só libera de novo no horário
  informado na mensagem de erro.

A tabela abaixo resume os limites relevantes (ver valores atualizados em
https://console.groq.com/docs/rate-limits):

| Modelo | RPM | RPD | TPM | TPD |
|---|---|---|---|---|
| llama-3.3-70b-versatile | 30 | 1.000 | 12.000 | 100.000 |
| openai/gpt-oss-120b | 30 | 1.000 | 8.000 | 200.000 |
| openai/gpt-oss-20b | 30 | 1.000 | 8.000 | 200.000 |
| llama-3.1-8b-instant | 30 | 14.400 | 6.000 | 500.000 |

A aplicação usa, por padrão, `llama-3.3-70b-versatile` para o agente de
raciocínio (Planner e Executor) e `llama-3.1-8b-instant` para as tarefas
mais simples (resumo do dataset, redação da resposta final). A escolha do
modelo de raciocínio prioriza o TPM (12.000, o maior entre os modelos
avaliados), não o TPD: o perfil dos dados enviado ao Planner e ao Executor
pode chegar a alguns milhares de tokens em datasets com muitas colunas, e
mais de uma chamada costuma acontecer dentro do mesmo minuto (planejamento,
geração de SQL e, eventualmente, correção de erro). Um modelo com TPM baixo
pode rejeitar uma única chamada mesmo estando bem abaixo do limite diário,
como aconteceu em testes reais com `openai/gpt-oss-120b` (TPM 8.000): o
perfil compacto de três arquivos do SISSER com schema idêntico passava de
8.000 tokens numa única chamada. A aplicação corrige a causa raiz desse
problema agrupando arquivos com schema idêntico em uma única entrada do
perfil (ver "Correções de bugs relevantes"), o que reduz bastante o consumo
por pergunta, além de agora ter um cache de perguntas por sessão que evita
gastar tokens de novo em perguntas repetidas.

Se o limite ainda assim for atingido, os modelos podem ser trocados sem
alterar código, via variáveis de ambiente `GROQ_MODEL_RACIOCINIO` e
`GROQ_MODEL_RAPIDO` (ver `.env.example`), ou aguardando o horário de reset
informado na mensagem de erro.

## Limitações conhecidas

- O histórico armazenado em SQLite não é permanente quando a aplicação roda
  no Streamlit Community Cloud, já que o armazenamento em disco da
  plataforma gratuita não persiste entre reinicializações do serviço.
- Contas gratuitas da Groq têm limites de tokens por minuto e por dia; em
  uso intenso ou compartilhado, a resposta pode demorar mais ou falhar
  temporariamente até o limite ser renovado (ver seção anterior).
- A detecção automática de colunas relevantes (dimensão, valor, data,
  coordenadas, UF, município) usada na Visão Geral e nas sugestões de
  pergunta é baseada em heurísticas de nome, tipo e valor de coluna.
  Funciona bem para os formatos testados, mas pode não identificar
  corretamente colunas de datasets com nomenclatura muito diferente.
- O mapa por município depende de uma coluna de código IBGE no arquivo; sem
  esse código, apenas o nome do município não é suficiente, pois nomes de
  cidade se repetem entre estados diferentes.
- O arquivo `assets/br_municipios.geojson` tem cerca de 8,5 MB após
  simplificação de precisão das coordenadas. Isso aumenta o tempo de
  carregamento inicial do mapa por município (poucos segundos, cacheado
  depois via `st.cache_data`).

## Testes

A camada determinística (ingestão, perfilamento, execução de SQL, detecção de
colunas para a Visão Geral) tem testes automatizados que não dependem de
chave de API. Há também testes de fumaça da interface
(`streamlit.testing.v1.AppTest`) que carregam o `app.py` real e simulam o
upload dos dois exemplos, verificando que nenhuma exceção ocorre ao
renderizar Carga de Dados, Visão Geral e Perguntas:

```
pip install pytest
pytest tests/ -v
```

## Tecnologias utilizadas

- **Python** como linguagem principal.
- **Streamlit** para a interface web.
- **LangChain** e **langchain-groq** para a orquestração dos agentes
  (framework de agentes exigido pelo desafio).
- **Groq** como provedor de LLM, modelos gratuitos (`llama-3.3-70b-versatile`
  para planejamento e geração de SQL, `llama-3.1-8b-instant` para tarefas
  simples).
- **DuckDB** como motor de consulta analítica sobre os arquivos CSV, sem
  exigir carregar o dataset inteiro em memória.
- **pandas** para perfilamento e manipulação de amostras.
- **Plotly** para os gráficos interativos, o mapa de dispersão geográfica e
  os mapas coropléticos por UF e por município.
- **SQLite** para o histórico persistente de datasets processados e
  perguntas realizadas.
- **GitHub** para hospedagem do código-fonte e da documentação.
- **Streamlit Community Cloud** para publicação da aplicação online.

## Licença

Distribuído sob a licença MIT. Ver arquivo [LICENSE](LICENSE).
