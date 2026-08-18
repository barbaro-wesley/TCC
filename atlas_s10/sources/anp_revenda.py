"""Conector da ANP — revenda de Diesel S10 (snapshot rolling das últimas semanas).

Baixa o CSV oficial "últimas 4 semanas" de combustíveis. É a fonte do preço-alvo
para a atualização incremental; o histórico completo (semestral) é tratado no
rebuild total.
"""

from __future__ import annotations

import csv
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

ANP_LATEST_URL = (
    "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/"
    "arquivos/shpc/qus/ultimas-4-semanas-diesel-gnv.csv"
)
ANP_REQUIRED_COLUMNS = {"Produto", "Data da Coleta", "Valor de Venda", "Unidade de Medida"}
MIN_BYTES = 50_000


def validate_anp_csv(path: Path) -> dict[str, Any]:
    """Validate the official Diesel/GNV CSV contract without loading it all."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=";")
        header = next(reader)
        first = next(reader, None)
    if not ANP_REQUIRED_COLUMNS.issubset(header) or first is None:
        raise ValueError("ANP response does not match the expected retail CSV contract")
    if path.stat().st_size < MIN_BYTES:
        raise ValueError("ANP response is unexpectedly small")
    return {"columns": len(header), "bytes": path.stat().st_size, "sha256": sha256(path)}


class AnpRevendaConnector:
    """Rolling four-week ANP retail Diesel S10 snapshot."""

    id = "anp_revenda"
    source = "ANP"
    url = ANP_LATEST_URL

    def fetch(self, today: date | None = None) -> FetchResult:
        today = today or date.today()
        target = CACHE_DIR / "anp" / f"latest-4-weeks-diesel-gnv-{today.isoformat()}.csv"
        details = atomic_download(self.url, target, validate_anp_csv)
        return FetchResult("ANP", self.url, relative(target), now_iso(), details)

    def cached(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted((CACHE_DIR / "anp").glob("*.csv")):
            rows.append({"source": "ANP", "path": relative(path), **validate_anp_csv(path)})
        return rows
