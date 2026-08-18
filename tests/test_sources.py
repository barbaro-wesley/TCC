"""Testes de contrato dos conectores de busca de dados (offline, sem rede).

Validam os parsers contra os snapshots oficiais já versionados em data/cache/.
O teste de download ao vivo (egress para os sites do governo) roda no CI, onde
a rede é aberta — ver .github/workflows/atualizacao-semanal.yml.
"""

from datetime import date
from pathlib import Path

from atlas_s10.sources import CONNECTORS
from atlas_s10.sources.anp_produtor_importador import PRODUCER_SHEET, PRODUCER_URL
from atlas_s10.sources.anp_revenda import AnpRevendaConnector, validate_anp_csv
from atlas_s10.sources.bcb_ptax import BcbPtaxConnector, ptax_url, validate_ptax_json
from atlas_s10.sources.ibge_ipca import IPCA_URL

ROOT = Path(__file__).resolve().parents[1]
ANP_FIXTURE = ROOT / "data" / "cache" / "anp" / "ultimas-4-semanas-diesel-gnv-2026-08-07.csv"
BCB_FIXTURE = ROOT / "data" / "cache" / "bcb" / "ptax-usd-2026-07-01_2026-08-13.json"


def test_registry_exposes_current_connectors():
    ids = {connector.id for connector in CONNECTORS}
    assert {"anp_revenda", "bcb_ptax", "anp_produtor_importador", "ibge_ipca"}.issubset(ids)
    assert isinstance(AnpRevendaConnector(), object)
    assert isinstance(BcbPtaxConnector(), object)


def test_ipca_connector_targets_sidra_table_7060():
    assert IPCA_URL.startswith("https://apisidra.ibge.gov.br/values/t/7060/")
    assert "/v/63/" in IPCA_URL  # variação mensal
    assert "/c315/all" in IPCA_URL


def test_producer_connector_targets_official_xls():
    assert PRODUCER_URL.endswith("precos-medios-ponderados-semanais-2013.xls")
    assert PRODUCER_URL.startswith("https://www.gov.br/anp/")
    assert PRODUCER_SHEET == "Preços Produtor e Importador"


def test_anp_validator_on_cached_fixture():
    result = validate_anp_csv(ANP_FIXTURE)
    assert result["columns"] == 16
    assert result["bytes"] > 50_000
    assert len(result["sha256"]) == 64


def test_bcb_validator_on_cached_fixture():
    result = validate_ptax_json(BCB_FIXTURE)
    assert result["closing_rows"] >= 20
    assert result["rows"] > result["closing_rows"]
    assert len(result["sha256"]) == 64


def test_ptax_url_uses_bcb_month_day_year_format():
    url = ptax_url(date(2026, 6, 1), date(2026, 8, 15))
    assert "@dataInicial='06-01-2026'" in url
    assert "@dataFinalCotacao='08-15-2026'" in url
    assert "$format=json" in url


def test_cached_inventory_is_offline_and_provenanced():
    for connector in CONNECTORS:
        for row in connector.cached():
            assert row["source"] in {"ANP", "BCB"}
            assert len(row["sha256"]) == 64
            assert row["path"].startswith("data/cache/")
