"""Build the API/frontend materialized view from audited artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from atlas_s10.product import build_dashboard, write_dashboard_snapshot  # noqa: E402


def main() -> None:
    payload = build_dashboard()
    path = write_dashboard_snapshot(payload)
    print(
        json.dumps(
            {
                "status": "ok",
                "path": str(path.relative_to(ROOT)),
                "geography": payload["meta"]["geography"],
                "forecast_horizons": [item["horizon"] for item in payload["forecasts"]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

