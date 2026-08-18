# Atlas S10 — auditoria de vazamento de dados (data leakage)

**Versão:** 1.0
**Data da auditoria:** 18 de agosto de 2026
**Escopo do código auditado:** pipeline de produção (`atlas_s10/`, `pipelines/`,
`services/api/`) e o código inicial dos notebooks (`src/`).
**Natureza:** auditoria estática em nível de código-fonte — rastreio dos
contratos causais, dos *guards* e da suíte de testes. **Não** é uma re-execução
do pipeline nem uma verificação do calendário real de publicação das fontes.

---

## 1. Objetivo e escopo

Esta auditoria responde a uma pergunta específica: **o Atlas S10 sofre de
vazamento de dados (data leakage)?** Isto é, alguma informação que só estaria
disponível *no futuro* em relação à origem de uma previsão entra no treino, na
seleção de modelos, na calibração ou na avaliação — inflando artificialmente o
desempenho reportado no backtest?

Num problema de série temporal com múltiplas fontes de frequências e defasagens
de publicação diferentes (revenda ANP semanal, USD/BRL diário, Brent diário,
cadeia ANP semanal), o leakage é o risco número um. A própria especificação do
TCC o lista como risco central (data leakage por datas de publicação diferentes
das datas de competência) e a metodologia (`research/methodology.md`) o trata
como decisão de projeto.

Foram verificados os oito vetores clássicos de leakage temporal, enumerados na
Seção 3.

## 2. Metodologia da auditoria

1. Leitura integral dos módulos de dados e modelagem: `atlas_s10/data.py`,
   `atlas_s10/features.py`, `atlas_s10/modeling.py`, `pipelines/prepare_data.py`,
   e os módulos iniciais `src/feature_engineering.py`, `src/baseline.py`,
   `src/external_data.py`.
2. Rastreio do **contrato causal** — como cada observação recebe uma marca de
   *quando ocorreu* (`observation_date`) e *quando ficou pública*
   (`available_at`), e qual das duas o backtest efetivamente consulta.
3. Verificação dos **guards** (asserções que abortam a execução) e da suíte de
   testes (`tests/test_causality.py`).
4. Classificação de cada achado usando o vocabulário de evidência da
   metodologia: **Evidence** (o que o código faz), **Inference** (o que isso
   garante) e, quando aplicável, **Limitation**.

## 3. Vetores de leakage verificados

### 3.1 Contrato temporal `observation_date` × `available_at`

**Evidence.** Toda linha semanal carrega `observation_date` (fim da semana de
competência) e `available_at` (fim do dia, após uma defasagem conservadora),
computado por `availability_at_end_of_day` em `pipelines/prepare_data.py:135`.
No `merge_market`, o `available_at` vinculante da linha é a disponibilidade da
**revenda** (`market["available_at"] = market["anp_available_at"]`,
`pipelines/prepare_data.py:897`).

**Inference.** As datas de competência e de disponibilidade não são tratadas
como sinônimos. O backtest gateia treino e ensemble por `available_at`, nunca
pela data de competência isolada. ✅ **Sem vazamento.**

### 3.2 Ordenação de defasagens — o guard mais crítico

**Evidence.** No início de `prepare_data()`:

```python
# pipelines/prepare_data.py:1548-1549
if anp_lag_days < max(usd_lag_days, brent_lag_days):
    raise ValueError("ANP target availability must not precede same-week external availability")
```

Com os defaults `anp_lag_days=8, usd_lag_days=1, brent_lag_days=3`.

**Inference.** Como a origem de cada previsão é a disponibilidade da revenda
(8 dias), e Brent (3 dias) e USD/BRL (1 dia) da **mesma semana** já estão
públicos antes disso, usar Brent e USD contemporâneos como feature é
**causalmente válido**. O guard impede a configuração patológica em que um driver
externo ficaria disponível *depois* do alvo. ✅ **Sem vazamento.**

### 3.3 As-of join da cadeia (distribuição e produtor/importador)

**Evidence.** `align_cost_drivers_asof` anexa preços de distribuição e
produtor/importador com `pd.merge_asof(..., direction="backward")` sobre
`available_at` (`pipelines/prepare_data.py:780-823`), e trava o build se uma
publicação futura entrar numa feature:

```python
# pipelines/prepare_data.py:859, 863
raise AssertionError("Future distribution release entered an as-of feature")
raise AssertionError("Future producer/importer release entered an as-of feature")
```

**Inference.** Cada linha recebe apenas a observação de cadeia **mais recente já
publicada** na data de disponibilidade da revenda. Um *release* futuro nunca
entra. ✅ **Sem vazamento.**

### 3.4 Features backward-only e a equivalência do fatiamento

