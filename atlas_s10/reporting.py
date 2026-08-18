"""Audit reports and analytics materialization for Atlas S10.

The report is deliberately generated from persisted backtest outputs.  It is
therefore reproducible, contains no hand-entered performance claims and can be
served as a static artifact during an offline demo.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import norm

from atlas_s10.config import DATA_DIR, REPORTS_DIR
from atlas_s10.features import HORIZON_WEEKS


def diebold_mariano(
    actual: pd.Series | np.ndarray,
    candidate: pd.Series | np.ndarray,
    baseline: pd.Series | np.ndarray,
    horizon_steps: int = 1,
) -> dict[str, float | int | None]:
    """Return a small-sample DM comparison using absolute-error loss.

    A negative statistic favours ``candidate``.  Newey-West autocovariances up
    to ``horizon_steps - 1`` account for overlapping multi-step forecast errors.
    The normal approximation is labelled as such in the generated report.
    """

    y = np.asarray(actual, dtype=float)
    left = np.asarray(candidate, dtype=float)
    right = np.asarray(baseline, dtype=float)
    mask = np.isfinite(y) & np.isfinite(left) & np.isfinite(right)
    differential = np.abs(y[mask] - left[mask]) - np.abs(y[mask] - right[mask])
    n = len(differential)
    if n < 8:
        return {"statistic": None, "p_value": None, "observations": n, "lag": 0}
    centered = differential - differential.mean()
    lag = min(max(0, int(horizon_steps) - 1), n - 2)
    long_run_variance = float(np.dot(centered, centered) / n)
    for offset in range(1, lag + 1):
        covariance = float(np.dot(centered[offset:], centered[:-offset]) / n)
        # Bartlett weights make the finite-sample estimate less erratic.
        long_run_variance += 2 * (1 - offset / (lag + 1)) * covariance
    if not math.isfinite(long_run_variance) or long_run_variance <= 1e-15:
        return {"statistic": None, "p_value": None, "observations": n, "lag": lag}
    statistic = float(differential.mean() / math.sqrt(long_run_variance / n))
    p_value = float(2 * norm.sf(abs(statistic)))
    return {
        "statistic": statistic,
        "p_value": p_value,
        "observations": n,
        "lag": lag,
    }


def build_diagnostics(
    predictions: pd.DataFrame,
    metrics: pd.DataFrame,
    forecasts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute model-comparison diagnostics from a common backtest panel."""

    point_metrics = metrics.loc[metrics["model"].ne("probability_layer")].copy()
    model_columns = [
        column
        for column in (
            "naive",
            "seasonal_naive",
            "moving_average_4",
            "moving_average_8",
            "moving_average_12",
            "arima",
            "sarima",
            "sarimax",
            "lightgbm",
            "lightgbm_price_only",
            "simple_average",
            "inverse_mase",
        )
        if column in predictions
    ]
    dm_rows: list[dict[str, Any]] = []
    correlations: list[dict[str, Any]] = []
    retirement: list[dict[str, Any]] = []
    weight_history: list[dict[str, Any]] = []
    for horizon, group in predictions.groupby("horizon_days"):
        horizon = int(horizon)
        group = group.sort_values("origin_date")
        for model in model_columns:
            if model == "naive":
                continue
            comparison = diebold_mariano(
                group["actual"],
                group[model],
                group["naive"],
                HORIZON_WEEKS[horizon],
            )
            dm_rows.append({"horizon_days": horizon, "model": model, **comparison})
        errors = pd.DataFrame(
            {model: group[model].astype(float) - group["actual"].astype(float) for model in model_columns}
        )
        correlations.append(
            {
                "horizon_days": horizon,
                "models": model_columns,
                "matrix": errors.corr().round(6).to_dict(),
            }
        )
        for _, row in point_metrics.loc[point_metrics["horizon_days"].eq(horizon)].iterrows():
            reasons: list[str] = []
            if float(row["mase"]) > 1:
                reasons.append("MASE > 1 no painel avaliado")
            if float(row["gain_vs_naive_pct"]) <= 0 and row["model"] != "naive":
                reasons.append("não superou naive em MAE")
            status = "review" if reasons else "retain"
            retirement.append(
                {
                    "horizon_days": horizon,
                    "model": str(row["model"]),
                    "status": status,
                    "reasons": reasons,
                }
            )
        for _, row in group.iterrows():
            try:
                weights = json.loads(str(row["ensemble_weights"]))
            except json.JSONDecodeError:
                weights = {}
            weight_history.append(
                {
                    "horizon_days": horizon,
                    "origin_date": pd.Timestamp(row["origin_date"]).date().isoformat(),
                    "weights": weights,
                }
            )

    probabilistic = metrics.loc[metrics["model"].eq("probability_layer")]
    return {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "dm_test": {
            "loss": "absolute error",
            "null": "equal expected forecast loss versus naive",
            "interpretation": "negative statistic favours the candidate; p-values use a normal approximation",
            "rows": dm_rows,
        },
        "error_correlations": correlations,
        "probabilistic_metrics": probabilistic.replace({np.nan: None}).to_dict(orient="records"),
        "model_governance": retirement,
        "weight_history": weight_history,
        "latest_forecasts": forecasts,
        "limitations": [
            "Only 24 outer origins per horizon are shown; statistical power is limited.",
            "DM p-values use an asymptotic normal approximation and are diagnostic, not proof of superiority.",
            "The interval layer uses past-only empirical residuals and targets 80% P10–P90 coverage.",
            "Economic results are a stylized counterfactual and omit private logistics, financing and supplier terms.",
            "VS-ePL-KRLS remains experimental because no licensed author reference implementation was located.",
            "A neural challenger was not fit because fewer than 200 weekly target observations create a high overfit risk.",
        ],
    }


