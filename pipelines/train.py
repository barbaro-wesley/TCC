"""Run the full causal backtest and persist product artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from atlas_s10.config import ensure_directories  # noqa: E402
from atlas_s10.data import load_market_frame  # noqa: E402
from atlas_s10.features import build_features  # noqa: E402
from atlas_s10.modeling import (  # noqa: E402
    BacktestConfig,
    build_forecasts,
    build_registry,
    economic_backtest,
    evaluate_backtest,
    run_backtest,
    save_artifacts,
    save_latest_lightgbm_models,
)
from atlas_s10.reporting import generate_reports  # noqa: E402


def main() -> None:
    ensure_directories()
    market = load_market_frame()
    features = build_features(market)
    config = BacktestConfig()
    predictions = run_backtest(features, config)
    metrics = evaluate_backtest(predictions, features)
    forecasts = build_forecasts(features, predictions, metrics, config)
    economic = economic_backtest(predictions)
    registry = build_registry(metrics, forecasts)
    paths = save_artifacts(predictions, metrics, forecasts, economic, registry, config)
    paths.update(save_latest_lightgbm_models(features, config))
    paths.update(generate_reports(predictions, metrics, forecasts, economic))
    champions = {item["horizon_days"]: item["champion"] for item in forecasts}
    print(
        json.dumps(
            {
                "status": "ok",
                "market_rows": len(market),
                "backtest_rows": len(predictions),
                "champions": champions,
                "artifacts": {key: str(path.relative_to(ROOT)) for key, path in paths.items()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
