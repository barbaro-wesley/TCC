# Especificação Inicial do TCC

## Sistema Inteligente de Apoio à Decisão para Compras de Combustíveis

Documento de contexto técnico, dados, hipóteses e próximos passos Este
documento consolida o contexto definido até o momento para a nova
proposta de TCC. Ele deve servir como referência dentro do repositório
no VS Code e poderá ser atualizado conforme a análise exploratória, a
disponibilidade dos dados e os experimentos de Machine Learning
avançarem. \# 1. Visão geral da ideia A proposta é desenvolver um
sistema inteligente de apoio à decisão para o setor de compras de
empresas, inicialmente focado em empresas de logística que compram
combustível em grande escala para suas frotas. O sistema não deve ser
apresentado como uma ferramenta capaz de prever com certeza o preço
futuro. A proposta é estimar preços e movimentos de curto prazo,
representar a incerteza da previsão e transformar essas estimativas em
informações úteis para decisões de compra. Exemplos de saída esperada:
preço esperado para a próxima janela; intervalo provável de preço;
probabilidade de alta ou queda; recomendação de comprar, aguardar ou
realizar compra parcial; e eventual economia potencial em comparação com
estratégias de referência. \# 2. Formulação preliminar do tema Tema
sugerido: Desenvolvimento de um sistema inteligente de apoio à decisão
para compras de insumos baseado em previsão probabilística de preços.
Escopo inicial recomendado: Diesel S10 no Brasil, começando por uma
região/UF (por exemplo, Rio Grande do Sul) e posteriormente avaliando a
generalização para outros estados ou regiões. Expansões futuras
possíveis incluem outras commodities e matérias-primas, como aço, cobre
e borracha. Essas expansões não devem fazer parte do primeiro modelo
antes que a metodologia seja validada com combustível. \# 3. Problema de
pesquisa Pergunta preliminar: É possível utilizar séries temporais e
variáveis exógenas para gerar previsões probabilísticas de curto prazo
do preço do combustível que melhorem decisões de aquisição? Uma segunda
pergunta experimental possível é comparar modelos univariados, que
utilizam apenas o histórico do combustível, com modelos multivariados
que incorporam petróleo Brent, câmbio e informações da cadeia de
produção e distribuição. \# 4. Saídas esperadas do sistema - Estimativa
do preço médio futuro do combustível. - Intervalo de previsão, evitando
falsa precisão. - Probabilidade de alta e probabilidade de queda. -
Variação percentual esperada para o horizonte analisado. - Recomendação
de decisão: comprar, aguardar ou, futuramente, comprar parcialmente. -
Nível de confiança/risco da recomendação. - Simulação da economia ou
custo adicional gerado pela política de compra. \# 5. Horizonte temporal
e granularidade Os dados públicos da ANP utilizados como variável-alvo
possuem principalmente frequência semanal. Por isso, a primeira versão
deve priorizar previsão para a próxima semana ou próximas janelas
semanais, em vez de prometer o melhor dia específico (segunda, terça,
quarta etc.). Caso no futuro sejam obtidos dados privados diários de
cotações ou compras de uma transportadora/fornecedor, o sistema poderá
evoluir para recomendações em granularidade diária. \# 6. Dados já
coletados \# 7. Detalhes das bases \## 7.1 ANP -- Revenda de
combustíveis Foram coletados arquivos de combustíveis automotivos
separados por semestre, incluindo dados de 2024, 2025 e primeiro
semestre de 2026. A base será usada para construir séries por produto,
UF e, quando a cobertura permitir, município. Variável-alvo inicial
sugerida: preço médio semanal do Diesel S10 no Rio Grande do Sul.
Posteriormente devem ser testados outros estados e níveis geográficos.
\## 7.2 Banco Central -- USD/BRL O câmbio USD/BRL foi coletado para os
mesmos períodos. Como a série é diária, será transformada em features
semanais como média, mínimo, máximo, último valor disponível e variação
semanal. \## 7.3 EIA -- Brent A série correta é Europe Brent Spot Price
FOB (Dollars per Barrel), Sourcekey RBRTE. O arquivo contém histórico
diário desde maio de 1987. O arquivo bruto completo deve ser preservado.
Features candidatas: média semanal, mínimo, máximo, último preço,
variação percentual e volatilidade semanal. \## 7.4 ANP -- Produtores e
importadores Foi coletada a planilha de Preços Médios Ponderados
Semanais a partir de 2013. Ela representa preços praticados por
produtores/importadores e pode permitir a análise da defasagem entre
mudanças no início da cadeia e alterações posteriores em distribuição e
revenda. \## 7.5 ANP -- Distribuição A orientação é utilizar a série
semanal para o Brasil inteiro. Os dados brutos não devem ser limitados
ao RS, pois a cobertura nacional permitirá testar modelos em outras UFs
e estudar generalização geográfica. \## 7.6 Biodiesel Foram coletadas as
bases de produção de biodiesel de 2005--2023 e 2024--2026. Produção não
é preço: essa informação deve ser tratada como variável auxiliar de
oferta e só permanecer no modelo se demonstrar valor preditivo. \## 7.7
IBGE -- IPCA A tabela escolhida é a SIDRA 7060. A variável inicial é
IPCA -- Variação mensal (%), Brasil, cobrindo de janeiro de 2020 a junho
de 2026. Itens selecionados/recomendados: - 5.Transportes -
51.Transportes - 5102.Veículo próprio - 5104.Combustíveis (veículos) -
5104001.Gasolina - 5104002.Etanol - 5104003.Óleo diesel - 5104005.Gás
veicular \# 8. Dados não priorizados neste momento Histórico direto da
Petrobras não será obrigatório na primeira versão, pois não foi
encontrada uma série histórica de download tão conveniente quanto as
bases da ANP e a ANP já oferece informações de produtores/importadores e
distribuição. ICMS também não será priorizado no Dataset V0. Para o
período recente do diesel, alterações tributárias podem ser incorporadas
posteriormente como eventos/regimes regulatórios construídos a partir de
atos oficiais. Outras variáveis como Selic, PIB, desemprego, Ibovespa,
notícias e sentimento não devem ser adicionadas antes de testar o poder
preditivo do núcleo atual. \# 9. Estrutura recomendada do repositório
data/ ├── raw/ │ ├── anp/ │ │ ├── revenda/ │ │ ├── distribuicao/ │ │ ├──
produtor_importador/ │ │ └── biodiesel/ │ ├── bcb/ │ │ └── usd_brl/ │
├── eia/ │ │ └── brent/ │ └── ibge/ │ └── ipca/ ├── processed/ └──
final/