def _table(frame: pd.DataFrame, columns: list[str] | None = None) -> str:
    selected = frame if columns is None else frame[[column for column in columns if column in frame]]
    return selected.to_html(index=False, border=0, classes="data-table", float_format=lambda x: f"{x:.5f}")


def write_backtest_report(
    predictions: pd.DataFrame,
    metrics: pd.DataFrame,
    forecasts: list[dict[str, Any]],
    economic: dict[str, Any],
    diagnostics: dict[str, Any],
) -> Path:
    """Generate a self-contained, presentation-ready static HTML report."""

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    quality_path = DATA_DIR / "gold" / "quality_report.json"
    quality = json.loads(quality_path.read_text(encoding="utf-8")) if quality_path.exists() else {}
    leaderboard = metrics.loc[metrics["model"].ne("probability_layer")].sort_values(
        ["horizon_days", "mae"]
    )
    probability = metrics.loc[metrics["model"].eq("probability_layer")]
    dm = pd.DataFrame(diagnostics["dm_test"]["rows"])
    governance = pd.DataFrame(diagnostics["model_governance"])
    economic_summary = pd.DataFrame(economic["summary"])
    champion_rows = []
    for forecast in forecasts:
        champion_rows.append(
            {
                "horizon_days": forecast["horizon_days"],
                "origin": forecast["origin_date"],
                "target": forecast["target_date"],
                "current": forecast["current_price"],
                "p50": forecast["point"],
                "p10": forecast["p10"],
                "p90": forecast["p90"],
                "prob_up": forecast["probability_relevant_up"],
                "champion": forecast["champion"],
                "operational": forecast["operational_model"],
                "agreement": forecast["agreement"],
            }
        )
    period = (
        f"{pd.to_datetime(predictions['origin_date']).min().date()} — "
        f"{pd.to_datetime(predictions['target_date']).max().date()}"
    )
    warnings = quality.get("warnings", [])
    limitations = diagnostics["limitations"]
    cards = "".join(
        f"<li>{escape(str(item))}</li>" for item in [*warnings, *limitations]
    )
    html = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Atlas S10 — Relatório de backtest</title>
