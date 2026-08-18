#!/usr/bin/env bash
# Ciclo completo DENTRO do container `pipeline` (compose): coleta -> prepara -> treina -> publica.
# A API lê os artefatos a cada request, então os dados ficam frescos sem reiniciar nada.
set -euo pipefail

echo "==> [1/5] sync_data (ANP + BCB)"
python -m pipelines.sync_data --network

echo "==> [2/5] sync_eia (Brent RBRTE)"
python -m pipelines.sync_eia --network --series RBRTE

echo "==> [3/5] prepare_data (usa raw/ + caches)"
python -m pipelines.prepare_data

echo "==> [4/5] train (backtest + forecasts + artefatos)"
python -m pipelines.train

echo "==> [5/5] build_product (atualiza demo-data.json)"
python -m pipelines.build_product

echo "==> OK: ciclo concluído."