notebooks/ ├── 01_data_inventory.ipynb ├── 02_data_cleaning.ipynb ├──
03_eda.ipynb ├── 04_feature_engineering.ipynb ├── 05_baseline.ipynb ├──
06_models.ipynb └── 07_backtesting.ipynb \# 10. Regras de engenharia de
dados - Arquivos em data/raw nunca devem ser alterados manualmente. -
Limpeza, padronização e agregações devem gerar novos arquivos em
data/processed. - O dataset efetivamente utilizado pelos modelos deve
ficar em data/final. - Sempre preservar a maior granularidade disponível
na fonte; agregar somente durante o processamento. - Não preencher datas
futuras com informações que ainda não estavam publicadas naquele
momento. - Registrar fonte, período, frequência e significado de cada
coluna criada. \# 11. Integração temporal As bases possuem frequências
diferentes: Brent e dólar são diários; ANP é majoritariamente semanal;
produção de biodiesel e IPCA são mensais. O Dataset V0 deverá utilizar
uma referência semanal. Dados diários serão agregados para a semana.
Dados mensais devem ser associados às semanas somente quando a
informação já estiver disponível/publicada, evitando vazamento de
informação (data leakage). \# 12. Features candidatas \# 13. Targets a
testar Regressão: - diesel_s10_preco_t+1 = preço médio do Diesel S10 na
próxima semana. Classificação: - 1 = preço subiu na próxima semana; 0 =
preço caiu/não subiu. Também deve ser estudada uma saída probabilística,
como P(alta), P(queda) e intervalo de previsão. \# 14. Modelos e
baselines O projeto não deve começar por redes neurais. Primeiro deve
existir um baseline forte e simples. - Naive Forecast: preço da próxima
semana = preço desta semana. - Média móvel / modelos estatísticos
simples. - ARIMA/SARIMA. - Random Forest. - XGBoost/LightGBM. - LSTM/GRU
somente após baselines e modelos tabulares. \# 15. Estratégia de
validação Não utilizar divisão aleatória convencional de treino/teste.
Como o problema é temporal, deve ser utilizada divisão cronológica e,
idealmente, walk-forward validation. Exemplo conceitual: treinar no
passado, prever a janela seguinte, avançar no tempo e repetir. Isso
simula o funcionamento real do sistema. \# 16. Métricas - MAE, RMSE e
eventualmente MAPE para regressão. - Accuracy, Precision, Recall, F1 e
ROC-AUC conforme aplicável para direção do preço. - Calibração das
probabilidades de alta/queda. - Cobertura e largura dos intervalos de
previsão. - Métrica de negócio: custo total de aquisição em backtesting.
\# 17. Backtesting e valor de negócio Uma das avaliações centrais deverá
simular decisões históricas. O objetivo não é somente obter um bom RMSE,
mas verificar se as previsões poderiam gerar decisões de compra
economicamente melhores. Estratégias candidatas para comparação: -
Comprar sempre em um dia/janela fixa. - Comprar apenas quando o estoque
atingir um limite. - Seguir a recomendação do modelo. - Oracle: comprar
no melhor preço conhecido do futuro, apenas como limite teórico. \# 18.
Motor de decisão -- fase posterior Após validar o forecasting, uma
segunda camada poderá transformar previsão em recomendação. Ela poderá
receber estoque atual, consumo diário, capacidade máxima, estoque de
segurança, volume necessário, lead time do fornecedor e tolerância ao
risco. A recomendação poderá evoluir de COMPRAR/AGUARDAR para decisões
de quantidade, como comprar uma parcela agora e postergar o restante. \#
19. Principais riscos e desafios - Cobertura e consistência dos dados
regionais da ANP. - Quantidade limitada de observações caso o período
seja curto. - Mudanças de regime e concept drift. - Eventos geopolíticos
e regulatórios imprevisíveis. - Data leakage devido a datas de
publicação diferentes das datas de competência. - Confundir correlação
com causalidade. - Features redundantes, especialmente IPCA de diesel
versus preço ANP. - Previsão boa em métrica estatística mas sem ganho
financeiro no backtesting. - Diferença entre preço médio público e preço
efetivamente negociado por uma transportadora. \# 20. Dados privados
desejáveis Se for possível obter dados anonimizados de uma empresa de
logística, eles podem aumentar muito o valor do TCC. Campos úteis
incluem data da compra, tipo de combustível, quantidade em litros, preço
por litro, UF/região, condição de pagamento, prazo de entrega e
eventualmente estoque/consumo. \# 21. Próximo passo imediato Criar o
notebook 01_data_inventory.ipynb. Ainda não treinar modelos. O objetivo
é abrir todas as bases e produzir um inventário confiável. - Dimensões
de cada arquivo. - Lista e significado das colunas. - Tipos de dados. -
Data mínima e máxima. - Frequência temporal. - Produtos disponíveis. -
UFs e municípios disponíveis. - Quantidade de valores ausentes. -
Duplicidades. - Cobertura temporal comum entre as fontes. - Verificação
da presença de Biodiesel B100 na base de produtores/importadores. \# 22.
Critério de sucesso da primeira prova de conceito A primeira prova de
conceito será considerada promissora se um modelo treinado apenas com
informações disponíveis até cada instante conseguir superar de forma
consistente o Naive Forecast em dados futuros e se a política de decisão
baseada nessas previsões apresentar ganho econômico ou redução de risco
em backtesting. \# 23. Decisões atuais de escopo - Combustível,
especialmente Diesel S10, é o caso principal. - Primeiro experimento
geográfico: uma UF, preferencialmente RS; depois testar outras
regiões. - Dados brutos nacionais devem ser preservados sempre que
disponíveis. - Previsão inicial semanal, não diária. - Brent utilizado:
Europe Brent Spot Price FOB (RBRTE), não WTI. - ANP + USD/BRL + Brent +
cadeia de distribuição formam o núcleo inicial. - IPCA e biodiesel são
variáveis auxiliares e precisam provar valor no experimento. - Petrobras
e ICMS não são requisitos para o Dataset V0. - Expansão para aço, cobre
e borracha fica para depois da validação da metodologia.

