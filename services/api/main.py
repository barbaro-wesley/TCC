"""FastAPI surface for the Atlas S10 product and audit artifacts."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pandas as pd
import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

from atlas_s10.config import ARTIFACTS_DIR, DATA_DIR, ROOT
from atlas_s10.data import load_market_frame, normalized_observations, snapshot
from atlas_s10.decision import ProcurementScenario, recommend
from atlas_s10.features import build_features
from atlas_s10.product import build_dashboard
from pipelines.sync_data import cached_source_status, sync_sources

app = FastAPI(
    title="Atlas S10 API",
    version="0.1.0",
    description="Causal Diesel S10 procurement intelligence for Brazil.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class ScenarioRequest(BaseModel):
    horizon_days: Literal[7, 14, 30] = 30
    current_stock_liters: float = Field(18_000, ge=0)
    tank_capacity_liters: float = Field(100_000, gt=0)
    daily_consumption_liters: float = Field(2_500, ge=0)
    planning_horizon_days: int = Field(30, ge=1, le=180)
    safety_stock_days: float = Field(5, ge=0, le=60)
    supplier_lead_days: float = Field(3, ge=0, le=60)
    risk_tolerance: Literal["conservative", "moderate", "aggressive"] = "moderate"

    @model_validator(mode="after")
    def stock_fits_tank(self) -> ScenarioRequest:
        if self.current_stock_liters > self.tank_capacity_liters:
            raise ValueError("current_stock_liters cannot exceed tank_capacity_liters")
        return self


def _json(path: Path):
    if not path.exists():
        raise HTTPException(status_code=503, detail=f"Artifact missing: {path.name}; run training")
    return json.loads(path.read_text(encoding="utf-8"))


def _records(frame: pd.DataFrame) -> list[dict]:
    clean = frame.copy()
    for column in clean.columns:
        if pd.api.types.is_datetime64_any_dtype(clean[column]):
            clean[column] = clean[column].astype(str)
    clean = clean.astype(object).where(pd.notna(clean), None)
    return clean.to_dict(orient="records")


@app.get("/health")
def health() -> dict:
    required = [
        DATA_DIR / "gold" / "market_weekly.csv",
        ARTIFACTS_DIR / "forecasts" / "latest.json",
        ROOT / "apps" / "web" / "public" / "demo-data.json",
    ]
    return {
        "status": "healthy" if all(path.exists() for path in required) else "degraded",
        "service": "atlas-s10-api",
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "artifacts": {path.name: path.exists() for path in required},
    }


@app.get("/api/dashboard")
@app.get("/dashboard")
def dashboard() -> dict:
    return build_dashboard()


@app.get("/sources")
def sources() -> dict:
    dashboard_data = build_dashboard()
    return {"sources": dashboard_data["sources"], "quality_checks": dashboard_data["qualityChecks"]}


@app.post("/data/sync")
def data_sync() -> dict:
    allow_network = os.getenv("ALLOW_NETWORK_SYNC", "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if allow_network:
        try:
            return sync_sources()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Official source sync failed: {exc}") from exc
    return {
        "status": "cache_only",
        "message": "Network sync is disabled; validated official cache is available. Set ALLOW_NETWORK_SYNC=1 to refresh it, then run the data/train pipelines.",
        "allow_network_sync": False,
        "official_sources": cached_source_status(),
    }


@app.get("/market/s10")
def market_s10(limit: int = Query(52, ge=1, le=520)) -> dict:
    market = load_market_frame().tail(limit)
    columns = [
        "semana_fim",
        "available_at",
        "preco_medio",
        "preco_minimo",
        "preco_maximo",
        "numero_postos",
        "numero_municipios",
        "numero_ufs",
        "usd_brl_ultimo",
        "brent_ultimo",
    ]
    return {
        "geography": {"type": "country", "code": "BR", "name": "Brasil"},
        "unit": "BRL/L",
        "rows": _records(market[columns]),
    }


@app.get("/market/features")
def market_features(limit: int = Query(20, ge=1, le=520)) -> dict:
    features = build_features(load_market_frame()).tail(limit)
    return {"rows": _records(features)}


def _validate_horizon(horizon: int) -> int:
    if horizon not in {7, 14, 30}:
        raise HTTPException(status_code=422, detail="horizon must be 7, 14 or 30")
    return horizon


@app.get("/forecast")
def forecast(horizon: int = 7) -> dict:
    horizon = _validate_horizon(horizon)
    forecasts = _json(ARTIFACTS_DIR / "forecasts" / "latest.json")
    result = dict(next(item for item in forecasts if item["horizon_days"] == horizon))
    calendar_days = int(
        (pd.Timestamp(result["target_date"]) - pd.Timestamp(result["origin_date"])).days
    )
    weeks = int(result["horizon_weeks"])
    result["horizon_contract"] = {
        "id": horizon,
        "weeks": weeks,
        "calendar_days": calendar_days,
        "label": f"{weeks} semana{'s' if weeks != 1 else ''} ({calendar_days} dias)",
        "legacy_id": horizon if horizon != calendar_days else None,
    }
    return result


@app.get("/models")
def models() -> dict:
    return {"models": _json(ARTIFACTS_DIR / "models" / "registry.json")}


@app.get("/models/leaderboard")
def leaderboard(horizon: int | None = None) -> dict:
    frame = pd.read_csv(ARTIFACTS_DIR / "reports" / "leaderboard.csv")
    if horizon is not None:
        horizon = _validate_horizon(horizon)
        frame = frame.loc[frame["horizon_days"].eq(horizon)]
    return {"rows": _records(frame)}


@app.get("/models/weights")
def model_weights() -> dict:
    forecasts = _json(ARTIFACTS_DIR / "forecasts" / "latest.json")
    return {
        "rows": [
            {
                "horizon_days": item["horizon_days"],
                "weights": item["weights"],
                "agreement": item["agreement"],
                "operational_model": item["operational_model"],
            }
            for item in forecasts
        ]
    }


@app.get("/models/error-correlation")
def error_correlation() -> dict:
    frame = pd.read_csv(ARTIFACTS_DIR / "forecasts" / "backtest_predictions.csv")
    models = [
        "naive",
        "arima",
        "sarima",
        "sarimax",
        "lightgbm",
        "lightgbm_price_only",
        "inverse_mase",
    ]
    rows = []
    for horizon, group in frame.groupby("horizon_days"):
        errors = pd.DataFrame({model: group[model] - group["actual"] for model in models})
        rows.append({"horizon_days": int(horizon), "matrix": errors.corr().round(4).to_dict()})
    return {"rows": rows}


@app.get("/models/calibration")
def calibration() -> dict:
    dashboard_data = build_dashboard()
    metrics = pd.read_csv(ARTIFACTS_DIR / "reports" / "leaderboard.csv")
    probability = metrics.loc[metrics["model"].eq("probability_layer")]
    return {"curve_7d": dashboard_data["backtest"]["calibration"], "metrics": _records(probability)}


@app.get("/backtest")
def backtest(horizon: int = 7) -> dict:
    horizon = _validate_horizon(horizon)
    frame = pd.read_csv(ARTIFACTS_DIR / "forecasts" / "backtest_predictions.csv")
    return {"rows": _records(frame.loc[frame["horizon_days"].eq(horizon)])}


@app.get("/backtest/economic")
def backtest_economic() -> dict:
    return _json(ARTIFACTS_DIR / "reports" / "economic_backtest.json")


@app.post("/decision/simulate")
def decision_simulate(payload: ScenarioRequest) -> dict:
    forecasts = _json(ARTIFACTS_DIR / "forecasts" / "latest.json")
    forecast_row = next(item for item in forecasts if item["horizon_days"] == payload.horizon_days)
    scenario = ProcurementScenario(
        current_stock_liters=payload.current_stock_liters,
        tank_capacity_liters=payload.tank_capacity_liters,
        daily_consumption_liters=payload.daily_consumption_liters,
        planning_horizon_days=payload.planning_horizon_days,
        safety_stock_days=payload.safety_stock_days,
        supplier_lead_days=payload.supplier_lead_days,
        risk_tolerance=payload.risk_tolerance,
    )
    return recommend(forecast_row, scenario)


@app.get("/time-machine")
def time_machine(as_of: str) -> dict:
    try:
        cutoff = pd.Timestamp(as_of)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Invalid as_of timestamp") from exc
    observations = normalized_observations(load_market_frame())
    known = snapshot(observations, cutoff)
    if known.empty:
        raise HTTPException(status_code=404, detail="No observations available at this timestamp")
    target = known.loc[known["series_id"].str.startswith("anp.diesel_s10")]
    latest_date = target["observation_date"].max() if not target.empty else None
    return {
        "as_of": str(cutoff),
        "known_observations": int(len(known)),
        "series": sorted(known["series_id"].unique().tolist()),
        "latest_target_observation": str(latest_date) if latest_date is not None else None,
        "rows": _records(known.tail(25)),
        "note": "This endpoint reconstructs data visibility; model replay is read from realized backtest artifacts in /api/dashboard.",
    }


@app.get("/research")
def research() -> dict:
    papers = yaml.safe_load((ROOT / "research" / "papers.yml").read_text(encoding="utf-8"))
    sources_data = yaml.safe_load((ROOT / "research" / "sources.yml").read_text(encoding="utf-8"))
    return {**papers, **sources_data}
