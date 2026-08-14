"""Project paths and reproducible runtime settings."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RAW_DIR = ROOT / "raw"
PROCESSED_DIR = ROOT / "processed"
FINAL_DIR = ROOT / "final"
ARTIFACTS_DIR = ROOT / "artifacts"
REPORTS_DIR = ARTIFACTS_DIR / "reports"
FORECASTS_DIR = ARTIFACTS_DIR / "forecasts"
MODELS_DIR = ARTIFACTS_DIR / "models"
WEB_PUBLIC_DIR = ROOT / "apps" / "web" / "public"


def fast_demo() -> bool:
    return os.getenv("FAST_DEMO", "1").strip().lower() not in {"0", "false", "no"}


def ensure_directories() -> None:
    for path in (
        DATA_DIR / "cache",
        DATA_DIR / "gold",
        REPORTS_DIR,
        FORECASTS_DIR,
        MODELS_DIR,
        WEB_PUBLIC_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)

