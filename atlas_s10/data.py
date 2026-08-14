"""Load, normalize and audit local official-source snapshots.

The primary target is the station-level ANP Diesel S10 sample aggregated weekly
for Brazil.  Every normalized value carries an observation timestamp and a
conservative availability timestamp.  Backtests query the latter, never the
former alone.  Legacy RS paths remain only as a fallback for old notebooks.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from atlas_s10.config import DATA_DIR, PROCESSED_DIR, ROOT

TARGET_PATH = PROCESSED_DIR / "anp" / "revenda" / "diesel_s10_rs_semanal.csv"
TARGET_OBSERVATIONS_PATH = (
    PROCESSED_DIR / "anp" / "revenda" / "diesel_s10_rs_observacoes.csv"
)
USD_PATH = PROCESSED_DIR / "external" / "usd_brl_semanal.csv"
BRENT_PATH = PROCESSED_DIR / "external" / "brent_semanal.csv"
GOLD_MARKET_PATH = DATA_DIR / "gold" / "market_weekly.csv"
GOLD_OBSERVATIONS_PATH = DATA_DIR / "gold" / "normalized_observations.csv"


@dataclass(frozen=True)
class SourceStatus:
    id: str
    name: str
    institution: str
    status: str
    rows: int
    observation_start: str
    observation_end: str
    latest_observation: str
    freshness_days: int
    frequency: str
    unit: str
    geography: str
    publication_lag: str
    acquisition: str
    source_url: str
    local_path: str
    sha256: str
    warning: str | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_iso(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def load_market_frame() -> pd.DataFrame:
    """Return the complete-week market frame used by every model."""
    if GOLD_MARKET_PATH.exists():
        frame = pd.read_csv(
            GOLD_MARKET_PATH,
            parse_dates=[
                "observation_date",
                "semana_inicio",
                "semana_fim",
                "available_at",
                "anp_available_at",
                "usd_brl_available_at",
                "brent_available_at",
                "distribuicao_s10_available_at_asof",
                "produtor_importador_s10_available_at_asof",
            ],
        )
        frame = frame.loc[frame["is_complete_week"].astype(bool)].copy()
        return frame.sort_values("semana_fim").reset_index(drop=True)

    missing = [path for path in (TARGET_PATH, USD_PATH, BRENT_PATH) if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Snapshots ausentes: {', '.join(map(str, missing))}")

    target = pd.read_csv(TARGET_PATH, parse_dates=["semana_fim"])
    usd = pd.read_csv(USD_PATH, parse_dates=["semana_fim"])
    brent = pd.read_csv(BRENT_PATH, parse_dates=["semana_fim"])

    # A raw semester may end mid-week. It is useful for inspection, but cannot
    # become a completed weekly target in training or the product headline.
    if TARGET_OBSERVATIONS_PATH.exists():
        observations = pd.read_csv(
            TARGET_OBSERVATIONS_PATH, usecols=["data_coleta"], parse_dates=["data_coleta"]
        )
        last_collection = observations["data_coleta"].max().normalize()
        target = target.loc[target["semana_fim"].le(last_collection)].copy()

    target = target.loc[~target["semana_sem_dados"].astype(bool)].copy()
    frame = target.merge(usd, on="semana_fim", how="left", validate="one_to_one")
    frame = frame.merge(brent, on="semana_fim", how="left", validate="one_to_one")
    frame = frame.sort_values("semana_fim").reset_index(drop=True)
    frame["available_at"] = (
        frame["semana_fim"] + pd.Timedelta(days=4, hours=12)
    ).dt.tz_localize("America/Sao_Paulo").dt.tz_convert("UTC")
    frame["geography_type"] = "state"
    frame["geography_code"] = "RS"
    frame["is_complete_week"] = True
    return frame


def normalized_observations(frame: pd.DataFrame) -> pd.DataFrame:
    """Build the long causal contract required by snapshot(as_of)."""
    if GOLD_OBSERVATIONS_PATH.exists():
        result = pd.read_csv(
            GOLD_OBSERVATIONS_PATH,
            parse_dates=["observation_date", "available_at", "ingested_at"],
        )
        return result.sort_values(["available_at", "series_id"]).reset_index(drop=True)

    ingested_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    definitions = [
        ("anp.diesel_s10.revenda.rs.mean", "preco_medio", "BRL/L", "ANP", 4),
        ("bcb.usd_brl.ptax.sell.weekly_last", "usd_brl_ultimo", "BRL/USD", "BCB", 0),
        ("eia.brent.rbrte.weekly_last", "brent_ultimo", "USD/bbl", "EIA", 0),
    ]
    parts: list[pd.DataFrame] = []
    for series_id, column, unit, source, lag_days in definitions:
        part = pd.DataFrame(
            {
                "series_id": series_id,
                "observation_date": frame["semana_fim"],
                "available_at": frame["semana_fim"] + pd.Timedelta(days=lag_days, hours=12),
                "ingested_at": ingested_at,
                "value": frame[column],
                "unit": unit,
                "source": source,
                "revision": 0,
                "geography_type": "state" if source == "ANP" else "global",
                "geography_code": "RS" if source == "ANP" else "GLOBAL",
                "geography": "Rio Grande do Sul" if source == "ANP" else "Global",
                "metadata": json.dumps(
                    {
                        "aggregation": "weekly",
                        "week_convention": "W-SUN",
                        "availability_assumption": (
                            "Thursday 12:00 America/Sao_Paulo after reference week"
                            if source == "ANP"
                            else "Known by forecast publication time"
                        ),
                    },
                    ensure_ascii=False,
                ),
            }
        )
        part["available_at"] = (
            pd.to_datetime(part["available_at"])
            .dt.tz_localize("America/Sao_Paulo")
            .dt.tz_convert("UTC")
        )
        parts.append(part)
    result = pd.concat(parts, ignore_index=True).dropna(subset=["value"])
    result["observation_date"] = pd.to_datetime(result["observation_date"])
    return result.sort_values(["available_at", "series_id"]).reset_index(drop=True)


def snapshot(observations: pd.DataFrame, as_of: str | pd.Timestamp) -> pd.DataFrame:
    """Return only values actually available at ``as_of``.

    Revisions are resolved by taking the last ingested version available at the
    timestamp.  The explicit assertion makes future-publication leakage fatal.
    """
    cutoff = pd.Timestamp(as_of)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    available = observations.loc[observations["available_at"].le(cutoff)].copy()
    if not available.empty and available["available_at"].gt(cutoff).any():
        raise AssertionError("Future publication leakage detected")
    return (
        available.sort_values(["series_id", "observation_date", "revision", "ingested_at"])
        .drop_duplicates(["series_id", "observation_date", "geography_code"], keep="last")
        .reset_index(drop=True)
    )


def quality_checks(frame: pd.DataFrame, observations: pd.DataFrame) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(check: str, passed: bool, detail: str, severity: str = "critical") -> None:
        checks.append(
            {
                "check": check,
                "status": "pass" if passed else "fail",
                "severity": severity,
                "detail": detail,
            }
        )

    add("weekly_duplicates", not frame["semana_fim"].duplicated().any(), "Uma linha por semana")
    expected = pd.date_range(frame["semana_fim"].min(), frame["semana_fim"].max(), freq="W-SUN")
    add("weekly_gaps", len(expected) == len(frame), f"{len(expected) - len(frame)} gaps")
    add("valid_prices", frame["preco_medio"].between(1, 20).all(), "Faixa plausível R$ 1–20/L")
    add("valid_usd", frame["usd_brl_ultimo"].between(1, 15).all(), "Faixa plausível R$ 1–15/USD")
    add("valid_brent", frame["brent_ultimo"].between(5, 250).all(), "Faixa plausível US$ 5–250/bbl")
    add(
        "future_availability",
        not observations["available_at"].isna().any(),
        "Todas as observações possuem available_at",
    )
    add(
        "required_contract",
        {
            "series_id", "observation_date", "available_at", "ingested_at", "value",
            "unit", "source", "revision", "geography", "metadata",
        }.issubset(observations.columns),
        "Contrato causal completo",
    )
    abrupt = frame["preco_medio"].pct_change().abs().gt(0.12).sum()
    add("abrupt_change", abrupt == 0, f"{int(abrupt)} variações semanais acima de 12%", "warning")
    return checks


def source_statuses(frame: pd.DataFrame) -> list[dict[str, Any]]:
    today = pd.Timestamp.now(tz="America/Sao_Paulo").normalize().tz_localize(None)
    specs = [
        {
            "id": "anp_s10_br",
            "name": "Diesel S10 — revenda nacional",
            "institution": "Agência Nacional do Petróleo",
            "path": GOLD_MARKET_PATH if GOLD_MARKET_PATH.exists() else TARGET_PATH,
            "date": frame["semana_fim"],
            "rows": int(frame["numero_observacoes"].sum()),
            "frequency": "Semanal",
            "unit": "BRL/L",
            "geography": "Brasil — 27 UFs",
            "publication_lag": "8 dias (premissa conservadora)",
            "acquisition": "CSV público semestral; cache local",
            "source_url": "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/serie-historica-de-precos-de-combustiveis",
        },
        {
            "id": "bcb_usd_brl",
            "name": "USD/BRL PTAX venda",
            "institution": "Banco Central do Brasil",
            "path": USD_PATH,
            "date": frame.loc[frame["usd_brl_ultimo"].notna(), "semana_fim"],
            "rows": int(pd.read_csv(PROCESSED_DIR / "external" / "usd_brl_diario.csv").shape[0]),
            "frequency": "Diária → semanal",
            "unit": "BRL/USD",
            "geography": "Brasil",
            "publication_lag": "Mesmo dia útil",
            "acquisition": "API OData PTAX; cache local",
            "source_url": "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/",
        },
        {
            "id": "eia_brent",
            "name": "Europe Brent Spot Price FOB",
            "institution": "U.S. Energy Information Administration",
            "path": BRENT_PATH,
            "date": pd.read_csv(BRENT_PATH, parse_dates=["semana_fim"])["semana_fim"],
            "rows": int(pd.read_csv(PROCESSED_DIR / "external" / "brent_diario.csv").shape[0]),
            "frequency": "Diária → semanal",
            "unit": "USD/bbl",
            "geography": "Global",
            "publication_lag": "Próximo dia útil (premissa)",
            "acquisition": "Planilha oficial RBRTE; cache local",
            "source_url": "https://www.eia.gov/dnav/pet/hist/RBRTEd.htm",
        },
    ]
    results: list[dict[str, Any]] = []
    for spec in specs:
        spec = dict(spec)
        dates = pd.to_datetime(spec.pop("date"))
        source_path = spec.pop("path")
        latest = dates.max().normalize()
        freshness = max(0, int((today - latest).days))
        status = "healthy" if freshness <= 14 else "warning" if freshness <= 45 else "stale"
        warning = None if status == "healthy" else f"Snapshot local está {freshness} dias atrás do relógio do sistema"
        item = SourceStatus(
            **spec,
            status=status,
            observation_start=dates.min().date().isoformat(),
            observation_end=latest.date().isoformat(),
            latest_observation=latest.date().isoformat(),
            freshness_days=freshness,
            local_path=str(source_path.relative_to(ROOT)).replace("\\", "/"),
            sha256=_sha256(source_path),
            warning=warning,
        )
        row = asdict(item)
        row.pop("path", None)
        results.append(row)
    return results
