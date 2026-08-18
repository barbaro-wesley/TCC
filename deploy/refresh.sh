#!/usr/bin/env bash
# Executado no HOST (VM) pelo systemd timer. Roda o ciclo num container one-shot.
# A API (container `api`) continua no ar e passa a servir os dados novos automaticamente.
set -euo pipefail

# Raiz do repositório (este script está em <repo>/deploy/).
cd "$(dirname "$(readlink -f "$0")")/.."

echo "==> $(date -u +%FT%TZ) refresh iniciando"
docker compose run --rm pipeline
echo "==> $(date -u +%FT%TZ) refresh concluído"

# (Opcional) manter o fallback do painel (Vercel) fresco versionando o snapshot:
# git add apps/web/public/demo-data.json data/gold artifacts \
#   && git commit -m "chore(dados): refresh automático da VM" \
#   && git push