Fim da especificação inicial --- documento vivo do projeto.

# Tabelas de referência

  ---------------------------------------------------------------------------------------------------------
  Fonte          Base                      Frequência     Uso                        Status
  -------------- ------------------------- -------------- -------------------------- ----------------------
  ANP            Preços de combustíveis    Semanal        Variável-alvo e preços     Coletado
                 automotivos / revenda                    regionais                  

  Banco Central  USD/BRL                   Diária         Variável exógena cambial   Coletado

  EIA            Europe Brent Spot Price   Diária         Referência internacional   Coletado
                 FOB -- RBRTE                             de petróleo                

  ANP            Preços médios ponderados  Semanal        Etapa anterior da cadeia   Coletado
                 de                                                                  
                 produtores/importadores a                                           
                 partir de 2013                                                      

  ANP            Preços de distribuição de Semanal        Preço na distribuição      Coletado
                 combustíveis -- Brasil                                              

  ANP            Produção de biodiesel     Mensal         Variável auxiliar de       Coletado
                 2005--2023 e 2024--2026                  oferta                     

  ANP            Biodiesel B100 em base de Semanal        Componente relacionado ao  Verificar na base
                 produtores/importadores                  diesel                     

  IBGE/SIDRA     IPCA -- Tabela 7060       Mensal         Inflação de                Coletado/selecionado
                                                          transportes/combustíveis   
  ---------------------------------------------------------------------------------------------------------

  -----------------------------------------------------------------------
  Grupo                               Exemplos
  ----------------------------------- -----------------------------------
  Diesel                              preço atual; lags t-1...t-4; média
                                      móvel; variação 1/4 semanas

  Brent                               média; mínimo; máximo; último;
                                      variação; volatilidade; lags

  USD/BRL                             média; mínimo; máximo; último;
                                      variação; lags

  Cadeia ANP                          preço produtor/importador;
                                      distribuição; respectivas
                                      defasagens

  Biodiesel                           preço B100 quando disponível;
                                      produção mensal

  IPCA                                Transportes; Combustíveis;
                                      Gasolina; Etanol; Óleo diesel

  Geografia                           UF; região; município quando houver
                                      cobertura suficiente
  -----------------------------------------------------------------------
