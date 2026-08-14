# Atlas S10 — metodologia científica e contrato causal

**Versão:** 1.1  
**Data de corte da auditoria:** 13 de agosto de 2026  
**Status:** especificação normativa; não é uma declaração de que toda a implementação atual já está conforme.

## 1. Decisões metodológicas

O Atlas S10 prevê o preço médio semanal de revenda do Diesel S10 em três horizontes diretos: 1, 2 e 4 semanas, apresentados como aproximadamente 7, 14 e 30 dias. O alvo primário é Brasil; região e UF são extensões condicionadas a cobertura suficiente. Cada horizonte pode ter modelos, hiperparâmetros, pesos, intervalos e campeão diferentes.

As escolhas centrais são:

1. usar o preço de revenda da ANP como alvo, sem substituir lacunas por dados sintéticos;
2. construir toda visão histórica a partir da informação que já estava disponível na origem da previsão;
3. avaliar por múltiplas origens temporais, com ajuste de hiperparâmetros e calibração dentro do passado de cada origem;
4. começar por baselines fortes; LightGBM é o principal challenger tabular;
5. manter VS-ePL-KRLS explicitamente experimental até haver reprodução fiel, testes e licença de código verificada;
6. não treinar uma rede profunda no histórico semanal atual de apenas 130 semanas completas;
7. produzir distribuição/intervalo e probabilidade calibrada, além do ponto;
8. separar previsão de preço da recomendação de compra;
9. promover modelos por evidência local fora da amostra, não pela conclusão de um paper.

Estas escolhas são **inferências de engenharia** apoiadas pela literatura, não fatos universais. R1 e R2 são diretamente relevantes ao diesel brasileiro; R3–R9 trazem evidência indireta de outros mercados e de vendas; R10 e M1–M9 fundamentam desenho de validação, combinação e métricas; R11–R15 e N1–N5 são hipóteses de challengers, não atalhos para seleção.

## 2. Vocabulário de evidência

Todo resultado, card e relatório deve poder ser classificado em quatro campos:

- **Evidence:** o que uma fonte, snapshot ou experimento observou diretamente.
- **Inference:** a hipótese que extraímos dessa evidência para o Atlas.
- **Limitation:** por que a evidência pode não se transferir ou estar incompleta.
- **Implementation consequence:** a decisão testável tomada no sistema.

Exemplo obrigatório:

> **Evidence:** R1 aplica VS-ePL-KRLS a Diesel S10/S500 brasileiro.  
> **Inference:** adaptação on-line pode ajudar sob relações de repasse instáveis.  
> **Limitation:** o paper não usa o mesmo conjunto de vintages, baselines e rolling-origin do Atlas.  
> **Implementation consequence:** o modelo entra como challenger experimental, nunca como vencedor automático.

`papers.yml` registra os quatro campos para cada referência. `sources.yml` faz a mesma separação entre cobertura local observada, política de disponibilidade e lacunas de proveniência.

## 3. Unidade de análise e alvo

### 3.1 Alvo principal

Para cada semana `t` e geografia `g`:

\[
y_{t,g}=\operatorname{mean}(p_{i,t,g})
\]

em que `p` é `Valor de Venda` de uma observação ANP com `Produto = DIESEL S10` e `Tipo da Venda = REVENDA`. A unidade é **R$/litro**.

Procedimento:

1. validar encoding, delimitador, decimal, datas, produto, tipo de venda e unidade;
2. remover linhas totalmente vazias;
3. remover duplicatas byte-a-byte ou por chave/valores, preservando uma linha e registrando o motivo;
4. identificar o posto por CNPJ quando disponível e normalizado;
5. se houver mais de uma coleta válida do mesmo posto na mesma semana, agregar primeiro dentro do posto e sinalizar o caso;
6. calcular média, mediana, mínimo, máximo, desvio, quantis, número de postos, municípios e UFs;
7. excluir semana parcial do treinamento e do placar principal;
8. reconciliar a média produzida com a série agregada oficial da ANP quando a mesma referência semanal estiver disponível.

A média equipondera postos depois do colapso posto-semana. É uma definição operacional do Atlas e pode diferir ligeiramente de uma estatística oficial cuja ponderação/metodologia seja distinta. Essa diferença deve ser exibida, não escondida.

### 3.2 Calendário semanal

O snapshot legado foi agregado com semana terminando no domingo (`W-SUN`), de segunda a domingo. Materiais recentes da ANP também apresentam períodos de referência domingo–sábado. Logo, o rótulo local **não deve ser chamado de “semana oficial ANP”** até a reconciliação.

A camada canônica deve armazenar `period_start` e `period_end`, não apenas um rótulo. Antes da promoção para produção há duas opções válidas:

- reproduzir exatamente os limites da semana oficial e validar contra o agregado publicado; ou
- manter `W-SUN` como calendário Atlas, documentando-o como transformação própria e usando um ledger independente de publicação.

O que é proibido é deduzir `available_at` a partir do nome do bucket semanal.

### 3.3 Cobertura já observada

O inventário local auditado encontrou:

| Recorte | Evidência local |
|---|---:|
| S10 revenda, Brasil | 387.927 observações, 27 UFs, 461 municípios e 10.463 postos |
| Alvo nacional completo | 130 semanas, de 07/01/2024 a 28/06/2026 |
| Postos por semana nacional | 2.267 a 3.532 |
| Preço médio semanal nacional | R$ 5,9612 a R$ 7,5837/l |
| RS | 29.921 observações, 736 postos e 36 municípios |
| Última semana RS adicional | parcial, terminando em 05/07/2026; excluída |

Isto é **Evidence** do snapshot, não garantia de representatividade perfeita. A amostra de postos muda; portanto cobertura e composição fazem parte do diagnóstico de cada semana.

## 4. Contrato point-in-time

### 4.1 Campos mínimos

Cada observação normalizada deve ter:

```text
series_id
observation_date
available_at
ingested_at
value
unit
source
revision
geography
metadata
```

Definições:

- `observation_date`: data/período econômico medido;
- `available_at`: primeiro instante comprovado em que o Atlas poderia conhecer o valor;
- `ingested_at`: instante em que esta instalação capturou os bytes;
- `revision`: identidade/vintage da versão publicada;
- `source`: instituição e recurso exatos, não apenas um domínio genérico.

Uma consulta `snapshot(as_of=O)` só pode retornar linhas com `available_at <= O`. Se qualquer feature usada em uma previsão tiver `available_at > forecast_origin`, o pipeline **falha**. Warning não basta.

### 4.2 Bitemporalidade e revisões

O armazenamento deve separar:

- tempo válido: período a que o número se refere;
- tempo de sistema: quando a versão passou a ser conhecida/ingerida.

Uma correção não sobrescreve o raw anterior. Ela cria nova revisão com checksum e intervalo de vigência no sistema. O backtest usa a revisão conhecida em cada origem; uma visão “latest” pode existir para análise ex post, mas não para seleção histórica.

### 4.3 Política por fonte

| Série | Regra causal | Situação atual |
|---|---|---|
| ANP revenda S10 | usar timestamp real da publicação semanal; feriados podem adiar a divulgação | snapshots existem, mas o ledger histórico de releases não |
| BCB PTAX USD/BRL | usar o boletim de fechamento apenas depois de seu timestamp; previsão intradiária anterior não o vê | 627 dias locais, sem timestamp de ingestão confiável |
| EIA Brent | usar timestamp de release capturado; no legado, proxy conservador com sensibilidade de 1/2/3 dias úteis | 9.947 dias locais, release histórico ausente |
| ANP produtor/importador | no mínimo o atraso oficial estimado de 12 dias; preferir publicação real | 709 semanas locais |
| ANP distribuição | desabilitar no backtest oficial até confirmar recurso e lag | 305 semanas locais, proveniência de download incompleta |
| Biodiesel produzido | liberar após publicação real; não confundir prazo de declaração SIMP com publicação | 258 meses locais; schema muda em 2024 |
| IPCA diesel | usar calendário/timestamp de release do IBGE | 78 meses locais, releases não anexados |
| Selic meta | usar anúncio/entrada efetiva conhecida; série SGS 432 | planejada |
| Petrobras, ICMS e mistura | guardar `published_at` e `effective_at`; ambos importam | planejadas |

Quando a disponibilidade histórica não puder ser reconstruída:

1. a feature fica fora do placar oficial; ou
2. entra numa análise de sensibilidade com nome sufixado `_availability_proxy`, hipótese explícita e resultado separado.

O mtime de um arquivo local não é `ingested_at`. O timestamp atual de uma página também não é o `available_at` de observações antigas.

### 4.4 Alinhamento entre frequências

Em uma origem `O`, uma série diária fornece apenas valores cujo `available_at <= O`. Features semanais podem usar último valor conhecido, média, retorno e volatilidade dos valores já publicados. Uma série mensal é mantida em degrau após sua release; **não é interpolada para trás nem suavizada usando um mês futuro**.

Toda feature exógena carrega:

- `source_observation_date`;
- `source_available_at`;
- `age_days_at_origin`;
- indicador de ausência/staleness;
- método de agregação.

## 5. Qualidade e representatividade dos dados

As validações rodam antes de qualquer feature:

- schema, encoding e tipos;
- duplicidade exata e por chave natural;
- datas fora do intervalo do arquivo;
- frequência e gaps;
- unidade e escala;
- valores impossíveis ou fora de limites robustos;
- cobertura de postos/municípios/UFs;
- mudança de schema;
- missingness total e por período;
- freshness e atraso de publicação;
- revisões e checksum;
- consistência geográfica;
- disponibilidade futura.

Achados locais que devem virar testes de regressão:

- os cinco CSVs automotivos somam 2.134.685 linhas físicas; 9.114 são separadores vazios em 2025.01;
- há 16 duplicatas exatas nos arquivos automotivos, duas no recorte S10 revenda;
- `Valor de Compra` está 100% vazio;
- preços individuais S10 válidos observados variam de R$ 4,73 a R$ 9,99/l;
- o arquivo de IPCA é um relatório SIDRA largo, com 625 colunas; códigos devem substituir posições;
- a produção de biodiesel muda de dimensões detalhadas para uma estrutura mais regional em 2024;
- o arquivo Brent tem dupla extensão, mas conteúdo XLS real.

Outlier não é sinônimo de erro. Um preço extremo válido permanece e recebe flag; remoção só ocorre por regra documentada e com sensibilidade. Mudanças bruscas do agregado exigem comparação com cobertura do painel, eventos e distribuição transversal.

Para mensurar viés de composição, publicar por semana:

```text
n_stations, n_municipalities, n_states
entry_rate, exit_rate
share_of_balanced_panel
raw_mean, station_balanced_mean, median
```

O target oficial continua sendo o definido antes do backtest; a versão balanced-panel é diagnóstico, não uma troca oportunista quando melhora a métrica.

## 6. Features causais

### 6.1 Histórico do S10

Por origem e geografia:

- lags 1, 2, 3, 4, 8 e 12;
- diferenças e retornos em 1, 2 e 4 semanas;
- aceleração (`diff_1 - lag(diff_1, 1)`);
- médias móveis 4, 8 e 12;
- EMA com parâmetros predefinidos/tunados no passado;
- desvio, mínimo, máximo e amplitude móveis;
- momentum e distância para médias;
- dispersão transversal e cobertura da amostra.

Janelas sempre terminam na última observação conhecida. São proibidos `center=True`, preenchimento para trás e cálculo no dataset inteiro antes do split.

### 6.2 Petróleo e câmbio

Para Brent, WTI e USD/BRL:

- último nível conhecido e idade;
- retorno e variação acumulada;
- médias e volatilidades trailing;
- lags compatíveis com o calendário de release;
- `Brent × USD/BRL` e, se WTI existir, `WTI × USD/BRL`.

Interações não recebem tratamento privilegiado. Elas entram em ablação por bloco: somente histórico; +câmbio; +petróleo; +ambos; +downstream/regulação.

### 6.3 Downstream, macro e eventos

Quando causalmente disponíveis:

- preço de produtor/importador e de distribuição;
- produção de biodiesel e vendas/consumo;
- importação/exportação;
- IPCA diesel e Selic;
- eventos Petrobras;
- alíquota/valor ICMS aplicável;
- mistura obrigatória de biodiesel;
- safra, apenas como variável regional opcional.

Eventos regulatórios têm ao menos `published_at` e `effective_at`. Antes da publicação não existem na informação do modelo; depois da publicação e antes da vigência podem aparecer como `announced_not_effective`; durante a vigência, como estado aplicável. A norma consolidada atual nunca é retroprojetada.

### 6.4 Missingness

Imputadores são ajustados no treino de cada fold. Para séries de evento/step, forward-fill só é permitido depois da primeira publicação conhecida. Valores faltantes anteriores não viram zero. O modelo recebe indicador de missing/stale quando apropriado.

Cada bloco de feature precisa mostrar ganho incremental e estabilidade. Se não melhorar consistentemente o backtest ou introduzir fragilidade desproporcional, sai do champion e pode permanecer como experimento.

## 7. Horizontes e construção de exemplos

São treinados modelos diretos:

\[
\widehat y_{t+h}=f_h(X_t), \quad h\in\{1,2,4\}.
\]

Na origem `O_t`, `X_t` contém apenas a informação liberada até `O_t`. O exemplo de treino `(X_j, y_{j+h})` só pode participar se o alvo `y_{j+h}` já estiver publicado e disponível em `O_t`. Isto cria naturalmente um purge na cauda do treino, maior em `h=4`.

Previsão recursiva não é padrão. Ela só pode virar challenger se superar o modelo direto e mostrar que a propagação de erro não degrada 14/30 dias.

O mapa de produto é declarado como aproximação:

| Produto | Horizonte semanal |
|---|---:|
| 7 dias | 1 semana direta |
| 14 dias | 2 semanas diretas |
| 30 dias | 4 semanas diretas (aproximação de 28 dias) |

A interface deve escrever “≈ 30 dias” ou explicar a convenção; não fingir precisão de dois dias inexistente no target semanal.

