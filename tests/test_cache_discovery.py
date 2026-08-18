import json
from pathlib import Path

import pandas as pd
import pytest

from pipelines.prepare_data import (
    BRENT_COLUMNS,
    USD_COLUMNS,
    aggregate_national_weekly,
    discover_optional_retail_caches,
    discover_ptax_caches,
    load_external_weekly,
    merge_market,
    station_day_medians,
)


def _touch_all(directory: Path, names: list[str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).touch()


def _write_capture_sidecar(path: Path, captured_at: str) -> None:
    path.with_suffix(f"{path.suffix}.metadata.json").write_text(
        json.dumps(
            {
                "captured_at": captured_at,
                "provenance_basis": "test_fixture",
                "source_url": "https://example.test/ptax",
            }
        ),
        encoding="utf-8",
    )


def test_anp_cache_discovery_is_dynamic_deterministic_and_asof_safe(tmp_path: Path):
    cache_dir = tmp_path / "data" / "cache" / "anp"
    _touch_all(
        cache_dir,
        [
            "2026-07-diesel-gnv.csv",
            "2026-08-diesel-gnv.csv",
            "ultimas-4-semanas-diesel-gnv-2026-08-07.csv",
            "latest-4-weeks-diesel-gnv-2026-08-14.csv",
            "latest-4-weeks-diesel-gnv-2026-08-15.csv",
            "not-an-anp-cache.csv",
        ],
    )
    (cache_dir / "latest-4-weeks-diesel-gnv-2026-08-14.csv.metadata.json").write_text(
        json.dumps(
            {
                "published_at": "2026-08-14T14:04:00-03:00",
                "source_url": "https://example.test/anp.csv",
            }
        ),
        encoding="utf-8",
    )

    found = discover_optional_retail_caches(
        tmp_path,
        "2026-08-14T21:00:00Z",
    )

    assert [item["path"].name for item in found] == [
        "2026-07-diesel-gnv.csv",
        "ultimas-4-semanas-diesel-gnv-2026-08-07.csv",
        "latest-4-weeks-diesel-gnv-2026-08-14.csv",
    ]
    assert [item["published_on"] for item in found] == [
        None,
        "2026-08-07",
        "2026-08-14",
    ]
    assert found[-1]["published_at"] == "2026-08-14T17:04:00Z"


def test_anp_sidecar_published_after_asof_is_invisible(tmp_path: Path):
    cache_dir = tmp_path / "data" / "cache" / "anp"
    _touch_all(cache_dir, ["latest-4-weeks-diesel-gnv-2026-08-14.csv"])
    (cache_dir / "latest-4-weeks-diesel-gnv-2026-08-14.csv.metadata.json").write_text(
        json.dumps({"published_at": "2026-08-14T22:00:00Z"}),
        encoding="utf-8",
    )

    assert discover_optional_retail_caches(tmp_path, "2026-08-14T21:00:00Z") == []


def test_anp_station_day_overlap_uses_latest_vintage_once():
    target = pd.DataFrame(
        {
            "observation_date": [pd.Timestamp("2026-08-06")] * 2,
            "state_code": ["SP"] * 2,
            "municipality_name": ["SAO PAULO"] * 2,
            "station_id": ["12345678000199"] * 2,
            "station_name": ["POSTO TESTE"] * 2,
            "value": [6.10, 6.20],
            "source_file": ["older.csv", "newer.csv"],
            "source_priority": [2, 2],
            "source_published_on": [
                pd.Timestamp("2026-08-07"),
                pd.Timestamp("2026-08-14"),
            ],
            "source_published_at": [pd.NaT, pd.Timestamp("2026-08-14T17:04:00Z")],
        }
    )

    station_day, stats = station_day_medians(target)

    assert len(station_day) == 1
    assert station_day.loc[0, "value"] == 6.20
    assert station_day.loc[0, "source_file"] == "newer.csv"
    assert stats["snapshot_overlap_extra_rows_removed"] == 1


def _weekly_driver(columns: list[str], prefix: str) -> pd.DataFrame:
    values: dict[str, object] = {"semana_fim": pd.Timestamp("2026-08-09")}
    for column in columns[1:]:
        values[column] = 1 if column.endswith("observacoes") else 5.0
    return pd.DataFrame([values])


def test_exact_anp_sidecar_publication_becomes_target_available_at():
    station_day = pd.DataFrame(
        {
            "week_end": [pd.Timestamp("2026-08-09")],
            "observation_date": [pd.Timestamp("2026-08-09")],
            "value": [6.91],
            "station_id": ["12345678000199"],
            "municipality_id": ["SP|SAO PAULO"],
            "state_code": ["SP"],
            "source_published_at": [pd.Timestamp("2026-08-14T17:04:00Z")],
        }
    )
    weekly, excluded = aggregate_national_weekly(station_day)
    assert excluded.empty

    market, _ = merge_market(
        weekly,
        _weekly_driver(USD_COLUMNS, "usd"),
        _weekly_driver(BRENT_COLUMNS, "brent"),
        "2026-08-14T17:10:00Z",
        anp_lag_days=8,
        usd_lag_days=1,
        brent_lag_days=3,
    )

    assert market.loc[0, "anp_availability_basis"] == "exact_snapshot_publication"
    assert market.loc[0, "anp_available_at"] == pd.Timestamp("2026-08-14T17:04:00Z")


def test_incomplete_anp_publication_coverage_keeps_conservative_lag():
    station_day = pd.DataFrame(
        {
            "week_end": [pd.Timestamp("2026-08-09")] * 2,
            "observation_date": [pd.Timestamp("2026-08-09")] * 2,
            "value": [6.90, 6.92],
            "station_id": ["12345678000199", "98765432000199"],
            "municipality_id": ["SP|SAO PAULO", "RJ|RIO DE JANEIRO"],
            "state_code": ["SP", "RJ"],
            "source_published_at": [pd.Timestamp("2026-08-14T17:04:00Z"), pd.NaT],
        }
    )
    weekly, _ = aggregate_national_weekly(station_day)
    market, _ = merge_market(
        weekly,
        _weekly_driver(USD_COLUMNS, "usd"),
        _weekly_driver(BRENT_COLUMNS, "brent"),
        "2026-08-14T17:10:00Z",
        anp_lag_days=8,
        usd_lag_days=1,
        brent_lag_days=3,
    )

    assert market.loc[0, "anp_availability_basis"] == "conservative_lag_proxy"
    assert market.loc[0, "anp_available_at"] == pd.Timestamp("2026-08-18T02:59:59Z")


def test_ptax_cache_discovery_excludes_future_query_vintage(tmp_path: Path):
    cache_dir = tmp_path / "data" / "cache" / "bcb"
    _touch_all(
        cache_dir,
        [
            "ptax-usd-2026-07-01_2026-08-13.json",
            "ptax-usd-2026-08-01_2026-08-14.json",
            "ptax-usd-2026-08-02_2026-08-15.json",
            "ptax-usd-invalid.json",
        ],
    )
    _write_capture_sidecar(
        cache_dir / "ptax-usd-2026-07-01_2026-08-13.json",
        "2026-08-13T20:00:00Z",
    )
    _write_capture_sidecar(
        cache_dir / "ptax-usd-2026-08-01_2026-08-14.json",
        "2026-08-14T20:00:00Z",
    )

    found = discover_ptax_caches(tmp_path, "2026-08-14T21:00:00Z")

    assert [item["path"].name for item in found] == [
        "ptax-usd-2026-07-01_2026-08-13.json",
        "ptax-usd-2026-08-01_2026-08-14.json",
    ]
    assert [item["vintage_on"] for item in found] == ["2026-08-13", "2026-08-14"]


def test_ptax_cache_captured_after_asof_is_invisible(tmp_path: Path):
    path = tmp_path / "data/cache/bcb/ptax-usd-2026-08-01_2026-08-14.json"
    path.parent.mkdir(parents=True)
    path.touch()
    _write_capture_sidecar(path, "2026-08-14T22:00:00Z")

    assert discover_ptax_caches(tmp_path, "2026-08-14T21:00:00Z") == []


def test_ptax_cache_without_capture_sidecar_is_rejected(tmp_path: Path):
    path = tmp_path / "data/cache/bcb/ptax-usd-2026-08-01_2026-08-14.json"
    path.parent.mkdir(parents=True)
    path.touch()

    with pytest.raises(ValueError, match="requires metadata sidecar"):
        discover_ptax_caches(tmp_path, "2026-08-14T21:00:00Z")


def _ptax_row(day: str, sell: float) -> dict[str, object]:
    return {
        "cotacaoCompra": sell - 0.01,
        "cotacaoVenda": sell,
        "dataHoraCotacao": f"{day} 13:10:00.000",
        "tipoBoletim": "Fechamento",
    }


def _write_ptax(
    path: Path,
    rows: list[dict[str, object]],
    captured_at: str,
) -> None:
    path.write_text(
        json.dumps({"@odata.context": "test", "value": rows}),
        encoding="utf-8",
    )
    _write_capture_sidecar(path, captured_at)


def test_ptax_overlaps_use_latest_eligible_vintage_without_duplicate_day(
    tmp_path: Path,
):
    external_dir = tmp_path / "processed" / "external"
    external_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "data": ["2026-07-31"],
            "usd_brl": [4.90],
            "usd_brl_compra": [4.89],
        }
    ).to_csv(external_dir / "usd_brl_diario.csv", index=False)
    pd.DataFrame(
        [["2026-08-02", 70.0, 69.0, 71.0, 70.0, 1.0, 1, 0.0]],
        columns=BRENT_COLUMNS,
    ).to_csv(external_dir / "brent_semanal.csv", index=False)

    cache_dir = tmp_path / "data" / "cache" / "bcb"
    cache_dir.mkdir(parents=True)
    _write_ptax(
        cache_dir / "ptax-usd-2026-08-01_2026-08-07.json",
        [_ptax_row("2026-08-06", 5.10)],
        "2026-08-07T20:00:00Z",
    )
    _write_ptax(
        cache_dir / "ptax-usd-2026-08-06_2026-08-14.json",
        [
            _ptax_row("2026-08-06", 5.20),
            _ptax_row("2026-08-07", 5.30),
            {
                **_ptax_row("2026-08-14", 5.40),
                "dataHoraCotacao": "2026-08-14 19:00:00.000",
            },
        ],
        "2026-08-14T20:00:00Z",
    )
    _write_ptax(
        cache_dir / "ptax-usd-2026-08-07_2026-08-15.json",
        [_ptax_row("2026-08-07", 9.99)],
        "2026-08-15T20:00:00Z",
    )

    usd, _, provenance = load_external_weekly(
        tmp_path,
        "2026-08-14T21:00:00Z",
    )

    week = usd.loc[usd["semana_fim"].eq(pd.Timestamp("2026-08-09"))].iloc[0]
    assert week["usd_brl_observacoes"] == 2
    assert week["usd_brl_media"] == 5.25
    assert week["usd_brl_ultimo"] == 5.30
    bcb_inputs = [
        item for item in provenance if item.get("snapshot_kind") == "official_bcb_odata_cache"
    ]
    assert [item["vintage_on"] for item in bcb_inputs] == ["2026-08-07", "2026-08-14"]
    assert bcb_inputs[-1]["future_closing_bulletins_excluded"] == 1
    assert provenance[0]["overlap_conflicting_dates"] == 1


