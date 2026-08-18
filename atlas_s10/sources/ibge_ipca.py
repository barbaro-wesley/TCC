"""Conector do IBGE/SIDRA — IPCA (tabela 7060, variação mensal).

Baixa a série mensal de variação do IPCA (variável 63) para o Brasil, com a
classificação `c315` completa (índice geral, grupos, itens e subitens). Itens de
interesse do Atlas: óleo diesel (5104003), combustíveis (5104), transportes
(grupo 5) e o índice geral — a seleção fina desses itens acontece na integração
de feature; aqui o snapshot é a tabela inteira, validado como resposta SIDRA
íntegra. A API do SIDRA é pública e não exige chave.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from atlas_s10.sources.base import (
    CACHE_DIR,
    FetchResult,
    atomic_download,
    now_iso,
    relative,
    sha256,
)

# Tabela 7060 (IPCA), variável 63 (variação mensal %), Brasil, classificação c315 completa.
IPCA_URL = "https://apisidra.ibge.gov.br/values/t/7060/n1/all/v/63/p/all/c315/all"


def validate_sidra_json(path: Path) -> dict[str, Any]:
    """Validate the SIDRA table 7060 payload (header row + at least one data row)."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or len(payload) < 2:
        raise ValueError("SIDRA response is not a non-empty values array")
    header = payload[0]
    if not isinstance(header, dict) or "V" not in header:
        raise ValueError("SIDRA response header does not match the table 7060 contract")
    data_rows = payload[1:]
    if not any(isinstance(row, dict) and row.get("V") not in (None, "") for row in data_rows):
        raise ValueError("SIDRA response has no data rows with values")
    return {
        "rows": len(data_rows),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


class IbgeIpcaConnector:
    """IBGE SIDRA IPCA table 7060 (monthly variation, full c315 classification)."""

    id = "ibge_ipca"
    source = "IBGE"
    url = IPCA_URL

    def fetch(self, today: date | None = None) -> FetchResult:
        today = today or date.today()
        target = CACHE_DIR / "ibge" / f"ipca-7060-{today.isoformat()}.json"
        details = atomic_download(self.url, target, validate_sidra_json)
        return FetchResult("IBGE", self.url, relative(target), now_iso(), details)

    def cached(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted((CACHE_DIR / "ibge").glob("ipca-7060-*.json")):
            rows.append({"source": "IBGE", "path": relative(path), **validate_sidra_json(path)})
        return rows
