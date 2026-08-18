import json
from datetime import date
from pathlib import Path

from pipelines import sync_data
from pipelines.sync_data import validate_anp_csv, validate_ptax_json

ROOT = Path(__file__).resolve().parents[1]


def test_cached_anp_parser_contract():
    path = ROOT / "data" / "cache" / "anp" / "ultimas-4-semanas-diesel-gnv-2026-08-07.csv"
    result = validate_anp_csv(path)
    assert result["columns"] == 16
    assert len(result["sha256"]) == 64


def test_cached_bcb_parser_closing_rows():
    path = ROOT / "data" / "cache" / "bcb" / "ptax-usd-2026-07-01_2026-08-13.json"
    result = validate_ptax_json(path)
    assert result["closing_rows"] >= 20
    assert result["rows"] > result["closing_rows"]


def test_sync_writes_atomic_ptax_capture_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_data, "ROOT", tmp_path)
    monkeypatch.setattr(sync_data, "CACHE_DIR", tmp_path / "data" / "cache")

    def fake_download(url, target, validator):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture", encoding="utf-8")
        return {"bytes": 7, "sha256": "a" * 64}

    monkeypatch.setattr(sync_data, "_download", fake_download)
    result = sync_data.sync_sources(date(2026, 8, 14))

    metadata_path = (
        tmp_path
        / "data/cache/bcb/ptax-usd-2026-05-31_2026-08-14.json.metadata.json"
    )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["captured_at"].endswith("Z")
    assert metadata["provenance_basis"] == "sync_completion_time_utc"
    assert "api_key" not in metadata["source_url"].casefold()
    assert result["official_sources"][1]["metadata_path"].endswith(".metadata.json")
