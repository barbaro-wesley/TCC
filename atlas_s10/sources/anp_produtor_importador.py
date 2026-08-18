"""Conector da ANP — produtor/importador de Diesel S10 (preços médios ponderados).

Baixa a planilha oficial "Preços Médios Ponderados Semanais a partir de 2013" e
valida o contrato mínimo antes de publicar o snapshot. É a etapa anterior da
cadeia (produtor/importador), usada como driver de custo com defasagem causal.
"""

from __future__ import annotations

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

PRODUCER_URL = (
    "https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/"
    "ppidp/precos-medios-ponderados-semanais-2013.xls"
)
PRODUCER_SHEET = "Preços Produtor e Importador"
LAG_NOTE = "doze dias"
MIN_COLUMNS = 9


def validate_producer_xls(path: Path) -> dict[str, Any]:
    """Validate the producer/importer workbook contract (sheet, columns, lag note).

    Mirrors the guards in ``pipelines.prepare_data.load_anp_cost_drivers`` so a
    silent layout change on the ANP side fails loudly here instead of downstream.
    Pandas is imported lazily to keep the connector registry importable without it.
    """
    import pandas as pd

    book = pd.ExcelFile(path, engine="xlrd")
    if PRODUCER_SHEET not in book.sheet_names:
        raise ValueError(
            f"Producer/importer workbook missing sheet '{PRODUCER_SHEET}'; found {book.sheet_names}"
        )
    raw = book.parse(PRODUCER_SHEET, header=None)
    if raw.shape[1] < MIN_COLUMNS:
        raise ValueError(
            f"Producer/importer workbook has {raw.shape[1]} columns; expected >= {MIN_COLUMNS}"
        )
    cells = [str(value) for value in raw.astype("string").stack().dropna().tolist()]
    if not any(LAG_NOTE in cell.casefold() for cell in cells):
        raise ValueError("Producer/importer workbook no longer contains its 12-day lag note")
    updated_label = next((cell for cell in cells if "atualizado em" in cell.casefold()), None)
    return {
        "sheet": PRODUCER_SHEET,
        "columns": int(raw.shape[1]),
        "workbook_updated_label": updated_label,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


class AnpProdutorImportadorConnector:
    """ANP weighted-average producer/importer Diesel S10 workbook (since 2013)."""

    id = "anp_produtor_importador"
    source = "ANP"
    url = PRODUCER_URL

    def fetch(self, today: date | None = None) -> FetchResult:
        today = today or date.today()
        target = CACHE_DIR / "anp" / f"precos-medios-ponderados-semanais-{today.isoformat()}.xls"
        details = atomic_download(self.url, target, validate_producer_xls)
        return FetchResult("ANP", self.url, relative(target), now_iso(), details)

    def cached(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted((CACHE_DIR / "anp").glob("precos-medios-ponderados-semanais-*.xls")):
            rows.append({"source": "ANP", "path": relative(path), **validate_producer_xls(path)})
        return rows
