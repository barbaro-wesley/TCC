"""Compose model artifacts into the stable API/frontend product contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from atlas_s10.config import ARTIFACTS_DIR, DATA_DIR, ROOT
from atlas_s10.data import load_market_frame
from atlas_s10.decision import ProcurementScenario, recommend
from atlas_s10.features import build_features, latest_driver_snapshot
from atlas_s10.modeling import MODEL_LABELS


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _round(value: Any, digits: int = 4) -> float:
    return round(float(value), digits)


def _model_family(model: str) -> str:
    if model in {"arima", "sarima", "sarimax"}:
        return "Estatístico"
    if model.startswith("lightgbm"):
        return "ML tabular"
    if model in {"simple_average", "inverse_mase"}:
        return "Ensemble"
    return "Baseline"


def _sources_for_ui(market: pd.DataFrame) -> list[dict[str, Any]]:
    quality = _load_json(DATA_DIR / "gold" / "quality_report.json")
    rows: list[dict[str, Any]] = []
    today = pd.Timestamp.now(tz="America/Sao_Paulo").normalize().tz_localize(None)
    inputs = quality.get("inputs", [])
    usd_input = next(
        item
        for item in inputs
        if item.get("snapshot_kind") == "normalized_historical_daily"
    )
    eia_input = next(
        (
            item
            for item in inputs
            if item.get("snapshot_kind") == "official_eia_api_or_xls_canonical_daily"
        ),
        next(item for item in inputs if "brent" in item.get("path", "").casefold()),
    )
    specs = [
        (
            "anp",
            "Diesel S10 — revenda nacional",
            "ANP",
            quality["target"]["target_rows"],
            quality["target"]["first_collection"],
            quality["target"]["last_collection"],
            quality["target"]["last_complete_week"],
            "8 dias (premissa conservadora)",
            94,
            "BRL/L",
            "Semanal",
        ),
        (
            "bcb",
            "USD/BRL PTAX venda",
            "Banco Central do Brasil",
            usd_input["combined_daily_rows"],
            usd_input["observation_start"],
            usd_input["combined_observation_end"],
            usd_input["combined_observation_end"],
            "1 dia (premissa conservadora)",
            97,
            "BRL/USD",
            "Diária → semanal",
        ),
        (
            "eia",
            "Europe Brent Spot Price FOB",
            "U.S. EIA",
            eia_input["rows"],
            eia_input["observation_start"],
            eia_input["observation_end"],
            eia_input["observation_end"],
            "3 dias (premissa conservadora)",
            99,
            "USD/bbl",
            "Diária → semanal",
        ),
    ]
    for source_id, name, institution, count, start, end, latest, lag, score, unit, frequency in specs:
        freshness = max(0, int((today - pd.Timestamp(latest)).days))
        status = "healthy" if freshness <= 14 else "warning" if freshness <= 45 else "stale"
        warning = None if status == "healthy" else f"Snapshot local; {freshness} dias desde a última observação."
        rows.append(
            {
                "id": source_id,
                "name": name,
                "institution": institution,
                "status": status,
                "rows": int(count),
                "coverage": f"{start} — {end}",
                "latest": latest,
                "lag": lag,
                "quality": score,
                "unit": unit,
                "frequency": frequency,
                "warning": warning,
            }
        )
    rows.extend(
        [
            {
                "id": "anp-dist",
                "name": "Preço de distribuição S10",
                "institution": "ANP",
                "status": "stale",
                "rows": 305,
                "coverage": "2020-08-23 — 2026-06-27",
                "latest": "2026-06-27",
                "lag": "14 dias (premissa não verificada)",
                "quality": 96,
                "unit": "BRL/L",
                "frequency": "Semanal",
                "warning": "Feature causal ativa, mas o snapshot está defasado e o lag é assumido.",
            },
            {
                "id": "anp-producer",
                "name": "Produtor/importador S10",
                "institution": "ANP",
                "status": "healthy",
                "rows": 709,
                "coverage": "2012-12-31 — 2026-08-02",
                "latest": "2026-08-02",
                "lag": "12 dias declarados",
                "quality": 96,
                "unit": "BRL/L",
                "frequency": "Semanal",
                "warning": "Feature causal ativa via as-of; a estimativa oficial de publicação é 12 dias.",
            },
            {
                "id": "ibge",
                "name": "IPCA — óleo diesel",
                "institution": "IBGE SIDRA",
                "status": "warning",
                "rows": 78,
                "coverage": "2020-01 — 2026-06",
                "latest": "2026-06-30",
                "lag": "Mensal",
                "quality": 91,
                "unit": "%",
                "frequency": "Mensal",
                "warning": "Catalogado, ainda fora do champion desta versão.",
            },
        ]
    )
    return rows


def _research_for_ui() -> list[dict[str, Any]]:
    path = ROOT / "research" / "papers.yml"
    if not path.exists():
        return []
    papers = yaml.safe_load(path.read_text(encoding="utf-8"))["papers"]
    result: list[dict[str, Any]] = []
    for paper in papers[:15]:
        assessment = paper.get("assessment", {})
        verification = str(paper.get("verification", ""))
        confidence = "Alta" if paper["id"] in {"R1", "R10"} else "Média"
        if "not verified" in verification.lower() or paper["id"] in {"R6", "R14"}:
            confidence = "Exploratória"
        result.append(
            {
                "id": paper["id"],
                "title": paper["title"],
                "target": paper.get("target", "Forecasting"),
                "why": assessment.get("inference", paper.get("relevant_findings", "")),
                "usage": paper.get("how_we_use_it", assessment.get("implementation_consequence", "")),
                "confidence": confidence,
                "evidence": assessment.get("evidence", ""),
                "limitation": assessment.get("limitation", paper.get("limitations", "")),
                "href": paper.get("url") or paper.get("doi"),
            }
        )
    return result


def _calibration_rows(backtest: pd.DataFrame) -> list[dict[str, Any]]:
    subset = backtest.loc[backtest["horizon_days"].eq(7)].copy()
    event = subset["actual"].gt(subset["current_price"] * 1.005)
    bins = pd.cut(
        subset["probability_relevant_up"],
        bins=[0, 0.2, 0.4, 0.6, 0.8, 1],
        include_lowest=True,
        labels=["0–20%", "20–40%", "40–60%", "60–80%", "80–100%"],
    )
    rows: list[dict[str, Any]] = []
    for label in bins.cat.categories:
        mask = bins.eq(label)
        if mask.any():
            rows.append(
                {
                    "bucket": str(label),
                    "predicted": _round(subset.loc[mask, "probability_relevant_up"].mean() * 100, 1),
                    "observed": _round(event.loc[mask].mean() * 100, 1),
                }
            )
    return rows


def _time_machine(backtest: pd.DataFrame) -> list[dict[str, Any]]:
    subset = backtest.loc[backtest["horizon_days"].eq(7)].tail(8)
    rows: list[dict[str, Any]] = []
    for _, row in subset.iterrows():
        probability = float(row["probability_relevant_up"])
        fraction = 0.60 if probability >= 0.65 else 0.35 if probability >= 0.5 else 0.15
        weights = json.loads(row["ensemble_weights"])
        current = float(row["current_price"])
        actual = float(row["actual"])
        suggested = 70_000 * fraction
        saving = suggested * (actual - current)
        recommendation = (
            "ANTECIPAR PARCIALMENTE"
            if fraction == 0.60
            else "COMPRAR PARCIALMENTE"
            if fraction == 0.35
            else "MANTER COMPRA TÁTICA"
        )
        rows.append(
            {
                "date": pd.Timestamp(row["origin_available_at"]).date().isoformat(),
                "knownThrough": pd.Timestamp(row["origin_date"]).date().isoformat(),
                "currentPrice": current,
                "forecast": float(row["inverse_mase"]),
                "p10": float(row["p10"]),
                "p90": float(row["p90"]),
                "actual": actual,
                "probabilityUp": _round(probability * 100, 1),
                "recommendation": recommendation,
                "suggestedLiters": round(suggested),
                "realizedSaving": _round(saving, 2),
                "weights": [
                    {"name": MODEL_LABELS.get(name, name), "value": _round(weight * 100, 1)}
                    for name, weight in weights.items()
                ],
                "sourcesAvailable": 3,
            }
        )
    return rows


def build_dashboard() -> dict[str, Any]:
    market = load_market_frame()
    features = build_features(market)
    forecasts = _load_json(ARTIFACTS_DIR / "forecasts" / "latest.json")
    metrics = pd.read_csv(ARTIFACTS_DIR / "reports" / "leaderboard.csv")
    backtest = pd.read_csv(
        ARTIFACTS_DIR / "forecasts" / "backtest_predictions.csv",
        parse_dates=["origin_date", "origin_available_at", "target_date"],
    )
    economic = _load_json(ARTIFACTS_DIR / "reports" / "economic_backtest.json")
    registry = _load_json(ARTIFACTS_DIR / "models" / "registry.json")
    run = _load_json(ARTIFACTS_DIR / "run_metadata.json")
    forecast_30 = next(item for item in forecasts if item["horizon_days"] == 30)
    recommendation = recommend(forecast_30, ProcurementScenario())
    latest = market.iloc[-1]
    previous = market.iloc[-2]

    history = [
        {
            "date": pd.Timestamp(row["semana_fim"]).date().isoformat(),
            "price": _round(row["preco_medio"]),
            "usd": _round(row["usd_brl_ultimo"]),
            "brent": _round(row["brent_ultimo"]),
        }
        for _, row in market.tail(52).iterrows()
    ]
    for forecast in forecasts:
        history.append(
            {
                "date": forecast["target_date"],
                "price": _round(forecast["point"]),
                "forecast": _round(forecast["point"]),
                "p10": _round(forecast["p10"]),
                "p90": _round(forecast["p90"]),
            }
        )

    forecast_rows = []
    for forecast in forecasts:
        calendar_days = int(
            (pd.Timestamp(forecast["target_date"]) - pd.Timestamp(forecast["origin_date"])).days
        )
        horizon_weeks = int(forecast["horizon_weeks"])
        forecast_rows.append(
            {
                "horizon": forecast["horizon_days"],
                "horizonCalendarDays": calendar_days,
                "horizonWeeks": horizon_weeks,
                "horizonLabel": (
                    f"{horizon_weeks} semana{'s' if horizon_weeks != 1 else ''} "
                    f"({calendar_days} dias)"
                ),
                "point": _round(forecast["point"]),
                "p10": _round(forecast["p10"]),
                "p90": _round(forecast["p90"]),
                "changePct": _round(forecast["change_pct"], 2),
                "probabilityUp": _round(forecast["probability_relevant_up"] * 100, 1),
                "confidence": _round(forecast["confidence"], 1),
                "coverage": _round(forecast["historical_interval_coverage"] * 100, 1),
                "champion": MODEL_LABELS.get(forecast["champion"], forecast["champion"]),
                "agreement": {"HIGH": "ALTA", "MEDIUM": "MÉDIA", "LOW": "BAIXA"}[
                    forecast["agreement"]
                ],
                "modelForecasts": [
                    {
                        "name": MODEL_LABELS.get(model, model),
                        "value": _round(forecast["model_predictions"][model]),
                        "weight": _round(forecast["weights"].get(model, 0) * 100, 1),
                    }
                    for model in forecast["eligible_models"]
                ],
            }
        )

    models: list[dict[str, Any]] = []
    for _, row in metrics.loc[~metrics["model"].eq("probability_layer")].iterrows():
        horizon = int(row["horizon_days"])
        forecast = next(item for item in forecasts if item["horizon_days"] == horizon)
        model = str(row["model"])
        registry_item = next(
            item for item in registry if item["family"] == model and item["horizon"] == horizon
        )
        models.append(
            {
                "model": MODEL_LABELS.get(model, model),
                "family": _model_family(model),
                "status": registry_item["status"],
                "horizon": horizon,
                "mae": _round(row["mae"]),
                "mase": _round(row["mase"]),
                "rmse": _round(row["rmse"]),
                "directionalAccuracy": _round(row["directional_accuracy"] * 100, 1),
                "intervalCoverage": None,
                "gainVsNaive": _round(row["gain_vs_naive_pct"], 1),
                "weight": _round(forecast["weights"].get(model, 0) * 100, 1),
            }
        )
    models.append(
        {
            "model": "VS-ePL-KRLS — Experimental",
            "family": "Adaptativo",
            "status": "experimental",
            "horizon": 30,
            "mae": 0,
            "mase": 0,
            "rmse": 0,
            "directionalAccuracy": 0,
            "gainVsNaive": 0,
            "weight": 0,
        }
    )

    seven = backtest.loc[backtest["horizon_days"].eq(7)].copy()
    economic_7 = next(item for item in economic["summary"] if item["horizon_days"] == 7)
    strategy_cost = float(
        sum(item["model_policy_cost"] for item in economic["detail"] if item["horizon_days"] == 7)
    )
    jit_cost = float(
        sum(item["just_in_time_cost"] for item in economic["detail"] if item["horizon_days"] == 7)
    )
    driver_values = latest_driver_snapshot(features)
    drivers = []
    for item in driver_values:
        direction = "up" if item["change_pct"] > 0 else "down" if item["change_pct"] < 0 else "neutral"
        formatted_value = (
            f"US$ {item['value']:.2f}"
            if item["id"] == "brent"
            else f"R$ {item['value']:.2f}"
            if item["id"] == "usd_brl"
            else f"R$ {item['value']:+.3f}/L"
        )
        drivers.append(
            {
                "name": item["label"],
                "value": formatted_value,
                "impact": _round(np.clip(item["change_pct"] / 15, -1, 1), 2),
                "direction": direction,
                "change": f"{item['change_pct']:+.2f}%",
                "detail": "Variação observada no último snapshot causal; impacto preditivo não implica causalidade.",
            }
        )

    quality = _load_json(DATA_DIR / "gold" / "quality_report.json")
    quality_checks = [
        {
            "name": check["check"].replace("_", " ").title(),
            "status": check["status"],
            "detail": check["detail"],
        }
        for check in quality["checks"]
    ]

    return {
        "meta": {
            "generatedAt": run["run_at"],
            "runId": f"atlas-br-{run['run_at'][:10]}",
            "dataMode": "cached",
            "geography": "Brasil",
            "geographyCode": "BR",
            "modelVersion": "rolling-origin-v1",
        },
        "market": {
            "currentPrice": _round(latest["preco_medio"]),
            "previousPrice": _round(previous["preco_medio"]),
            "weeklyChangePct": _round((latest["preco_medio"] / previous["preco_medio"] - 1) * 100, 2),
            "sampleSize": int(latest["numero_postos"]),
            "updatedAt": pd.Timestamp(latest["semana_fim"]).date().isoformat(),
            "history": history,
        },
        "forecasts": forecast_rows,
        "recommendation": {
            "signal": recommendation["signal"],
            "action": recommendation["action"],
            "recommendedLiters": recommendation["purchase_now_liters"],
            "totalLiters": recommendation["required_liters"],
            "percentage": _round(
                recommendation["purchase_now_liters"] / max(recommendation["required_liters"], 1) * 100,
                1,
            ),
            "potentialSavings": _round(recommendation["expected_savings_brl"], 2),
            "timingRisk": _round(recommendation["timing_risk_brl"], 2),
            "confidence": _round(forecast_30["confidence"], 1),
            "rationale": [
                recommendation["rationale"],
                f"Intervalo P10–P90 de R$ {forecast_30['p10']:.2f} a R$ {forecast_30['p90']:.2f}/L.",
                f"Cobertura atual estimada em {recommendation['stock_coverage_days']:.1f} dias.",
            ],
        },
        "drivers": drivers,
        "briefing": [
            {
                "title": "Brent recuou no snapshot",
                "body": f"O Brent encerrou a semana em US$ {latest['brent_ultimo']:.2f}, variação semanal de {latest['brent_variacao_semanal_pct']:+.1f}%.",
                "tone": "positive" if latest["brent_variacao_semanal_pct"] < 0 else "risk",
            },
            {
                "title": "Câmbio compõe o custo importado",
                "body": f"USD/BRL em R$ {latest['usd_brl_ultimo']:.2f}; o modelo testa sua interação com o petróleo em reais.",
                "tone": "neutral",
            },
            {
                "title": "Sinal operacional moderado",
                "body": "A recomendação preserva flexibilidade porque o forecast de 4 semanas (28 dias; identificador legado 30) está praticamente estável e o intervalo é largo.",
                "tone": "neutral",
            },
        ],
        "models": models,
        "backtest": {
            "period": f"{seven['origin_date'].min().date().isoformat()} — {seven['target_date'].max().date().isoformat()}",
            "folds": int(len(seven)),
            "refitCadence": "Expanding window semanal; tuning em origens internas passadas",
            "series": [
                {
                    "date": row["target_date"].date().isoformat(),
                    "actual": _round(row["actual"]),
                    "predicted": _round(row["inverse_mase"]),
                    "p10": _round(row["p10"]),
                    "p90": _round(row["p90"]),
                }
                for _, row in seven.iterrows()
            ],
            "economic": {
                "strategyCost": _round(strategy_cost, 2),
                "baselineCost": _round(jit_cost, 2),
                "saving": _round(economic_7["savings_vs_jit_brl"], 2),
                "savingPct": _round(economic_7["savings_vs_jit_brl"] / jit_cost * 100, 2),
                "decisions": economic_7["decisions"],
                "positiveDecisions": round(economic_7["positive_decisions_pct"] / 100 * economic_7["decisions"]),
            },
            "calibration": _calibration_rows(backtest),
        },
        "timeMachine": _time_machine(backtest),
        "sources": _sources_for_ui(market),
        "qualityChecks": quality_checks,
        "research": _research_for_ui(),
    }


def write_dashboard_snapshot(payload: dict[str, Any]) -> Path:
    target = ROOT / "apps" / "web" / "public" / "demo-data.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