## 8. Escada de modelos

### 8.1 Baselines obrigatórios

Todos os horizontes avaliam:

1. naive: último preço conhecido;
2. seasonal naive: valor de `t-52`, apenas quando há histórico suficiente;
3. média móvel 4;
4. média móvel 8;
5. média móvel 12;
6. ARIMA;
7. SARIMA;
8. SARIMAX com exógenas causalmente disponíveis;
9. média simples dos melhores baselines, selecionados no treino interno.

Se não houver 52 semanas passadas, o seasonal naive é “indisponível”, não recebe preenchimento improvisado. Ordem, sazonalidade e tendência do ARIMA/SARIMA(X) são escolhidas na validação interna; falha de convergência gera artefato de erro e fallback explícito, nunca uma previsão silenciosamente fabricada.

### 8.2 LightGBM

É o challenger tabular principal porque lida com não linearidade, interações e missingness com custo proporcional ao dataset. Restrições para a amostra curta:

- árvores rasas, folhas mínimas conservadoras e regularização;
- grade pequena ou otimização com orçamento fixo;
- early stopping somente em validação temporal passada;
- seed e threads registradas;
- regressão de ponto; quantis apenas se calibrados fora da amostra;
- importância por permutação em origens futuras e SHAP apenas como descrição do modelo, nunca causalidade.

R2, R13, R14, N2 e N4 justificam testá-lo, mas a inconsistência de R14 impede qualquer alegação prévia de vitória.

### 8.3 VS-ePL-KRLS

R1 dá relevância direta ao Brasil. Ainda assim, antes de codificar:

1. congelar as equações e símbolos da versão escolhida do paper/dissertação;
2. buscar código dos autores e verificar licença;
3. listar diferenças entre paper e Atlas;
4. testar atualização on-line, inicialização, step size, kernel, estabilidade numérica e reprodutibilidade;
5. reproduzir pelo menos um experimento controlado;
6. executar o mesmo outer backtest dos demais.

Sem isso, o nome permitido é **“VS-ePL-KRLS — Experimental”**. Uma aproximação não pode ser chamada de implementação fiel.

### 8.4 TCN ou GRU

Com 130 pontos semanais, a decisão atual é **não treinar** TCN/GRU para o placar. R11, R12, R13, N1 e N2 usam séries diárias muito maiores e/ou upstream. Quando houver histórico bastante, admitir no máximo uma arquitetura pequena, escolhida antes do teste final, com scaler fold-local, early stopping passado e múltiplas seeds.

Critério mínimo para abrir esse experimento: exemplos de treino em número materialmente superior ao total de parâmetros efetivos, pelo menos dois ciclos sazonais quando sazonalidade for usada e origens suficientes para medir estabilidade. O número exato é configuração versionada, não ajustado depois de olhar o teste.

### 8.5 Modelos proibidos de se autoproclamarem úteis

- híbrido por ter a palavra “hybrid” no paper;
- decomposição feita antes do split;
- rede profunda avaliada em uma única seed;
- stacking alimentado por previsões in-sample;
- modelo que ganha apenas contra um baseline fraco;
- modelo cuja feature usa release futura;
- modelo que melhora RMSE e piora materialmente MAE, MASE, calibração ou custo sem explicação.

## 9. Backtest temporal

### 9.1 Outer loop

O placar principal é expanding-window/rolling-origin:

```text
para cada horizonte h:
  para cada origem O no período de avaliação:
    montar snapshot(as_of=O)
    remover exemplos cujo alvo ainda não estava disponível em O
    ajustar pipeline/modelo com treino passado
    prever diretamente O+h
    armazenar previsão, distribuição, versão, origem e realização posterior
```

Com o snapshot atual, a configuração inicial recomendada é reservar aproximadamente o último ano para múltiplas origens, desde que sobrem ao menos 78 semanas para o primeiro ajuste. A geometria exata — `initial_train_size`, `step`, datas e número de origens — é salva no artefato. Se um horizonte/família não tiver amostra suficiente, retorna `insufficient_history`.

Não há um único holdout terminal como evidência principal. O artefato legado com 26 semanas pode ser apresentado como diagnóstico histórico, mas não substitui o protocolo normativo e não deve ser usado repetidamente para inventar modelos.

### 9.2 Inner loop

Em cada origem externa, hiperparâmetros, seleção de features, threshold de classificação, ensemble e calibração usam apenas suborigens internas anteriores. O teste externo fica intocado.

Objetivo interno primário: MAE médio por horizonte. MASE, estabilidade e custo computacional resolvem empates. Uma busca que falhe ou tenha poucas suborigens recua para configuração conservadora pré-registrada.

### 9.3 Robustez

Além do expanding principal:

- rolling window fixo, por exemplo 104 semanas quando viável;
- cortes pré/pós choque quando houver observações suficientes;
- lags conservadores alternativos para fontes sem ledger histórico;
- target raw versus balanced-panel diagnóstico;
- com e sem blocos exógenos;
- seeds diferentes em algoritmos estocásticos.

Resultados de robustez não são combinados seletivamente. O relatório mostra a matriz completa e registra configurações antes da execução.

### 9.4 Dependência entre erros

Previsões de horizontes 2 e 4 têm erros sobrepostos e serialmente correlacionados. Intervalos de métricas, bootstrap e Diebold–Mariano devem respeitar blocos/defasagem do horizonte. “52 origens” não equivalem automaticamente a 52 observações independentes.

## 10. Proteções contra leakage

Testes devem provocar falha para:

- feature com `available_at > forecast_origin`;
- scaler, imputador, seletor ou encoder ajustado fora do fold;
- cálculo rolling centralizado;
- backward-fill;
- decomposição da série completa;
- tuning tocando o outer test;
- calibrador treinado com resultado futuro;
- stacking com previsão do próprio exemplo treinado;
- target transformado usando estatística futura;
- revisão atual aplicada a uma origem antiga;
- evento legal retroprojetado pela data de vigência antes de ser publicado.

Um teste sintético “canário” deve incluir uma coluna que revela o futuro. O pipeline correto a exclui ou falha; ganho absurdo é evidência de defeito, não de descoberta.

## 11. Métricas

### 11.1 Ponto

Por modelo, horizonte, período e geografia:

\[
MAE=\frac1n\sum|y_i-\hat y_i|,
\qquad
RMSE=\sqrt{\frac1n\sum(y_i-\hat y_i)^2}.
\]

MASE usa como escala o erro absoluto médio do naive de uma etapa **calculado somente no treino daquela origem**:

\[
MASE=\frac{\operatorname{mean}|y_i-\hat y_i|}
{\operatorname{mean}_{j\in train}|y_j-y_{j-1}|}.
\]

Denominador zero torna a métrica indefinida e deve ser reportado. sMAPE usa denominador simétrico, com regra explícita para zero. MAE e MASE têm prioridade; RMSE descreve caudas. MAPE não é métrica de promoção.

Publicar:

```text
gain_vs_naive = 1 - MAE_model / MAE_naive
gain_vs_sarimax = 1 - MAE_model / MAE_sarimax
```

com numerador, denominador, origens comuns e intervalo de incerteza.

### 11.2 Direção e alta relevante

Direção simples:

\[
d_{t,h}=\operatorname{sign}(y_{t+h}-y_t).
\]

Empates têm classe própria ou tolerância predefinida; não são silenciosamente contados como queda. Reportar accuracy, balanced accuracy, matriz de confusão e, para alta relevante, precision, recall e F1.

Alta economicamente relevante:

\[
z_{t,h}=1[y_{t+h}>y_t+\tau_{t,h}],
\]

onde `tau` é calculado antes da previsão a partir de financiamento, armazenagem, custo de oportunidade, margem operacional e quantidade. Ele não é escolhido olhando `y_{t+h}`. Se custos da empresa não forem fornecidos, usar cenário demonstrativo claramente rotulado e fazer sensibilidade; não chamar o threshold de universal.

### 11.3 Probabilidade

Para `P(z=1)`:

- Brier score;
- log loss com clipping numérico documentado;
- Brier skill versus probabilidade-base passada;
- reliability curve com contagem por bin;
- calibration intercept/slope quando a amostra permitir.

Platt ou isotonic são ajustados em previsões internas/out-of-fold. Isotonic exige amostra e diversidade de classes suficientes; como regra conservadora, se houver menos de 30 exemplos em qualquer classe, nenhuma calibração flexível recebe status “calibrada”. O relatório mostra `uncalibrated` em vez de fabricar confiança.

### 11.4 Intervalos e quantis

Outputs mínimos: P10, P50, P90. P05/P95 são opcionais. Avaliar:

- pinball loss por quantil;
- cobertura empírica (PICP);
- largura média/mediana;
- interval score;
- cobertura por regime e horizonte.

Um intervalo nominal de 80% que cobriu 67% é exibido como “80% nominal / 67% observado”; jamais como “80% de confiança” sem ressalva.

### 11.5 Comparação estatística

Diebold–Mariano (M8) é evidência secundária. Informar função de perda, correção de autocorrelação, horizonte, versão do teste, número de origens e, se usado, ajuste de pequena amostra. Com poucas origens, priorizar tamanho do efeito e intervalo por block bootstrap. P-valor não decide campeão sozinho.

## 12. Previsões probabilísticas

Ordem de implementação:

1. resíduos rolling por modelo/horizonte;
2. conformal split/rolling sobre previsões out-of-fold passadas;
3. regressão quantílica LightGBM;
4. combinação de densidades, somente com histórico amplo.

Para conformal, o conjunto de calibração contém apenas resíduos realizados antes da origem. Para cobertura `1-α`, usar o quantil finito apropriado dos nonconformity scores. Janela, ponderação por recência e tratamento de drift são versionados. Quantis previstos devem obedecer monotonicidade; correção de crossing é registrada como transformação.

Sob mudança de regime, cobertura marginal histórica não garante cobertura condicional. Por isso a interface mostra cobertura rolling, largura e staleness. N5 é uma direção sofisticada para combinação dinâmica de densidades, não requisito do MVP.

## 13. Ensembles

### 13.1 Baselines de combinação

Comparar, por horizonte:

1. melhor modelo individual elegível;
2. média simples;
3. peso fixo inverse-MASE;
4. peso dinâmico, apenas quando houver histórico suficiente.

Para `k` modelos:

\[
r_i=\frac1{\epsilon+MASE_i},\quad
v_i=\frac{r_i}{\sum_jr_j},\quad
w_i=(1-\lambda)v_i+\lambda/k.
\]

Depois aplicar `0 <= w_i <= 0,60` e renormalizar. MASE vem somente de erros já realizados; `epsilon`, `lambda`, janela e conjunto de modelos são configurações versionadas. O ensemble final usa previsões emitidas na mesma origem e mesma definição de target.

### 13.2 Dinâmico

A janela sugerida é 52 erros realizados por modelo/horizonte, não 52 linhas ainda sem target. Sem esse mínimo, retornar ao peso fixo ou uniforme. Pesos são congelados na origem e salvos no forecast artifact.

N3 e R15 motivam ensembles heterogêneos; M1, M2, R10 e M9 alertam que média simples pode superar pesos estimados. Logo, complexidade só permanece se houver ganho estável.

### 13.3 Diversidade

Calcular correlação de erros em origens comuns, com tamanho da interseção. Se `corr(error)>0,95` e um modelo é consistentemente pior, sinalizar redundância. A exclusão ocorre dentro do treino/registro, nunca depois de inspecionar o teste final. Correlação baixa não compensa um modelo sem skill.

## 14. Champion/challenger

Registro mínimo:

```text
model_id, code_commit, data_snapshot_id, family, horizon
trained_until, features, hyperparameters, random_seed
outer_origins, metrics, calibration, status, artifact, created_at
```

Status: `baseline`, `challenger`, `champion`, `experimental`, `quarantined`.

Gates de elegibilidade:

- contrato point-in-time e testes de leakage aprovados;
- artefato e ambiente reproduzíveis;
- previsões para todas as origens comparáveis ou cobertura explicitada;
- MASE menor que 1 ou justificativa documentada para manter apenas como diversificador;
- nenhuma degradação material ocultada em subperíodos;
- probabilidades/intervalos com avaliação própria;
- custo e latência compatíveis.

Entre elegíveis, o menor MAE nas origens externas comuns é o ponto de partida, com MASE, estabilidade, cauda, calibração, valor econômico, complexidade e diversidade como scorecard — não uma soma arbitrária que mascara trade-offs. Se o ganho estiver dentro da incerteza e o challenger for mais complexo, o baseline permanece campeão. Há um campeão por horizonte.

Quarentena ocorre por leakage, schema quebrado, dependência indisponível, drift severo, falha repetida de convergência, deterioração contra naive ou cobertura probabilística enganosa. Retorno exige novo backtest versionado.

## 15. Motor de decisão

### 15.1 Separação de responsabilidades

O forecaster retorna uma distribuição de preços e metadados. O decision engine recebe essa distribuição mais o estado da empresa; ele não altera retroativamente o modelo para obter uma ação desejada.

Entradas mínimas:

```text
forecast_distribution, prob_up
inventory, tank_capacity, expected_consumption
planning_horizon, financing_cost, storage_cost, cash_cost
emergency_purchase_penalty, supplier_lead_time
max_advance_share, safety_stock
```

Necessidade líquida:

\[
Q_{need}=\max(0,D_H+safety\_stock-inventory).
\]

As quantidades precisam respeitar capacidade, estoque, consumo, lote e antecipação máxima. Para uma ação `a`, calcular:

\[
E[C(a)] = C_{purchase}+C_{finance}+C_{storage}+E[C_{later}]
          +E[C_{shortage}]+C_{cash/risk}.
\]

As ações candidatas são `NORMAL`, `BUY_NOW`, `WAIT` e `BUY_PARTIAL`. Avaliá-las na mesma distribuição e escolher o menor custo esperado. Em empate dentro de uma tolerância econômica predefinida, preferir `NORMAL` ou a ação menos irreversível.

