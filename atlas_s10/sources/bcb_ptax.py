"""Conector do Banco Central — PTAX USD/BRL (boletins de fechamento).

Baixa as cotações de fechamento via API OData do BCB numa janela recente. A taxa
de venda semanal é o driver cambial do modelo.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
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

PTAX_BASE_URL = (
    "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
    "CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,"
    "dataFinalCotacao=@dataFinalCotacao)"
)
PTAX_REQUIRED_KEYS = {"cotacaoCompra", "cotacaoVenda", "dataHoraCotacao", "tipoBoletim"}
PTAX_WINDOW_DAYS = 75


def ptax_url(start: date, end: date) -> str:
    """Build the BCB OData query for the USD closing bulletins in [start, end]."""
    select = "cotacaoCompra,cotacaoVenda,dataHoraCotacao,tipoBoletim"
    return (
        f"{PTAX_BASE_URL}?@moeda='USD'&@dataInicial='{start:%m-%d-%Y}'"
        f"&@dataFinalCotacao='{end:%m-%d-%Y}'&$top=10000&$format=json&$select={select}"
    )


def validate_ptax_json(path: Path) -> dict[str, Any]:
    """Validate the BCB OData payload and count official closing bulletins."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("value")
    if not isinstance(rows, list):
        raise ValueError("BCB response has no OData value array")
    closings = [row for row in rows if row.get("tipoBoletim") == "Fechamento"]
    if not closings or not all(PTAX_REQUIRED_KEYS.issubset(row) for row in closings):
        raise ValueError("BCB response has no valid PTAX closing rows")
    return {
        "rows": len(rows),
        "closing_rows": len(closings),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


class BcbPtaxConnector:
    """Recent BCB PTAX USD/BRL closing bulletins."""

    id = "bcb_ptax"
    source = "BCB"

    def fetch(self, today: date | None = None) -> FetchResult:
        today = today or date.today()
        start = today - timedelta(days=PTAX_WINDOW_DAYS)
        url = ptax_url(start, today)
        target = CACHE_DIR / "bcb" / f"ptax-usd-{start.isoformat()}_{today.isoformat()}.json"
        details = atomic_download(url, target, validate_ptax_json)
        return FetchResult("BCB", url, relative(target), now_iso(), details)

    def cached(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted((CACHE_DIR / "bcb").glob("ptax-usd-*.json")):
            rows.append({"source": "BCB", "path": relative(path), **validate_ptax_json(path)})
        return rows