**Evidence.** Em `atlas_s10/features.py:10-68`, todas as transformações são
retrospectivas: `shift(+k)`, `diff`, `pct_change`, `rolling(...).mean/std/min/max`,
`ewm`. Apenas os **targets** usam `shift(-weeks)` (`features.py:64-67`). O seletor
`model_feature_columns` (`features.py:71-80`) bloqueia os prefixos `target_`,
além de `observation_date`, `available_at`, `price_min` e `price_max`.

**Inference.** Como toda transformação de feature só olha para trás, calcular as
features sobre a série inteira e **depois** fatiar por origem
(`features.iloc[:origin_index+1]`) é matematicamente equivalente a recalculá-las
a cada origem. Não há "vazamento por transformação global". ✅ **Sem vazamento.**

### 3.5 Contaminação treino/validação no backtest

**Evidence.** Em `_point_predictions` (`atlas_s10/modeling.py:211-229`) o conjunto
de treino é duplamente restringido:

```python
training = features.iloc[: origin_index - weeks + 1].dropna(subset=[target_column])
training = training.loc[
    pd.to_datetime(training[f"target_available_at_{horizon_days}"], utc=True)
    <= origin_available
]
assert_causal_training(training, origin, horizon_days)
```

`assert_causal_training` (`features.py:83-90`) torna **fatais** três condições:
target ainda não publicado, publicação futura na fold, e origem contaminando o
próprio treino (`observation_date` do treino ≥ o da origem).

**Inference.** O fatiamento por posição garante que o alvo da última linha de
treino foi observado até a origem; o filtro por `target_available_at` garante que
esse alvo já era **público**; e a asserção fecha as três brechas. ✅ **Sem
vazamento.**

### 3.6 Seleção de modelos, tuning e pesos de ensemble

**Evidence.**
- *Tuning do LightGBM:* `_choose_lgb_params` (`modeling.py:127-159`) escolhe
  hiperparâmetros em **inner origins** estritamente anteriores à origem externa,
  com o mesmo filtro de `target_available_at`.
- *Pesos do ensemble:* em `run_backtest` (`modeling.py:373-395`) os pesos
  inverse-MASE usam apenas erros **já maturados**
  (`realized_at <= origin_available`). O erro é *calculado* com o valor real
  futuro, mas só é *utilizado* depois que aquele futuro amadureceu.
- *Camada probabilística/conformal:* `_add_sequential_probabilities`
  (`modeling.py:317-356`) calibra probabilidade e intervalos P10/P90 apenas com
  folds cujo desfecho era conhecido na origem corrente.

**Inference.** A seleção de modelo, o ajuste de hiperparâmetros e a combinação
são **online/causais** — nenhum deles "espia" resultados futuros. ✅ **Sem
vazamento.**

### 3.7 Pré-processamento (imputação e escala)

**Evidence.** A imputação por mediana do LightGBM é ajustada **só no treino**
(`_prepare_matrix`, `modeling.py:98-99`: `medians = x_train.median(...)`). A
padronização do SARIMAX usa apenas o histórico até a origem
(`modeling.py:189-205`). A escala da métrica MASE em `evaluate_backtest`
(`modeling.py:440-442`) usa somente preços **anteriores** à primeira origem do
backtest.

**Inference.** Não há o erro clássico de ajustar `scaler`/imputador no dataset
inteiro antes do split. ✅ **Sem vazamento.**

### 3.8 Código inicial (`src/`, "primeiro momento") e upstream externo

**Evidence.**
- `src/feature_engineering.py` usa features retrospectivas, target `shift(-1)`
  (`:74`), **split cronológico** (últimas 26 semanas como teste, sem embaralhar —
  `:95`) e valida datas consecutivas t→t+1 (`:97-99`).
- `src/baseline.py:35-67` faz **walk-forward expansivo**: cada semana de teste é
  prevista apenas com histórico anterior, e há guard explícito
  (`src/baseline.py:46`): `raise ValueError("O historico walk-forward contem informacao futura.")`.
- `src/external_data.py:120-142` agrega diário→semanal apenas com estatísticas
  intra-semana e `pct_change` — nada de janela centrada ou futura.

**Inference.** Mesmo a versão inicial dos notebooks é causal: nunca houve
*random split*, e o walk-forward é protegido por asserção. ✅ **Sem vazamento.**

### 3.9 Resumo

| # | Vetor | Evidência (arquivo) | Veredito |
|---|-------|---------------------|----------|
| 3.1 | Contrato `observation_date` × `available_at` | `prepare_data.py:135,897` | ✅ Limpo |
| 3.2 | Ordenação de defasagens | `prepare_data.py:1548` | ✅ Limpo |
| 3.3 | As-of join da cadeia | `prepare_data.py:780-863` | ✅ Limpo |
| 3.4 | Features backward-only | `features.py:10-80` | ✅ Limpo |
| 3.5 | Treino/validação no backtest | `modeling.py:211-229`, `features.py:83` | ✅ Limpo |
| 3.6 | Seleção/tuning/ensemble | `modeling.py:127-159,373-395` | ✅ Limpo |
| 3.7 | Imputação/escala | `modeling.py:98,189-205,440` | ✅ Limpo |
| 3.8 | Código inicial `src/` + upstream | `src/feature_engineering.py:95`, `src/baseline.py:46` | ✅ Limpo |