O resultado mostra decomposição do custo, restrição ativa e cenários. “Comprar agora” significa “menor custo esperado sob estes dados e parâmetros”, não conselho financeiro absoluto.

### 15.2 Threshold econômico

Por litro, uma aproximação transparente é:

\[
\tau_h = carry_h + storage_h + opportunity_h + risk\_margin_h
         - avoided\_emergency\_cost_h.
\]

O cálculo exato e unidades ficam no relatório. `P(y_{t+h}>y_t+tau_h)` é distinto de `P(y_{t+h}>y_t)` e deve ser apresentado assim.

### 15.3 Backtest econômico

Simular sequencialmente:

- calendário normal;
- antecipar;
- esperar;
- parcial;
- política do modelo.

Em cada origem, o estado de estoque vem das ações anteriores; não pode ser reiniciado com conhecimento futuro. Preço realizado, demanda e penalidades são aplicados quando ocorrem. Medir custo total, economia absoluta/relativa versus política normal, regret versus melhor ação ex post, pior regret, drawdown econômico, falsos sinais e capital médio antecipado.

O oracle serve apenas para calcular regret e limite descritivo. Não é benchmark atingível. Uma economia histórica não é promessa futura.

## 16. Confiança, disagreement e explicabilidade

“Confiança” é uma avaliação operacional, não uma porcentagem decorativa. A probabilidade de alta pode ser percentual quando calibrada; confiança do sistema deve ser uma categoria derivada de:

- freshness/completude das fontes;
- número de erros realizados no horizonte;
- cobertura e largura recentes do intervalo;
- Brier skill/calibração;
- dispersão entre modelos;
- estabilidade por janelas/regimes;
- distância da origem atual ao domínio de treino.

Regras/taxonomia são versionadas. Se uma fonte crítica está atrasada, a cobertura degradou ou modelos divergem, a categoria cai e o motivo aparece. Um “74% de confiança” sem alvo probabilístico, calibração e denominador é proibido.

Model disagreement inclui intervalo entre forecasts, desvio robusto e matriz de erro. Divergência pode ampliar intervalos ou impedir ação agressiva; não é automaticamente incerteza probabilística calibrada.

Explicabilidade:

- SARIMAX: coeficientes, sinais, incerteza e diagnóstico de resíduos;
- LightGBM: permutation importance temporal e SHAP por origem;
- ensemble: pesos e contribuição de cada componente;
- decisão: decomposição de custo e cenário contrafactual.

SHAP explica o modelo dado o conjunto de features; não prova causalidade econômica. Importância calculada no treino e desempenho em origem futura devem ser distinguidos.

## 17. Monitoramento e drift

Monitorar por série e horizonte:

- atraso/freshness e mudança de schema;
- cobertura geográfica e panel turnover;
- missingness e distribuição de features;
- erro rolling e ganho versus naive;
- bias, direção e Brier;
- cobertura/largura dos intervalos;
- correlação e dispersão de modelos;
- decisão/custo/regret.

Alertas têm severidade e ação:

- `info`: mudança esperada, sem impacto;
- `warning`: staleness ou degradação moderada; reduzir confiança;
- `critical`: leakage, unidade/schema incompatível, fonte futura ou desempenho materialmente pior; bloquear treino/previsão ou colocar modelo em quarentena.

Regimes (`estabilidade`, `choque cambial`, `choque petróleo`, `reajuste`, `tributário`, `mistura`) começam como regras causais predefinidas. Clustering feito com o período completo não pode ser usado para fingir que o regime era conhecido na origem.

## 18. Reprodutibilidade

Cada execução grava:

- checksums de raw e manifest;
- URL final, headers relevantes e timestamps de fetch;
- versões de schema e transformações;
- commit, dependências, SO e seeds;
- calendário, timezone e convenção semanal;
- definição do target e features;
- origens outer/inner e purge;
- hiperparâmetros, logs, falhas e duração;
- previsões por origem antes de agregar métricas;
- pesos, calibrador e thresholds;
- relatório de dados e limitações.

Raw é imutável. Bronze normaliza forma sem alterar significado; silver aplica chaves/tempo causal; gold constrói matrizes por `as_of`. Um artifact sem `data_snapshot_id` ou sem lista de origens não entra no registry.

## 19. O que os dados atuais permitem afirmar

**Evidence:** há matéria-prima oficial suficiente para uma demo nacional de 130 semanas, além de Brent, PTAX, produtor/importador, distribuição, biodiesel e IPCA em arquivos locais. O baseline legado RS tem 26 previsões de holdout; o naive obteve MAE aproximado de 0,0823 e RMSE de 0,1632. A accuracy direcional de 69,23% nesse holdout é enganosa isoladamente: o naive sempre previu “não alta” e a classe ocorreu em 18 de 26 casos.

