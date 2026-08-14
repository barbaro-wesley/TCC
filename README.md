# Atlas S10

Fuel Procurement Intelligence para Diesel B S10 no Brasil.

O Atlas S10 combina dados públicos reais, previsão probabilística e restrições de
estoque para apoiar decisões de compra de combustível. A aplicação não apresenta
uma “ordem de compra”: ela mostra cenários, incerteza, risco, quantidade factível e
o resultado histórico de uma política operacional.

## Estado atual

- Target nacional ANP: 135 semanas completas, de 07/01/2024 a 02/08/2026.
- Último preço observado: **R$ 6,9877/L**, amostra de 3.063 postos.
- Horizontes diretos: 7 dias (1 semana), 14 dias (2 semanas) e 30 dias (4 semanas).
- Validação: 24 rolling origins por horizonte, sem random split.
- Modelos: naive, seasonal naive, médias móveis, ARIMA, SARIMA, SARIMAX,
  LightGBM, ablação LightGBM somente-preço e ensembles.
- Camada probabilística: P10/P50/P90, probabilidade de alta maior que 0,5%,
  calibração histórica e indicador de concordância.
- Produto: API FastAPI e dashboard Next.js responsivo, com fallback offline real.

Resultados do último treino:

| Horizonte | P50 | Variação | P10–P90 | Prob. alta relevante |
|---|---:|---:|---:|---:|
| 7 dias | R$ 6,9819 | -0,08% | R$ 6,8957–7,0681 | 45,1% |
| 14 dias | R$ 6,9897 | +0,03% | R$ 6,7798–7,1995 | 47,6% |
| 30 dias | R$ 7,0035 | +0,23% | R$ 6,2779–7,7292 | 49,1% |

Esses números são artefatos do corte atual, não valores fixos no código.

## Arquitetura

```text
raw/ + data/cache/             snapshots oficiais locais
          │
          ▼
pipelines/prepare_data.py      parsing, DQ, available_at, gold causal
          │
          ▼
atlas_s10/features.py          features e alvos diretos 7/14/30
          │
          ▼
pipelines/train.py             rolling-origin, modelos, ensemble, intervalos
          │
          ├── artifacts/       forecasts, registry, backtest e relatórios
          ├── data/gold/       CSV + Parquet
          └── data/atlas_s10.duckdb
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
services/api/            apps/web/
FastAPI                  Next.js + TypeScript
```

Principais diretórios:

- `atlas_s10/`: dados, features, métricas, modelos, decisão e relatórios.
- `pipelines/`: sincronização, preparação, treino e snapshot do produto.
- `services/api/`: API FastAPI.
- `apps/web/`: dashboard B2B.
- `research/`: fontes, papers e metodologia auditada.
- `tests/`: contratos de dados, causalidade, métricas, ensemble, decisão e API.

## Requisitos

- Windows 10/11 com PowerShell, ou shell equivalente.
- Python 3.11 ou superior.
- Node.js 20 ou superior e npm.
- Aproximadamente 1 GB livre para ambiente, dependências e dados locais.

O projeto foi validado neste ambiente com Python 3.14, Node.js 24 e npm 11.

## Instalação

Na raiz do repositório:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