## 4. Pontos de atenção (hardening) — não são vazamento hoje

Os itens abaixo **não** produzem leakage no estado atual do repositório, mas são
melhorias de robustez que fecham riscos latentes ou removem código enganoso.

1. **Fallback legado menos conservador.** Quando os artefatos `data/gold/` não
   existem, `load_market_frame` computa `available_at = semana_fim + 4d12h`
   (`atlas_s10/data.py:107-109`) e `normalized_observations` usa lag ANP=4 e
   externo=0 — mais frouxo que o pipeline de produção (8/1/3). É **inerte**
   enquanto o gold existe (o caminho de produção é sempre usado), mas convém
   **alinhar os lags do fallback** aos de produção ou **remover** o caminho
   legado para evitar que uma regeneração acidental use disponibilidade otimista.

2. **Asserção "morta" em `snapshot()`.** Em `atlas_s10/data.py:180-182`, o teste
   de publicação futura roda sobre o conjunto **já filtrado** por `<= cutoff`,
   portanto nunca dispara. A proteção real é o próprio filtro; a asserção dá
   falsa sensação de segurança. Sugestão: assertar contra o conjunto original
   (pré-filtro) ou remover a linha e documentar que o filtro é a garantia.

3. **Premissas de defasagem são suposições.** Revenda = 8 dias ("conservadora"),
   distribuição = 14 dias (`assumed_unverified` no próprio metadata),
   produtor/importador = 12 dias. A **ordem relativa** está protegida (Seção 3.2);
   o risco residual é o valor **absoluto** do lag da revenda. Se a publicação
   real da ANP demorar *mais* que 8 dias, o modelo estaria usando o alvo um pouco
   antes de ele ser público — um viés otimista leve. Recomenda-se confirmar
   contra o calendário oficial de publicação da ANP e registrar a evidência.

4. **V0 ignora publication lag.** `src/feature_engineering.py` usa `semana_fim`
   diretamente. Para um modelo **univariado** t→t+1 isso não gera leakage
   treino/teste (fonte única, timing consistente), mas é levemente otimista
   quanto ao *timing operacional*. O pipeline de produção corrige isso com o
   contrato `available_at`.

## 5. Limitações desta auditoria

- É uma auditoria **estática**: não reexecutei `prepare_data.py` / `train.py`
  nem revalidei os artefatos numéricos em `artifacts/`.
- Não verifiquei o **calendário real de publicação** das fontes (ANP, BCB, EIA);
  as defasagens foram avaliadas quanto à **coerência interna e ordem relativa**,
  não quanto ao valor absoluto correto no mundo real.
- Os CSVs `processed/external/brent_semanal.csv` e `usd_brl_diario.csv` foram
  auditados pela lógica de geração em `src/external_data.py`; não inspecionei
  byte a byte os arquivos materializados.
- A auditoria cobre o risco de **leakage**; não avalia poder preditivo,
  significância estatística (o backtest tem 24 origens por horizonte) nem a
  qualidade econômica da política de compra.

## 6. Veredito final

**Não foi identificado vazamento de dados que comprometa o backtest do Atlas
S10.** O projeto trata a causalidade temporal como princípio de projeto, em três
camadas independentes que se reforçam:

1. um **contrato causal** explícito (`observation_date` × `available_at`);
2. **guards que abortam a execução** diante de qualquer publicação futura
   (ordenação de lags, as-of join, `assert_causal_training`);
3. **validação walk-forward** com seleção de modelo, tuning, ensemble e
   calibração todos restritos ao passado de cada origem.

A versão inicial (`src/`, os notebooks) também é limpa: split cronológico e
walk-forward com asserção, sem *random split* em nenhum momento. Os quatro pontos
da Seção 4 são melhorias de robustez, não correções de vazamento.

Para uma banca: o desenho causal deste TCC está **acima da média** e é
**defensável**. A recomendação é (a) aplicar o hardening da Seção 4 e (b)
documentar a validação do lag de 8 dias da revenda contra o calendário oficial da
ANP, fechando o único risco residual (absoluto, não estrutural).

---

*Documento de auditoria — parte do dossiê de metodologia do Atlas S10. Ver
`research/methodology.md` para o contrato causal normativo e `tests/test_causality.py`
para os testes que travam as garantias descritas aqui.*
