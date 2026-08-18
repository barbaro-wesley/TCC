"""Atualiza os pequenos caches oficiais usados pela demo do Atlas S10.

A lógica dos conectores agora vive em ``atlas_s10.sources``. Este módulo mantém a
interface histórica — ``validate_anp_csv``, ``validate_ptax_json``,
``sync_sources`` e ``cached_source_status`` — usada pela API e pelos testes, além
da CLI. Rede é opt-in; sem rede, valida e reporta os snapshots locais em vez de
inventar dados.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from atlas_s10.sources import CONNECTORS  # noqa: E402
from atlas_s10.sources.anp_revenda import ANP_LATEST_URL, validate_anp_csv  # noqa: E402,F401
from atlas_s10.sources.bcb_ptax import ptax_url, validate_ptax_json  # noqa: E402,F401


def cached_source_status() -> list[dict[str, Any]]:
    """Return the validated local cache inventory for offline operation."""
    results: list[dict[str, Any]] = []
    for connector in CONNECTORS:
        results.extend(connector.cached())
    return results


def sync_sources(today: date | None = None) -> dict[str, Any]:
    """Download current official snapshots (one per connector) atomically."""
    today = today or date.today()
    official = [connector.fetch(today).to_dict() for connector in CONNECTORS]
    return {"status": "synced", "official_sources": official}


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
