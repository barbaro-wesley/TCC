"""Score a frozen Atlas forecast against a newly published ANP release."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from atlas_s10.release_evaluation import (  # noqa: E402
    build_release_evaluation,
    write_release_evaluation,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--frozen-forecast", type=Path, required=True)
    parser.add_argument("--market", type=Path, default=ROOT / "data/gold/market_weekly.csv")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/reports/release_evaluation.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_release_evaluation(
        summary_path=args.summary,
        frozen_forecast_path=args.frozen_forecast,
        market_path=args.market,
    )
    path = write_release_evaluation(payload, args.output)
    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(path.relative_to(ROOT)),
                "operational_scores": len(payload["operational_scores"]),
                "has_provisional_official_score": payload[
                    "provisional_official_summary_score"
                ]
                is not None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
