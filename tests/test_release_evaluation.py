from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

from atlas_s10.release_evaluation import (
    build_release_evaluation,
    load_anp_national_s10_summary,
    score_frozen_forecast,
)


def _summary_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "BRASIL"
    for _ in range(9):
        sheet.append([])
    sheet.append(
        [
            "DATA INICIAL",
            "DATA FINAL",
            "BRASIL",
            "PRODUTO",
            "NÚMERO DE POSTOS PESQUISADOS",
            "UNIDADE DE MEDIDA",
            "PREÇO MÉDIO REVENDA",
            "DESVIO PADRÃO REVENDA",
            "PREÇO MÍNIMO REVENDA",
            "PREÇO MÁXIMO REVENDA",
            "COEF DE VARIAÇÃO REVENDA",
        ]
    )
    sheet.append(
        [
            datetime(2026, 8, 9),
            datetime(2026, 8, 15),
            "BRASIL",
            "OLEO DIESEL S10",
            3139,
            "R$/l",
            6.91,
            0.438,
            5.77,
            9.27,
            0.063,
        ]
    )
    workbook.save(path)


def _forecast(target: str, horizon: int, point: float = 6.98) -> dict[str, object]:
    return {
        "origin_date": "2026-08-02",
        "target_date": target,
        "horizon_days": horizon,
        "current_price": 7.0,
        "point": point,
        "p10": 6.8,
        "p90": 7.2,
    }


def test_load_anp_national_summary_maps_official_calendar(tmp_path: Path):
    path = tmp_path / "summary.xlsx"
    _summary_workbook(path)

    summary = load_anp_national_s10_summary(path)

    assert summary["period_start"] == "2026-08-09"
    assert summary["period_end"] == "2026-08-15"
    assert summary["atlas_w_sun_target_date"] == "2026-08-16"
    assert summary["price"] == 6.91
    assert summary["station_count"] == 3139


def test_score_frozen_forecast_reports_interval_and_direction():
    score = score_frozen_forecast(
        _forecast("2026-08-09", 7),
        6.97,
        status="definitive_operational_target",
    )

    assert score["interval_contains_actual"] is True
    assert score["direction_match"] is True
    assert score["absolute_error"] == pytest.approx(0.01)


def test_build_release_evaluation_keeps_targets_separate(tmp_path: Path):
    import json

    summary_path = tmp_path / "summary.xlsx"
    _summary_workbook(summary_path)
    forecast_path = tmp_path / "latest.json"
    forecast_path.write_text(
        json.dumps(
            [
                _forecast("2026-08-09", 7, 6.98),
                _forecast("2026-08-16", 14, 6.99),
            ]
        ),
        encoding="utf-8",
    )
    market_path = tmp_path / "market.csv"
    pd.DataFrame({"semana_fim": ["2026-08-09"], "preco_medio": [6.97]}).to_csv(
        market_path, index=False
    )

    payload = build_release_evaluation(
        summary_path=summary_path,
        frozen_forecast_path=forecast_path,
        market_path=market_path,
        generated_at=datetime(2026, 8, 14, 20, tzinfo=UTC),
    )

    assert payload["operational_scores"][0]["actual"] == 6.97
    assert payload["provisional_official_summary_score"]["actual"] == 6.91
    assert payload["provisional_official_summary_score"]["target_date"] == "2026-08-16"