<style>
:root{{--bg:#0b1220;--panel:#111b2d;--line:#26344d;--text:#e8eef8;--muted:#9caec7;--accent:#4aa8ff;--good:#45cf9a;--warn:#f5b84b}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 Inter,Segoe UI,sans-serif}}
main{{max-width:1280px;margin:auto;padding:36px}} h1{{font-size:34px;margin:0}} h2{{margin-top:38px;border-bottom:1px solid var(--line);padding-bottom:10px}}
.eyebrow{{color:var(--accent);font-size:12px;letter-spacing:.16em;text-transform:uppercase}} .muted{{color:var(--muted)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;margin:22px 0}} .card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px}}
.metric{{font-size:23px;font-variant-numeric:tabular-nums}} .data-table{{width:100%;border-collapse:collapse;background:var(--panel);font-variant-numeric:tabular-nums}}
.data-table th,.data-table td{{padding:9px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}} .data-table th:first-child,.data-table td:first-child{{text-align:left}}
.scroll{{overflow:auto;border:1px solid var(--line);border-radius:12px}} code{{color:var(--good)}} li{{margin:6px 0}} @media(max-width:700px){{main{{padding:20px}}}}
</style></head><body><main>
<div class="eyebrow">Atlas S10 · audit artifact</div><h1>Backtest temporal e governança</h1>
<p class="muted">Gerado em {escape(diagnostics['generated_at'])}. Período das previsões externas: {escape(period)}. Todos os folds usam janela expansiva e dados conhecidos na origem.</p>
<div class="grid"><div class="card"><div class="muted">Folds</div><div class="metric">{len(predictions)}</div></div>
<div class="card"><div class="muted">Horizontes</div><div class="metric">7 · 14 · 30d</div></div>
<div class="card"><div class="muted">Qualidade dos dados</div><div class="metric">{escape(str(quality.get('status','unknown')).upper())}</div></div>
<div class="card"><div class="muted">Protocolo</div><div class="metric">Rolling origin</div></div></div>
<h2>Forecast operacional atual</h2><div class="scroll">{_table(pd.DataFrame(champion_rows))}</div>
<h2>Leaderboard comum</h2><p class="muted">Modelos são comparados no mesmo target nacional, período, frequência e protocolo.</p>
<div class="scroll">{_table(leaderboard, ['horizon_days','model','mae','rmse','mase','smape_pct','directional_accuracy','gain_vs_naive_pct','gain_vs_sarimax_pct','folds'])}</div>
<h2>Probabilidade e intervalos</h2><div class="scroll">{_table(probability, ['horizon_days','brier','log_loss','precision','recall','f1','picp_p10_p90','interval_width','pinball_p10','pinball_p90','folds'])}</div>
<h2>Diebold–Mariano vs naive</h2><p class="muted">Perda absoluta; estatística negativa favorece o candidato. Inferência exploratória com amostra curta.</p>
<div class="scroll">{_table(dm, ['horizon_days','model','statistic','p_value','observations','lag'])}</div>
<h2>Backtest econômico</h2><div class="scroll">{_table(economic_summary)}</div><p class="muted">{escape(economic['caveat'])}</p>
<h2>Governança de modelos</h2><div class="scroll">{_table(governance, ['horizon_days','model','status','reasons'])}</div>
<h2>Limitações e avisos</h2><ul>{cards}</ul>
<h2>Reprodutibilidade</h2><p>Execute <code>python pipelines/prepare_data.py</code>, <code>python pipelines/train.py</code> e <code>python pipelines/build_product.py</code>. O painel completo de correlações e pesos está em <code>artifacts/reports/diagnostics.json</code>.</p>
</main></body></html>"""
    path = REPORTS_DIR / "backtest.html"
    path.write_text(html, encoding="utf-8")
    return path


def materialize_analytics(
    predictions: pd.DataFrame,
    metrics: pd.DataFrame,
) -> dict[str, Path]:
    """Persist Parquet gold tables and a local DuckDB analytical catalog."""

    gold = DATA_DIR / "gold"
    market_csv = gold / "market_weekly.csv"
    observations_csv = gold / "normalized_observations.csv"
    outputs: dict[str, Path] = {}
    frames: dict[str, pd.DataFrame] = {
        "backtest_predictions": predictions,
        "model_leaderboard": metrics,
    }
    if market_csv.exists():
        frames["market_weekly"] = pd.read_csv(market_csv)
    if observations_csv.exists():
        frames["normalized_observations"] = pd.read_csv(observations_csv)
    for name in ("market_weekly", "normalized_observations"):
        if name in frames:
            target = gold / f"{name}.parquet"
            frames[name].to_parquet(target, index=False)
            outputs[name] = target
    database = DATA_DIR / "atlas_s10.duckdb"
    connection = duckdb.connect(str(database))
    try:
        for name, frame in frames.items():
            connection.register("source_frame", frame)
            connection.execute(f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM source_frame')
            connection.unregister("source_frame")
        connection.execute(
            "CREATE OR REPLACE VIEW latest_market AS SELECT * FROM market_weekly ORDER BY semana_fim DESC LIMIT 1"
        )
        connection.execute(
            "CREATE OR REPLACE VIEW champion_leaderboard AS "
            "SELECT * FROM model_leaderboard WHERE model <> 'probability_layer' "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY horizon_days ORDER BY mae) = 1"
        )
    finally:
        connection.close()
    outputs["duckdb"] = database
    return outputs


def generate_reports(
    predictions: pd.DataFrame,
    metrics: pd.DataFrame,
    forecasts: list[dict[str, Any]],
    economic: dict[str, Any],
) -> dict[str, Path]:
    """Generate every reporting/storage artifact used by the demo."""

    diagnostics = build_diagnostics(predictions, metrics, forecasts)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    diagnostics_path = REPORTS_DIR / "diagnostics.json"
    diagnostics_path.write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    html_path = write_backtest_report(predictions, metrics, forecasts, economic, diagnostics)
    outputs = materialize_analytics(predictions, metrics)
    return {"diagnostics": diagnostics_path, "backtest_html": html_path, **outputs}
