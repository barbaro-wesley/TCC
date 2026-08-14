import json

import pandas as pd

from atlas_s10.config import DATA_DIR
from atlas_s10.data import load_market_frame, normalized_observations, quality_checks


def test_national_gold_contract_and_quality():
    market = load_market_frame()
    observations = normalized_observations(market)
    report = json.loads((DATA_DIR / "gold" / "quality_report.json").read_text(encoding="utf-8"))
    assert len(market) == report["target"]["weekly_rows"] == 135
    assert market["semana_fim"].max() == pd.Timestamp("2026-08-02")
    assert len(observations) == report["normalized_observations"]["rows"] == 1419
    assert market["geography_code"].eq("BR").all()
    assert market["unit"].eq("BRL/L").all()
    assert market["semana_fim"].diff().dropna().eq(pd.Timedelta(days=7)).all()
    assert not any(check["status"] == "fail" for check in quality_checks(market, observations))
    assert report["status"] == "pass"
    assert report["target"]["states"] == 27
    assert report["cache_extensions"]["anp"]["files_used"] == 2
    assert report["cache_extensions"]["bcb"]["files_used"] == 1
