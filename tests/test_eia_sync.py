from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from pipelines.sync_eia import (
    EIAClient,
    EIAConfigurationError,
    EIARequestError,
    import_eia_xls_snapshot,
    load_canonical_cache,
    load_eia_xls_daily,
    sync_eia_spot_prices,
)

ROOT = Path(__file__).resolve().parents[1]
DUMMY_KEY = "unit-test-eia-key-never-real"


class FakeResponse:
    def __init__(self, payload: dict):
        self.body = json.dumps(payload).encode("utf-8")

    def read(self, _limit: int = -1) -> bytes:
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def api_row(period: str, value: str, series: str = "RBRTE") -> dict[str, str]:
    return {
        "period": period,
        "duoarea": "ZEU",
        "area-name": "NA",
        "product": "EPCBRENT",
        "product-name": "UK Brent Crude Oil",
        "process": "PF4",
        "process-name": "Spot Price FOB",
        "series": series,
        "series-description": "Europe Brent Spot Price FOB (Dollars per Barrel)",
        "value": value,
        "units": "$/BBL",
    }


def fake_opener(rows: list[dict[str, str]], captured: list[dict[str, list[str]]] | None = None):
    def open_request(request, timeout):
        assert timeout > 0
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
        if captured is not None:
            captured.append(query)
        offset = int(query["offset"][0])
        length = int(query["length"][0])
        start = query["start"][0]
        end = query["end"][0]
        requested = set(query["facets[series][]"])
        selected = [
            row
            for row in rows
            if start <= row["period"] <= end and row["series"] in requested
        ]
        payload = {
            "response": {
                "total": str(len(selected)),
                "dateFormat": "YYYY-MM-DD",
                "frequency": "daily",
                "data": selected[offset : offset + length],
            },
            # The live service echoes this field; persistence must redact it.
            "request": {"params": {"api_key": DUMMY_KEY}},
            "apiVersion": "2.1.13",
        }
        return FakeResponse(payload)

    return open_request


def test_client_requires_environment_key(monkeypatch):
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    with pytest.raises(EIAConfigurationError, match="EIA_API_KEY"):
        EIAClient(opener=fake_opener([]))


@pytest.mark.parametrize(
    "base_url",
    [
        "https://attacker.example/v2",
        "https://api.eia.gov.attacker.example/v2",
        "https://api.eia.gov:444/v2",
        "http://api.eia.gov/v2",
        "https://api.eia.gov@attacker.example/v2",
    ],
)
def test_client_rejects_non_official_production_hosts(monkeypatch, base_url):
    monkeypatch.setenv("EIA_API_KEY", DUMMY_KEY)
    with pytest.raises(EIAConfigurationError, match="restricted|credentials"):
        EIAClient(base_url=base_url, opener=fake_opener([]))


def test_loopback_requires_explicit_test_mode_and_injected_transport(monkeypatch):
    monkeypatch.setenv("EIA_API_KEY", DUMMY_KEY)
    loopback = "http://127.0.0.1:8765/v2"

    with pytest.raises(EIAConfigurationError, match="test-only"):
        EIAClient(base_url=loopback, opener=fake_opener([]))
    with pytest.raises(EIAConfigurationError, match="injected transport"):
        EIAClient(base_url=loopback, allow_loopback_for_testing=True)

    client = EIAClient(
        base_url=loopback,
        opener=fake_opener([]),
        allow_loopback_for_testing=True,
    )
    assert client.base_url == loopback


def test_client_paginates_validates_and_redacts(monkeypatch):
    monkeypatch.setenv("EIA_API_KEY", DUMMY_KEY)
    captured: list[dict[str, list[str]]] = []
    rows = [
        api_row("2026-08-06", "89.65"),
        api_row("2026-08-07", "87.62"),
        api_row("2026-08-10", "92.74"),
    ]
    client = EIAClient(opener=fake_opener(rows, captured))
    result = client.fetch_daily_spot_prices(
        series="RBRTE", start="2026-08-06", end="2026-08-10", page_size=2
    )

    assert [row["value"] for row in result.records] == ["89.65", "87.62", "92.74"]
    assert [page.offset for page in result.pages] == [0, 2]
    assert captured[0]["api_key"] == [DUMMY_KEY]
    assert DUMMY_KEY not in repr(client)
    assert DUMMY_KEY not in json.dumps([page.payload for page in result.pages])
    assert result.pages[0].payload["request"]["params"]["api_key"] == "[REDACTED]"