**Inference:** baselines de persistência serão difíceis de superar; métricas balanceadas, probabilidade e custo são essenciais. A cobertura nacional oferece melhor MVP do que permanecer hardcoded em RS.

**Limitation:** 130 semanas é uma amostra curta; não há histórico local de vintages/releases, vários drivers planejados ainda não existem e o painel de postos muda. O holdout legado não implementa todo o protocolo aqui descrito.

**Implementation consequence:** resultados atuais devem ser rotulados como demo/auditoria, com features de disponibilidade incerta fora do placar causal. O sistema deve promover o alvo nacional, reconstruir um ledger de releases e retreinar antes de alegar produção.

## 20. Matriz de adoção da literatura

| Decisão Atlas | Evidence | Inference | Limitação | Consequência |
|---|---|---|---|---|
| Baselines ARIMA/SARIMA(X) | R2–R6 | modelos simples são competitivos em combustíveis | mercados/protocolos diferentes | obrigatórios antes de ML |
| Point-in-time e combinação simples | R10, M1, M2 | vintages e pooling reduzem falsa confiança | R10 é gasolina mensal dos EUA | ledger causal e média simples obrigatórios |
| VS-ePL-KRLS | R1 | adaptação on-line pode lidar com drift | sem reprodução Atlas/código licenciado confirmado | experimental |
| LightGBM/XGBoost | R13, R14, N2, N4 | árvores capturam interações tabulares | R14 tem conflito; alvos upstream | LightGBM challenger com ablação |
| TCN/GRU/CNN-LSTM | R11–R13, N1, N2 | sequências grandes podem sustentar DL | só 130 semanas locais; decomposition leakage | adiado/gated |
| Ensemble dinâmico | R15, N3, N5 | diversidade e pesos variantes podem ajudar | alto risco de estimação em amostra curta | simples primeiro; cap/shrinkage |
| Rolling-origin e MASE | M3–M5 | seleção deve imitar implantação | origens são dependentes | outer expanding + inner temporal |
| Probabilidade/quantis | M6, M7, N5 | decisão precisa de distribuição e loss | calibração pequena/instável | Brier, reliability, pinball e cobertura |
| Direção e valor operacional | N4, R9 | erro de sinal e custo importam além do ponto | retorno de WTI/estação não é S10 nacional | métricas e engine separados |

## 21. Limitações abertas

1. **Disponibilidade histórica:** principal risco científico; proxies não equivalem a vintages.
2. **Amostra curta:** limita tuning, DL, calibração e testes de significância.
3. **Painel variável:** média nacional pode mudar por composição.
4. **Repasse econômico:** Brent/USD não se transforma instantaneamente em preço de bomba; lags variam.
5. **Drivers ausentes:** Petrobras, ICMS, vendas, comércio, WTI e safra ainda não estão adquiridos.
6. **Schemas mutáveis:** biodiesel, SIDRA e arquivos ANP exigem contratos e versionamento.
7. **Granularidade:** previsão nacional não garante skill estadual/municipal.
8. **Incerteza condicional:** cobertura marginal não protege todos os regimes.
9. **Decisão simplificada:** o engine não substitui um otimizador logístico completo nem contratos reais do cliente.
10. **Transferência acadêmica:** muitos papers preveem crude, retornos ou vendas, não Diesel S10 brasileiro.
11. **Conflitos bibliográficos/resultados:** R6, R14 e a versão do identificador M8 permanecem explicitamente sinalizados.

## 22. Checklist de conformidade

Uma release só pode dizer “backtest causal Atlas S10” se:

- [ ] alvo, calendário e geografia estiverem versionados;
- [ ] todas as features tiverem `available_at` verificável ou estiverem excluídas;
- [ ] `snapshot(as_of)` tiver teste de falha futura;
- [ ] duplicatas, partial weeks e cobertura estiverem reportadas;
- [ ] outer rolling-origin e inner temporal estiverem separados;
- [ ] scaler, decomposição, seleção, tuning, stacking e calibração forem fold-local;
- [ ] naive, médias móveis e ARIMA/SARIMA(X) estiverem no mesmo placar;
- [ ] métricas forem calculadas nas mesmas origens;
- [ ] intervalos mostrarem cobertura observada;
- [ ] probabilidade mostrar Brier/reliability e tamanho amostral;
- [ ] pesos de ensemble vierem apenas de erros já realizados;
- [ ] ação operacional mostrar custos e restrições;
- [ ] artifacts, hashes, seeds e commit estiverem registrados;
- [ ] limitações e features indisponíveis aparecerem na interface.

Sem todos os itens, o resultado pode continuar útil como **demo exploratória**, mas não recebe o selo de avaliação causal reproduzível.
