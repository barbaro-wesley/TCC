"""Refresh the small official-source caches used by the Atlas S10 demo.

Network access is opt-in.  With networking disabled the command verifies and
reports the existing reproducible snapshots instead of silently inventing data.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import tempfile
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CACHE_DIR = ROOT / "data" / "cache"
ANP_LATEST_URL = (
    "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/"
    "arquivos/shpc/qus/ultimas-4-semanas-diesel-gnv.csv"
)
PTAX_BASE_URL = (
    "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
    "CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,"
    "dataFinalCotacao=@dataFinalCotacao)"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_anp_csv(path: Path) -> dict[str, Any]:
    """Validate the official Diesel/GNV CSV contract without loading it all."""

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=";")
        header = next(reader)
        first = next(reader, None)
    required = {"Produto", "Data da Coleta", "Valor de Venda", "Unidade de Medida"}
    if not required.issubset(header) or first is None:
        raise ValueError("ANP response does not match the expected retail CSV contract")
    if path.stat().st_size < 50_000:
        raise ValueError("ANP response is unexpectedly small")
    return {"columns": len(header), "bytes": path.stat().st_size, "sha256": _sha256(path)}


def validate_ptax_json(path: Path) -> dict[str, Any]:
    """Validate BCB OData payload and count official closing bulletins."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("value")
    if not isinstance(rows, list):
        raise ValueError("BCB response has no OData value array")
    closings = [row for row in rows if row.get("tipoBoletim") == "Fechamento"]
    required = {"cotacaoCompra", "cotacaoVenda", "dataHoraCotacao", "tipoBoletim"}
    if not closings or not all(required.issubset(row) for row in closings):
        raise ValueError("BCB response has no valid PTAX closing rows")
    return {
        "rows": len(rows),
        "closing_rows": len(closings),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _download(url: str, target: Path, validator) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Atlas-S10/0.1 (+local research demo)"},
    )
    temp_path: Path | None = None
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=target.parent, prefix=f".{target.name}.", delete=False
            ) as handle:
                temp_path = Path(handle.name)
                while chunk := response.read(1024 * 1024):
                    handle.write(chunk)
        details = validator(temp_path)
        temp_path.replace(target)
        return details
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _ptax_url(start: date, end: date) -> str:
    select = "cotacaoCompra,cotacaoVenda,dataHoraCotacao,tipoBoletim"
    return (
        f"{PTAX_BASE_URL}?@moeda='USD'&@dataInicial='{start:%m-%d-%Y}'"
        f"&@dataFinalCotacao='{end:%m-%d-%Y}'&$top=10000&$format=json&$select={select}"
    )


def cached_source_status() -> list[dict[str, Any]]:
    """Return validated local cache inventory for offline operation."""

    results: list[dict[str, Any]] = []
    for path in sorted((CACHE_DIR / "anp").glob("*.csv")):
        results.append({"source": "ANP", "path": str(path.relative_to(ROOT)), **validate_anp_csv(path)})
    for path in sorted((CACHE_DIR / "bcb").glob("ptax-usd-*.json")):
        results.append({"source": "BCB", "path": str(path.relative_to(ROOT)), **validate_ptax_json(path)})
    return results


def sync_sources(today: date | None = None) -> dict[str, Any]:
    """Download current ANP and BCB official snapshots atomically."""

    today = today or date.today()
    anp_path = CACHE_DIR / "anp" / f"latest-4-weeks-diesel-gnv-{today.isoformat()}.csv"
    ptax_start = today - timedelta(days=75)
    ptax_path = CACHE_DIR / "bcb" / f"ptax-usd-{ptax_start.isoformat()}_{today.isoformat()}.json"
    anp = _download(ANP_LATEST_URL, anp_path, validate_anp_csv)
    bcb = _download(_ptax_url(ptax_start, today), ptax_path, validate_ptax_json)
    return {
        "status": "synced",
        "official_sources": [
            {"source": "ANP", "url": ANP_LATEST_URL, "path": str(anp_path.relative_to(ROOT)), **anp},
            {"source": "BCB", "url": _ptax_url(ptax_start, today), "path": str(ptax_path.relative_to(ROOT)), **bcb},
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--network",
        action="store_true",
        help="Allow official HTTP downloads; otherwise validate cached snapshots only.",
    )
    args = parser.parse_args()
    allow_network = args.network or os.getenv("ALLOW_NETWORK_SYNC", "0").lower() in {
        "1",
        "true",
        "yes",
    }
    payload = sync_sources() if allow_network else {
        "status": "cache_only",
        "official_sources": cached_source_status(),
        "message": "Network disabled; verified reproducible local official snapshots.",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