def test_request_error_never_exposes_key(monkeypatch):
    monkeypatch.setenv("EIA_API_KEY", DUMMY_KEY)

    def fail(request, timeout):
        raise urllib.error.URLError(f"failed URL {request.full_url}")

    client = EIAClient(opener=fail)
    with pytest.raises(EIARequestError) as captured:
        client.fetch_daily_spot_prices(
            series="RBRTE", start="2026-08-06", end="2026-08-07"
        )
    assert DUMMY_KEY not in str(captured.value)


def test_incremental_sync_merges_revision_and_persists_sanitized_vintages(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("EIA_API_KEY", DUMMY_KEY)
    first = EIAClient(
        opener=fake_opener(
            [api_row("2026-08-06", "89.65"), api_row("2026-08-07", "87.62")]
        )
    )
    sync_eia_spot_prices(
        root=tmp_path,
        start="2026-08-06",
        end="2026-08-07",
        retrieved_at=datetime(2026, 8, 8, 12, tzinfo=UTC),
        client=first,
    )

    second = EIAClient(
        opener=fake_opener(
            [
                api_row("2026-08-06", "89.65"),
                api_row("2026-08-07", "88.00"),
                api_row("2026-08-10", "92.74"),
            ]
        )
    )
    result = sync_eia_spot_prices(
        root=tmp_path,
        end="2026-08-10",
        revision_lookback_days=1,
        retrieved_at=datetime(2026, 8, 11, 12, tzinfo=UTC),
        client=second,
    )

    rows = load_canonical_cache(tmp_path / "data/cache/eia/spot-prices-daily.csv")
    assert [(row["period"], row["value"]) for row in rows] == [
        ("2026-08-06", "89.65"),
        ("2026-08-07", "88"),
        ("2026-08-10", "92.74"),
    ]
    assert result["merge"]["inserted_rows"] == 1
    assert result["merge"]["revised_rows"] == 1
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert DUMMY_KEY not in path.read_text(encoding="utf-8")


def test_official_rbrte_xls_parser_contract():
    path = ROOT / "data/cache/eia/RBRTEd-2026-08-14.xls"
    if not path.exists():
        pytest.skip("official EIA XLS snapshot is not present")

    daily, quality = load_eia_xls_daily(path)
    assert quality["series"] == "RBRTE"
    assert quality["release_date"] == "2026-08-12"
    assert quality["observation_end"] == "2026-08-11"
    assert quality["rows"] > 9_900
    latest = daily.set_index("data")["brent_usd_barril"]
    assert latest.loc[pd.Timestamp("2026-08-06")] == pytest.approx(89.65)
    assert latest.loc[pd.Timestamp("2026-08-07")] == pytest.approx(87.62)
    assert latest.loc[pd.Timestamp("2026-08-10")] == pytest.approx(92.74)
    assert latest.loc[pd.Timestamp("2026-08-11")] == pytest.approx(93.26)


def test_official_xls_import_builds_canonical_cache(tmp_path):
    source = ROOT / "data/cache/eia/RBRTEd-2026-08-14.xls"
    if not source.exists():
        pytest.skip("official EIA XLS snapshot is not present")
    local_source = tmp_path / "data/cache/eia/RBRTEd-2026-08-14.xls"
    local_source.parent.mkdir(parents=True)
    shutil.copy2(source, local_source)

    result = import_eia_xls_snapshot(
        local_source,
        root=tmp_path,
        retrieved_at=datetime(2026, 8, 14, 22, 59, 7, tzinfo=UTC),
    )

    rows = load_canonical_cache(tmp_path / "data/cache/eia/spot-prices-daily.csv")
    assert result["status"] == "imported"
    assert result["cache"]["series"]["RBRTE"]["end"] == "2026-08-11"
    assert len(rows) > 9_900
    assert rows[-1]["value"] == "93.26"