cd apps\web
npm.cmd ci
cd ..\..
```

Usar diretamente `.venv\Scripts\python.exe` evita problemas com a política de
execução do PowerShell ao ativar ambientes virtuais.

Opcionalmente, copie as configurações locais:

```powershell
Copy-Item .env.example .env
```

## Rodar a aplicação

Os artefatos pré-calculados já permitem abrir a demo sem retreinar.

### 1. Backend

Em um terminal, na raiz:

```powershell
.\.venv\Scripts\python.exe -m uvicorn services.api.main:app --reload --host 127.0.0.1 --port 8000
```

### 2. Frontend

Em outro terminal:

```powershell
cd apps\web
npm.cmd run dev
```

Abra:

- Dashboard: <http://localhost:3000>
- Swagger/OpenAPI: <http://127.0.0.1:8000/docs>
- Healthcheck: <http://127.0.0.1:8000/health>

Se a API não estiver disponível, o frontend usa `apps/web/public/demo-data.json`
e identifica visualmente o estado como snapshot local. Nenhum número aleatório é
injetado nesse fallback.

## Atualizar dados e previsões

### Usar os snapshots oficiais já armazenados

```powershell
.\.venv\Scripts\python.exe pipelines\sync_data.py
.\.venv\Scripts\python.exe pipelines\prepare_data.py
.\.venv\Scripts\python.exe pipelines\train.py
.\.venv\Scripts\python.exe pipelines\build_product.py
```

O primeiro comando valida hashes e schemas do cache sem acessar a internet. O
treino completo leva aproximadamente dois a três minutos nesta máquina.

### Solicitar atualização de rede

```powershell
$env:ALLOW_NETWORK_SYNC='1'
.\.venv\Scripts\python.exe pipelines\sync_data.py --network
.\.venv\Scripts\python.exe pipelines\prepare_data.py
```

O conector baixa snapshots oficiais recentes da ANP e do BCB de maneira atômica.
Se uma fonte estiver indisponível, preserve o cache validado e não substitua dados
reais por valores sintéticos.

Depois da preparação, execute novamente `train.py` e `build_product.py` para
publicar novas previsões no dashboard.

## Endpoints principais

```text
GET  /health
GET  /api/dashboard
GET  /sources
POST /data/sync
GET  /market/s10
GET  /market/features
GET  /forecast?horizon=7|14|30
GET  /models
GET  /models/leaderboard
GET  /models/weights
GET  /models/error-correlation
GET  /models/calibration
GET  /backtest
GET  /backtest/economic
POST /decision/simulate
GET  /time-machine?as_of=<ISO-8601>
GET  /research
```

## Testes e qualidade

Backend, dados e ML:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check atlas_s10 pipelines services tests
```

Frontend:

```powershell
cd apps\web
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
```

Última validação local: **16 testes passaram**, lint, typecheck e build de produção
concluídos com sucesso.

## Dados e causalidade

Fontes efetivamente usadas no produto atual:

- ANP: preço de revenda nacional do Diesel S10, distribuição e
  produtor/importador.
- Banco Central do Brasil: USD/BRL PTAX venda.
- U.S. EIA: Brent spot.

Cada observação normalizada possui:

```text
series_id, observation_date, available_at, ingested_at, value, unit,
source, revision, geography_type, geography_code, geography, metadata
```

`observation_date` e `available_at` não são tratados como sinônimos. O backtest
falha se um target ou driver tiver disponibilidade posterior à origem da previsão.
O protocolo detalhado está em `research/methodology.md`; o catálogo de fontes está
em `research/sources.yml`.

## Artefatos

- `artifacts/forecasts/latest.json`: forecast atual 7/14/30.
- `artifacts/forecasts/backtest_predictions.csv`: painel rolling-origin.
- `artifacts/models/registry.json`: model registry.
- `artifacts/models/lightgbm_h*.txt`: challengers LightGBM serializados.
- `artifacts/reports/leaderboard.csv`: métricas comuns.
- `artifacts/reports/backtest.html`: relatório estático completo.
- `artifacts/reports/diagnostics.json`: DM tests, correlações e governança.
- `artifacts/reports/economic_backtest.json`: contrafactual operacional.
- `data/gold/`: tabelas causais em CSV e Parquet.
- `data/atlas_s10.duckdb`: catálogo analítico local.

## Pesquisa

`research/papers.yml` contém 29 referências com evidência, inferência, limitação e
consequência de implementação. O VS-ePL-KRLS é exibido como experimental: o paper
foi revisado, mas nenhuma implementação licenciada dos autores foi localizada, e
uma aproximação não é apresentada como reprodução fiel.

## Limitações conhecidas

- A série nacional semanal ainda é curta para deep learning: 135 semanas.
- O backtest externo contém 24 origens por horizonte; testes estatísticos têm
  poder limitado.
- O lag histórico da revenda ANP usa premissa conservadora de oito dias.
- O lag de distribuição usa 14 dias assumidos e permanece experimental.
- A média nacional não é ponderada por volume vendido; a composição de postos
  varia ao longo do tempo.
- O backtest econômico não conhece descontos privados, frete, custo financeiro
  real, contratos ou capacidade operacional de uma empresa específica.
- A recomendação é suporte a procurement sob premissas informadas, não uma ordem
  financeira absoluta.

## Política de versionamento dos dados

Os aproximadamente 350 MB em `raw/` são mantidos localmente e ignorados pelo Git
para evitar inflar o repositório. Gold, artefatos pequenos e o snapshot do frontend
podem ser versionados para que a demo continue abrindo offline. Para publicar o
histórico bruto, prefira storage de objetos ou Git LFS e preserve hashes/proveniência.

