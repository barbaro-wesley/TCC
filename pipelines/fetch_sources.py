"""Orquestrador dos conectores de busca de dados ("agentes de busca de dados").

Executa cada conector oficial registrado em ``atlas_s10.sources.CONNECTORS``.

* Com ``--network`` (ou ``ALLOW_NETWORK_SYNC=1``): baixa e valida os snapshots
  recentes de cada fonte, de forma atômica.
* Sem rede: apenas reporta o inventário do cache local validado.

Uma falha em uma fonte **não derruba as demais** e nenhum dado é inventado: a
falha é reportada e o processo termina com código de saída não-zero para que o
CI a torne visível.
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


def run(allow_network: bool, today: date | None = None) -> dict[str, Any]:
    """Fetch (when online) and inventory every registered connector."""
    today = today or date.today()
    fetched: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []

    for connector in CONNECTORS:
        if allow_network:
            try:
                fetched.append(connector.fetch(today).to_dict())
            except Exception as exc:  # noqa: BLE001 - report the failure, never invent data
                failures.append(
                    {
                        "source": connector.source,
                        "id": connector.id,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        try:
            inventory.extend(connector.cached())
        except Exception as exc:  # noqa: BLE001 - a missing/invalid cache is reportable, not fatal here
            failures.append(
                {"source": connector.source, "id": connector.id, "error": f"cache: {exc}"}
            )

    if not allow_network:
        status = "cache_only"
    elif failures:
        status = "partial"
    else:
        status = "synced"

    return {
        "status": status,
        "allow_network": allow_network,
        "connectors": [connector.id for connector in CONNECTORS],
        "fetched": fetched,
        "failures": failures,
        "cached_inventory": inventory,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--network",
        action="store_true",
        help="Permite downloads oficiais; sem isso, valida apenas o cache local.",
    )
    args = parser.parse_args()
    allow_network = args.network or os.getenv("ALLOW_NETWORK_SYNC", "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    payload = run(allow_network)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload["status"] == "partial":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