def test_eia_canonical_daily_cache_replaces_partial_legacy_week(tmp_path: Path):
    external_dir = tmp_path / "processed" / "external"
    external_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "data": ["2026-08-07"],
            "usd_brl": [5.10],
            "usd_brl_compra": [5.09],
        }
    ).to_csv(external_dir / "usd_brl_diario.csv", index=False)
    pd.DataFrame(
        [["2026-08-09", 88.90, 88.90, 88.90, 88.90, None, 1, 0.0]],
        columns=BRENT_COLUMNS,
    ).to_csv(external_dir / "brent_semanal.csv", index=False)

    eia_dir = tmp_path / "data" / "cache" / "eia"
    eia_dir.mkdir(parents=True)
    values = [88.90, 86.47, 86.65, 89.65, 87.62]
    pd.DataFrame(
        {
            "period": pd.date_range("2026-08-03", periods=5, freq="D").strftime("%Y-%m-%d"),
            "series": ["RBRTE"] * 5,
            "value": values,
            "units": ["$/BBL"] * 5,
            "series_description": ["Europe Brent Spot Price FOB"] * 5,
            "duoarea": ["ZEU"] * 5,
            "area_name": ["NA"] * 5,
            "product": ["EPCBRENT"] * 5,
            "product_name": ["UK Brent Crude Oil"] * 5,
            "process": ["PF4"] * 5,
            "process_name": ["Spot Price FOB"] * 5,
            "retrieved_at": ["2026-08-14T20:00:00Z"] * 5,
            "vintage_id": ["test-vintage"] * 5,
        }
    ).to_csv(eia_dir / "spot-prices-daily.csv", index=False)

    _, brent, provenance = load_external_weekly(tmp_path, "2026-08-14T21:00:00Z")

    week = brent.loc[brent["semana_fim"].eq(pd.Timestamp("2026-08-09"))].iloc[0]
    assert week["brent_observacoes"] == 5
    assert week["brent_media"] == pytest.approx(sum(values) / len(values))
    assert week["brent_ultimo"] == pytest.approx(87.62)
    assert any(
        item.get("snapshot_kind") == "official_eia_api_or_xls_canonical_daily"
        for item in provenance
    )

    _, before_vintage, before_provenance = load_external_weekly(
        tmp_path, "2026-08-14T19:00:00Z"
    )
    fallback = before_vintage.loc[
        before_vintage["semana_fim"].eq(pd.Timestamp("2026-08-09"))
    ].iloc[0]
    assert fallback["brent_observacoes"] == 1
    assert not any(
        item.get("snapshot_kind") == "official_eia_api_or_xls_canonical_daily"
        for item in before_provenance
    )
