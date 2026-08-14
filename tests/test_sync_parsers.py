from pathlib import Path

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
