"""Temporal backtesting, model selection and probabilistic forecasting.

All outer predictions are produced from an expanding window.  Model tuning is
performed only on inner origins that precede the outer origin.  The small data
regime is intentional: complex models must earn their place against naive
forecasts rather than win through an oversized search space.
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import expit
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.statespace.sarimax import SARIMAX

from atlas_s10.config import ARTIFACTS_DIR, FORECASTS_DIR, MODELS_DIR, REPORTS_DIR
from atlas_s10.features import HORIZON_WEEKS, assert_causal_training, model_feature_columns
from atlas_s10.metrics import (
    brier_score,
    classification_metrics,
    directional_accuracy,
    log_loss,
    mae,
    mase,
    picp,
    pinball_loss,
    rmse,
    smape,
)

MODEL_LABELS = {
    "naive": "Naive",
    "seasonal_naive": "Seasonal naive (52s)",
    "moving_average_4": "Média móvel 4",
    "moving_average_8": "Média móvel 8",
    "moving_average_12": "Média móvel 12",
    "arima": "ARIMA",
    "sarima": "SARIMA",
    "sarimax": "SARIMAX + mercado",
    "lightgbm": "LightGBM",
    "lightgbm_price_only": "LightGBM — somente preço",
    "simple_average": "Média simples",
    "inverse_mase": "Ensemble inverse-MASE",
}

BASE_MODELS = [
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
]


@dataclass(frozen=True)
class BacktestConfig:
    outer_origins: int = 24
    min_training_rows: int = 60
    relevant_up_threshold: float = 0.005
    conformal_alpha: float = 0.20
    ensemble_shrinkage: float = 0.25
    max_weight: float = 0.60
    seed: int = 42


LGB_CANDIDATES = [
    {"n_estimators": 80, "learning_rate": 0.035, "num_leaves": 7, "max_depth": 3},
    {"n_estimators": 120, "learning_rate": 0.025, "num_leaves": 9, "max_depth": 4},
    {"n_estimators": 70, "learning_rate": 0.05, "num_leaves": 5, "max_depth": 3},
]


def _safe_float(value: Any) -> float | None:
    value = float(value)
    return value if math.isfinite(value) else None


def _prepare_matrix(
    train: pd.DataFrame, row: pd.DataFrame, columns: list[str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    x_train = train[columns].replace([np.inf, -np.inf], np.nan).copy()
    x_row = row[columns].replace([np.inf, -np.inf], np.nan).copy()
    medians = x_train.median(numeric_only=True).fillna(0.0)
    return x_train.fillna(medians), x_row.fillna(medians)


def _fit_lightgbm(
    train: pd.DataFrame,
    row: pd.DataFrame,
    feature_columns: list[str],
    target_column: str,
    params: dict[str, Any],
    seed: int,
) -> float:
    x_train, x_row = _prepare_matrix(train, row, feature_columns)
    model = lgb.LGBMRegressor(
        objective="regression_l1",
        verbosity=-1,
        random_state=seed,
        n_jobs=1,
        min_child_samples=max(8, min(18, len(train) // 4)),
        reg_lambda=0.8,
        reg_alpha=0.05,
        subsample=0.9,
        colsample_bytree=0.85,
        **params,
    )
    model.fit(x_train, train[target_column].astype(float))
    return float(model.predict(x_row)[0])


def _choose_lgb_params(
    features: pd.DataFrame,
    outer_index: int,
    horizon_days: int,
    feature_columns: list[str],
    config: BacktestConfig,
) -> dict[str, Any]:
    weeks = HORIZON_WEEKS[horizon_days]
    possible = list(range(max(config.min_training_rows, outer_index - 16), outer_index, 4))
    inner_origins = possible[-3:]
    target = f"target_{horizon_days}"
    if not inner_origins:
        return LGB_CANDIDATES[0]
    scores: list[float] = []
    for candidate in LGB_CANDIDATES:
        errors: list[float] = []
        for inner_index in inner_origins:
            inner_row = features.iloc[[inner_index]]
            inner_origin = features.iloc[inner_index]
            training = features.iloc[: inner_index - weeks + 1].dropna(subset=[target]).copy()
            training = training.loc[
                pd.to_datetime(training[f"target_available_at_{horizon_days}"], utc=True)
                <= pd.to_datetime(inner_origin["available_at"], utc=True)
            ]
            if len(training) < 35:
                continue
            prediction = _fit_lightgbm(
                training, inner_row, feature_columns, target, candidate, config.seed
            )
            actual = float(features.iloc[inner_index][target])
            errors.append(abs(prediction - actual))
        scores.append(float(np.mean(errors)) if errors else float("inf"))
    return dict(LGB_CANDIDATES[int(np.argmin(scores))])


def _statistical_predictions(
    price_history: pd.Series,
    exogenous_history: pd.DataFrame,
    horizon_weeks: int,
) -> dict[str, float]:
    y = price_history.astype(float).to_numpy()
    predictions: dict[str, float] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            model = ARIMA(y, order=(1, 1, 1), trend="t").fit()
            predictions["arima"] = float(model.forecast(horizon_weeks)[-1])
        except Exception:
            predictions["arima"] = float(y[-1])
        try:
            model = SARIMAX(
                y,
                order=(1, 1, 1),
                seasonal_order=(1, 0, 0, 13),
                trend="t",
                enforce_stationarity=False,
                enforce_invertibility=False,
            ).fit(disp=False, maxiter=60)
            predictions["sarima"] = float(model.forecast(horizon_weeks)[-1])
        except Exception:
            predictions["sarima"] = predictions["arima"]
        try:
            exog = exogenous_history.replace([np.inf, -np.inf], np.nan).ffill().bfill()
            means = exog.mean()
            scales = exog.std().replace(0, 1).fillna(1)
            scaled = (exog - means) / scales
            future = pd.DataFrame(
                np.repeat(scaled.iloc[[-1]].to_numpy(), horizon_weeks, axis=0),
                columns=scaled.columns,
            )
            model = SARIMAX(
                y,
                exog=scaled.to_numpy(),
                order=(1, 1, 0),
                trend="t",
                enforce_stationarity=False,
                enforce_invertibility=False,
            ).fit(disp=False, maxiter=60)
            predictions["sarimax"] = float(model.forecast(horizon_weeks, exog=future)[-1])
        except Exception:
            predictions["sarimax"] = predictions["arima"]
    return predictions


def _point_predictions(
    features: pd.DataFrame,
    origin_index: int,
    horizon_days: int,
    feature_columns: list[str],
    config: BacktestConfig,
) -> tuple[dict[str, float], dict[str, Any]]:
    weeks = HORIZON_WEEKS[horizon_days]
    origin = features.iloc[origin_index]
    target_column = f"target_{horizon_days}"
    training = features.iloc[: origin_index - weeks + 1].dropna(subset=[target_column]).copy()
    origin_available = pd.to_datetime(origin["available_at"], utc=True)
    training = training.loc[
        pd.to_datetime(training[f"target_available_at_{horizon_days}"], utc=True)
        <= origin_available
    ]
    assert_causal_training(training, origin, horizon_days)
    if len(training) < config.min_training_rows - weeks:
        raise ValueError(f"Only {len(training)} causal training rows for {horizon_days}d")

    history = features.iloc[: origin_index + 1]
    prices = history["price"].astype(float)
    points = {
        "naive": float(prices.iloc[-1]),
        "seasonal_naive": float(prices.iloc[-52]) if len(prices) >= 52 else float(prices.iloc[-1]),
        "moving_average_4": float(prices.iloc[-4:].mean()),
        "moving_average_8": float(prices.iloc[-8:].mean()),
        "moving_average_12": float(prices.iloc[-12:].mean()),
    }
    points.update(
        _statistical_predictions(
            prices,
            history[["brent", "usd_brl", "landed_oil_brl"]],
            weeks,
        )
    )
    lgb_params = _choose_lgb_params(
        features, origin_index, horizon_days, feature_columns, config
    )
    points["lightgbm"] = _fit_lightgbm(
        training,
        features.iloc[[origin_index]],
        feature_columns,
        target_column,
        lgb_params,
        config.seed,
    )
    price_only_columns = [
        column for column in feature_columns if column == "price" or column.startswith("price_")
    ]
    price_only_params = _choose_lgb_params(
        features, origin_index, horizon_days, price_only_columns, config
    )
    points["lightgbm_price_only"] = _fit_lightgbm(
        training,
        features.iloc[[origin_index]],
        price_only_columns,
        target_column,
        price_only_params,
        config.seed,
    )
    lower_plausible = max(1.0, float(prices.iloc[-1]) * 0.65)
    upper_plausible = float(prices.iloc[-1]) * 1.45
    points = {
        model: float(np.clip(prediction, lower_plausible, upper_plausible))
        for model, prediction in points.items()
    }
    return points, {
        "lightgbm": lgb_params,
        "lightgbm_price_only": price_only_params,
        "training_rows": int(len(training)),
    }


def inverse_mase_weights(
    errors: pd.DataFrame,
    models: list[str],
    shrinkage: float = 0.25,
    max_weight: float = 0.60,
) -> dict[str, float]:
    if not models:
        raise ValueError("At least one model is required")
    if len(models) == 1:
        return {models[0]: 1.0}
    scores = np.asarray(
        [1.0 / (1e-6 + float(errors[model].abs().mean())) for model in models], dtype=float
    )
    raw = scores / scores.sum()
    uniform = np.full(len(models), 1.0 / len(models))
    weights = (1 - shrinkage) * raw + shrinkage * uniform
    weights = np.minimum(weights, max_weight)
    # Iterative redistribution respects the cap even with two highly unequal models.
    for _ in range(10):
        weights = weights / weights.sum()
        over = weights > max_weight
        if not over.any():
            break
        excess = float(np.sum(weights[over] - max_weight))
        weights[over] = max_weight
        under = ~over
        if under.any():
            weights[under] += excess * weights[under] / weights[under].sum()
    weights = weights / weights.sum()
    return {model: float(weight) for model, weight in zip(models, weights, strict=True)}


def _add_sequential_probabilities(
    predictions: pd.DataFrame, config: BacktestConfig
) -> pd.DataFrame:
    result = predictions.sort_values(["horizon_days", "origin_date"]).copy()
    for horizon, indexes in result.groupby("horizon_days", sort=False).groups.items():
        horizon_rows = result.loc[indexes].sort_values("origin_date")
        for index in horizon_rows.index:
            current_origin = pd.to_datetime(result.loc[index, "origin_available_at"], utc=True)
            previous = horizon_rows.loc[
                pd.to_datetime(horizon_rows["target_available_at"], utc=True).le(current_origin)
                & horizon_rows.index.to_series().ne(index)
            ]
            residuals = previous["actual"] - previous["ensemble_prediction"]
            if len(residuals) >= 8:
                scale = max(0.015, float(np.std(residuals, ddof=1)))
                quantile = float(
                    np.quantile(np.abs(residuals), 1 - config.conformal_alpha, method="higher")
                )
            elif len(previous) >= 2:
                realized_moves = (previous["actual"] - previous["current_price"]).abs()
                scale = max(0.015, float(realized_moves.median()))
                quantile = 1.282 * scale
            else:
                # No future fold statistics: use a deliberately conservative,
                # scale-relative prior until enough errors have actually matured.
                scale = max(
                    0.03,
                    float(result.loc[index, "current_price"])
                    * 0.02
                    * math.sqrt(HORIZON_WEEKS[int(horizon)]),
                )
                quantile = 1.282 * scale
            row = result.loc[index]
            threshold_price = float(row["current_price"]) * (1 + config.relevant_up_threshold)
            probability = float(expit((float(row["ensemble_prediction"]) - threshold_price) / scale))
            result.loc[index, "probability_relevant_up"] = probability
            result.loc[index, "p10"] = float(row["ensemble_prediction"]) - quantile
            result.loc[index, "p90"] = float(row["ensemble_prediction"]) + quantile
            result.loc[index, "calibration_count"] = int(len(residuals))
    return result


def run_backtest(features: pd.DataFrame, config: BacktestConfig | None = None) -> pd.DataFrame:
    config = config or BacktestConfig()
    feature_columns = model_feature_columns(features)
    rows: list[dict[str, Any]] = []
    for horizon_days, weeks in HORIZON_WEEKS.items():
        last_origin = len(features) - weeks - 1
        first_origin = max(config.min_training_rows + weeks, last_origin - config.outer_origins + 1)
        realized_errors: list[dict[str, Any]] = []
        for origin_index in range(first_origin, last_origin + 1):
            origin = features.iloc[origin_index]
            points, metadata = _point_predictions(
                features, origin_index, horizon_days, feature_columns, config
            )
            # Ensembles use only errors realized strictly before this origin.
            origin_available = pd.to_datetime(origin["available_at"], utc=True)
            matured = [
                record
                for record in realized_errors
                if pd.to_datetime(record["realized_at"], utc=True) <= origin_available
            ]
            available_errors = pd.DataFrame(
                [{model: record[model] for model in BASE_MODELS} for record in matured]
            )
            if len(available_errors) >= 6:
                eligible = sorted(
                    BASE_MODELS,
                    key=lambda model: float(available_errors[model].abs().mean()),
                )[:4]
                weights = inverse_mase_weights(
                    available_errors,
                    eligible,
                    config.ensemble_shrinkage,
                    config.max_weight,
                )
            else:
                eligible = ["naive", "arima", "lightgbm"]
                weights = {model: 1 / len(eligible) for model in eligible}
            simple_prediction = float(np.mean([points[model] for model in eligible]))
            ensemble_prediction = float(sum(points[model] * weight for model, weight in weights.items()))
            actual = float(origin[f"target_{horizon_days}"])
            current = float(origin["price"])
            row: dict[str, Any] = {
                "horizon_days": horizon_days,
                "horizon_weeks": weeks,
                "origin_date": origin["observation_date"],
                "origin_available_at": origin["available_at"],
                "target_date": origin[f"target_date_{horizon_days}"],
                "target_available_at": origin[f"target_available_at_{horizon_days}"],
                "current_price": current,
                "actual": actual,
                "simple_average": simple_prediction,
                "inverse_mase": ensemble_prediction,
                "ensemble_prediction": ensemble_prediction,
                "eligible_models": json.dumps(eligible),
                "ensemble_weights": json.dumps(weights, sort_keys=True),
                "training_rows": metadata["training_rows"],
                "lightgbm_params": json.dumps(metadata["lightgbm"], sort_keys=True),
                "lightgbm_price_only_params": json.dumps(
                    metadata["lightgbm_price_only"], sort_keys=True
                ),
            }
            row.update(points)
            rows.append(row)
            realized_errors.append(
                {
                    **{model: points[model] - actual for model in BASE_MODELS},
                    "realized_at": origin[f"target_available_at_{horizon_days}"],
                }
            )
    result = pd.DataFrame(rows)
    return _add_sequential_probabilities(result, config)


def evaluate_backtest(predictions: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    models = [*BASE_MODELS, "simple_average", "inverse_mase"]
    for horizon, group in predictions.groupby("horizon_days"):
        group = group.sort_values("origin_date")
        actual = group["actual"].to_numpy(float)
        current = group["current_price"].to_numpy(float)
        horizon_weeks = HORIZON_WEEKS[int(horizon)]
        training_end = pd.to_datetime(group["origin_date"].min())
        historical = features.loc[features["observation_date"].lt(training_end), "price"].to_numpy(float)
        scale = float(np.mean(np.abs(historical[horizon_weeks:] - historical[:-horizon_weeks])))
        naive_mae = mae(actual, group["naive"].to_numpy(float))
        sarimax_mae = mae(actual, group["sarimax"].to_numpy(float))
        for model in models:
            predicted = group[model].to_numpy(float)
            model_mae = mae(actual, predicted)
            rows.append(
                {
                    "horizon_days": int(horizon),
                    "model": model,
                    "label": MODEL_LABELS[model],
                    "mae": model_mae,
                    "rmse": rmse(actual, predicted),
                    "mase": mase(actual, predicted, scale),
                    "smape_pct": smape(actual, predicted),
                    "directional_accuracy": directional_accuracy(actual, predicted, current),
                    "gain_vs_naive_pct": (naive_mae - model_mae) / naive_mae * 100,
                    "gain_vs_sarimax_pct": (sarimax_mae - model_mae) / sarimax_mae * 100,
                    "folds": int(len(group)),
                }
            )
        actual_up = actual > current * 1.005
        probability = group["probability_relevant_up"].to_numpy(float)
        probability_metrics = {
            "horizon_days": int(horizon),
            "model": "probability_layer",
            "label": "Probabilidade ensemble",
            "brier": brier_score(actual_up, probability),
            "log_loss": log_loss(actual_up, probability),
            **classification_metrics(actual_up, probability >= 0.5),
            "picp_p10_p90": picp(
                actual, group["p10"].to_numpy(float), group["p90"].to_numpy(float)
            ),
            "interval_width": float((group["p90"] - group["p10"]).mean()),
            "pinball_p10": pinball_loss(actual, group["p10"].to_numpy(float), 0.10),
            "pinball_p90": pinball_loss(actual, group["p90"].to_numpy(float), 0.90),
            "folds": int(len(group)),
        }
        rows.append(probability_metrics)
    return pd.DataFrame(rows)


def _champion_by_horizon(metrics: pd.DataFrame) -> dict[int, str]:
    candidates = metrics.loc[metrics["model"].isin([*BASE_MODELS, "simple_average", "inverse_mase"])]
    return {
        int(horizon): str(group.sort_values(["mase", "mae"]).iloc[0]["model"])
        for horizon, group in candidates.groupby("horizon_days")
    }


def _latest_distribution(
    features: pd.DataFrame,
    backtest: pd.DataFrame,
    metrics: pd.DataFrame,
    horizon_days: int,
    config: BacktestConfig,
) -> dict[str, Any]:
    feature_columns = model_feature_columns(features)
    origin_index = len(features) - 1
    points, metadata = _point_predictions(
        features, origin_index, horizon_days, feature_columns, config
    )
    realized = backtest.loc[backtest["horizon_days"].eq(horizon_days)]
    error_frame = pd.DataFrame(
        {model: realized[model] - realized["actual"] for model in BASE_MODELS}
    )
    eligible = list(
        metrics.loc[
            metrics["horizon_days"].eq(horizon_days) & metrics["model"].isin(BASE_MODELS)
        ]
        .sort_values("mase")
        .head(4)["model"]
    )
    weights = inverse_mase_weights(
        error_frame,
        eligible,
        config.ensemble_shrinkage,
        config.max_weight,
    )
    ensemble = float(sum(points[model] * weight for model, weight in weights.items()))
    champion = _champion_by_horizon(metrics)[horizon_days]
    if champion == "simple_average":
        point = float(np.mean([points[model] for model in eligible]))
    elif champion == "inverse_mase":
        point = ensemble
    else:
        point = points[champion]

    # Operational output uses the empirically weighted distribution whenever it
    # is within one standard error of the winning point model. This avoids
    # unstable winner-takes-all selection in a short backtest.
    champion_metric = metrics.loc[
        metrics["horizon_days"].eq(horizon_days) & metrics["model"].eq(champion), "mae"
    ].iloc[0]
    ensemble_metric = metrics.loc[
        metrics["horizon_days"].eq(horizon_days) & metrics["model"].eq("inverse_mase"), "mae"
    ].iloc[0]
    standard_error = float(realized["actual"].sub(realized[champion]).abs().std() / math.sqrt(len(realized)))
    operational_model = "inverse_mase" if ensemble_metric <= champion_metric + standard_error else champion
    if operational_model == "inverse_mase":
        point = ensemble

    residuals = realized["actual"] - realized["inverse_mase"]
    absolute = residuals.abs()
    conformal = float(np.quantile(absolute, 0.80, method="higher"))
    residual_scale = max(0.015, float(residuals.std(ddof=1)))
    current = float(features.iloc[-1]["price"])
    threshold = current * (1 + config.relevant_up_threshold)
    probability_up = float(expit((point - threshold) / residual_scale))
    predictions = np.asarray([points[model] for model in eligible])
    disagreement = float(np.std(predictions, ddof=0))
    agreement_ratio = disagreement / max(float(realized["inverse_mase"].sub(realized["actual"]).abs().mean()), 0.01)
    agreement = "HIGH" if agreement_ratio < 0.45 else "MEDIUM" if agreement_ratio < 0.90 else "LOW"

    probabilistic = metrics.loc[
        metrics["horizon_days"].eq(horizon_days) & metrics["model"].eq("probability_layer")
    ].iloc[0]
    coverage = float(probabilistic["picp_p10_p90"])
    calibration_score = max(0.0, 1 - abs(coverage - 0.8) / 0.8)
    width_ratio = 2 * conformal / current
    agreement_score = {"HIGH": 1.0, "MEDIUM": 0.72, "LOW": 0.42}[agreement]
    recent_errors = absolute.tail(8)
    recent_score = max(0.0, 1 - float(recent_errors.mean()) / max(current * 0.04, 0.01))
    confidence = 100 * (
        0.35 * calibration_score
        + 0.25 * agreement_score
        + 0.20 * max(0.0, 1 - width_ratio / 0.10)
        + 0.20 * recent_score
    )
    confidence = float(np.clip(confidence, 25, 92))
    confidence_label = "HIGH" if confidence >= 78 else "MODERATE" if confidence >= 58 else "LOW"

    # The ANP target is weekly.  The product label keeps the business-friendly
    # 30-day horizon, while the direct model target is explicitly four weeks.
    target_date = features.iloc[-1]["observation_date"] + pd.Timedelta(
        weeks=HORIZON_WEEKS[horizon_days]
    )
    return {
        "horizon_days": horizon_days,
        "horizon_weeks": HORIZON_WEEKS[horizon_days],
        "origin_date": pd.Timestamp(features.iloc[-1]["observation_date"]).date().isoformat(),
        "target_date": pd.Timestamp(target_date).date().isoformat(),
        "current_price": current,
        "point": point,
        "change_abs": point - current,
        "change_pct": (point / current - 1) * 100,
        "p10": max(0.0, point - conformal),
        "p90": point + conformal,
        "probability_relevant_up": probability_up,
        "relevant_up_threshold_pct": config.relevant_up_threshold * 100,
        "champion": champion,
        "operational_model": operational_model,
        "model_predictions": points,
        "eligible_models": eligible,
        "weights": weights,
        "agreement": agreement,
        "model_dispersion": disagreement,
        "historical_interval_coverage": coverage,
        "confidence": confidence,
        "confidence_label": confidence_label,
        "confidence_components": {
            "calibration": calibration_score,
            "agreement": agreement_score,
            "interval_width": max(0.0, 1 - width_ratio / 0.10),
            "recent_performance": recent_score,
        },
        "training_rows": metadata["training_rows"],
        "trained_until": pd.Timestamp(features.iloc[-1]["observation_date"]).date().isoformat(),
        "experimental": False,
    }


def build_forecasts(
    features: pd.DataFrame,
    backtest: pd.DataFrame,
    metrics: pd.DataFrame,
    config: BacktestConfig | None = None,
) -> list[dict[str, Any]]:
    config = config or BacktestConfig()
    return [
        _latest_distribution(features, backtest, metrics, horizon, config)
        for horizon in HORIZON_WEEKS
    ]


def economic_backtest(predictions: pd.DataFrame, volume_liters: float = 70_000) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for _, row in predictions.iterrows():
        probability = float(row["probability_relevant_up"])
        expected_change = float(row["ensemble_prediction"] / row["current_price"] - 1)
        fraction = 0.60 if probability >= 0.65 and expected_change > 0 else 0.35 if probability >= 0.5 else 0.15
        policy_cost = volume_liters * (
            fraction * float(row["current_price"]) + (1 - fraction) * float(row["actual"])
        )
        jit_cost = volume_liters * float(row["actual"])
        fixed_cost = volume_liters * (
            0.5 * float(row["current_price"]) + 0.5 * float(row["actual"])
        )
        rows.append(
            {
                "horizon_days": int(row["horizon_days"]),
                "origin_date": pd.Timestamp(row["origin_date"]).date().isoformat(),
                "fraction_bought_early": fraction,
                "model_policy_cost": policy_cost,
                "just_in_time_cost": jit_cost,
                "fixed_50_50_cost": fixed_cost,
                "savings_vs_jit": jit_cost - policy_cost,
                "savings_vs_fixed": fixed_cost - policy_cost,
            }
        )
    detail = pd.DataFrame(rows)
    summary = []
    for horizon, group in detail.groupby("horizon_days"):
        summary.append(
            {
                "horizon_days": int(horizon),
                "decisions": int(len(group)),
                "volume_per_decision_liters": volume_liters,
                "savings_vs_jit_brl": float(group["savings_vs_jit"].sum()),
                "savings_vs_fixed_brl": float(group["savings_vs_fixed"].sum()),
                "positive_decisions_pct": float(group["savings_vs_jit"].gt(0).mean() * 100),
                "worst_regret_brl": float(group["savings_vs_jit"].min()),
            }
        )
    return {
        "policy": "Antecipação 60%/35%/15% conforme probabilidade; 70.000 L por decisão",
        "baseline": "Just-in-time: 100% do volume no fim do horizonte",
        "summary": summary,
        "detail": rows,
        "caveat": "Backtest contrafactual sem frete, desconto, custo de capital ou restrições privadas de tanque.",
    }


def build_registry(metrics: pd.DataFrame, forecasts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    champions = {item["horizon_days"]: item["champion"] for item in forecasts}
    created = datetime.now(UTC).replace(microsecond=0).isoformat()
    registry: list[dict[str, Any]] = []
    for _, row in metrics.loc[~metrics["model"].eq("probability_layer")].iterrows():
        model = str(row["model"])
        horizon = int(row["horizon_days"])
        status = "champion" if champions[horizon] == model else "baseline" if model in BASE_MODELS[:7] else "challenger"
        registry.append(
            {
                "model_id": f"{model}-h{horizon}-v1",
                "family": model,
                "label": MODEL_LABELS[model],
                "horizon": horizon,
                "trained_until": forecasts[0]["trained_until"],
                "features": (
                    "causal weekly market features"
                    if model in {"lightgbm", "sarimax"}
                    else "causal target-price features"
                    if model == "lightgbm_price_only"
                    else "target history"
                ),
                "hyperparameters": "fixed parsimonious specification; LightGBM tuned by inner temporal origins",
                "metrics": {
                    key: _safe_float(row[key])
                    for key in ("mae", "rmse", "mase", "smape_pct", "directional_accuracy")
                },
                "status": status,
                "artifact": (
                    f"artifacts/models/lightgbm_h{horizon}.txt"
                    if model == "lightgbm"
                    else "artifacts/forecasts/backtest_predictions.csv"
                ),
                "created_at": created,
            }
        )
    for horizon in HORIZON_WEEKS:
        registry.append(
            {
                "model_id": f"vs-epl-krls-h{horizon}-experimental",
                "family": "vs-epl-krls",
                "label": "VS-ePL-KRLS — Experimental",
                "horizon": horizon,
                "trained_until": None,
                "features": [],
                "hyperparameters": {},
                "metrics": {},
                "status": "experimental",
                "artifact": None,
                "created_at": created,
                "limitation": "Paper reviewed; no author-licensed reference implementation was located. No approximation is presented as faithful.",
            }
        )
    return registry


def save_latest_lightgbm_models(
    features: pd.DataFrame,
    config: BacktestConfig | None = None,
) -> dict[str, Path]:
    """Fit and serialize the reproducible latest LightGBM challenger per horizon."""

    config = config or BacktestConfig()
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    feature_columns = model_feature_columns(features)
    origin_index = len(features) - 1
    origin = features.iloc[origin_index]
    metadata: dict[str, Any] = {}
    paths: dict[str, Path] = {}
    for horizon_days, weeks in HORIZON_WEEKS.items():
        target_column = f"target_{horizon_days}"
        training = features.iloc[: origin_index - weeks + 1].dropna(subset=[target_column]).copy()
        training = training.loc[
            pd.to_datetime(training[f"target_available_at_{horizon_days}"], utc=True)
            <= pd.to_datetime(origin["available_at"], utc=True)
        ]
        assert_causal_training(training, origin, horizon_days)
        params = _choose_lgb_params(
            features,
            origin_index,
            horizon_days,
            feature_columns,
            config,
        )
        x_train = training[feature_columns].replace([np.inf, -np.inf], np.nan).copy()
        medians = x_train.median(numeric_only=True).fillna(0.0)
        x_train = x_train.fillna(medians)
        model = lgb.LGBMRegressor(
            objective="regression_l1",
            verbosity=-1,
            random_state=config.seed,
            n_jobs=1,
            min_child_samples=max(8, min(18, len(training) // 4)),
            reg_lambda=0.8,
            reg_alpha=0.05,
            subsample=0.9,
            colsample_bytree=0.85,
            **params,
        )
        model.fit(x_train, training[target_column].astype(float))
        path = MODELS_DIR / f"lightgbm_h{horizon_days}.txt"
        model.booster_.save_model(str(path))
        paths[f"lightgbm_h{horizon_days}"] = path
        metadata[str(horizon_days)] = {
            "artifact": str(path.relative_to(ARTIFACTS_DIR.parent)).replace("\\", "/"),
            "feature_columns": feature_columns,
            "medians": {key: float(value) for key, value in medians.items()},
            "parameters": params,
            "training_rows": int(len(training)),
            "trained_until": pd.Timestamp(origin["observation_date"]).date().isoformat(),
            "target": target_column,
            "feature_importance_gain": {
                feature: float(importance)
                for feature, importance in sorted(
                    zip(
                        feature_columns,
                        model.booster_.feature_importance(importance_type="gain"),
                        strict=True,
                    ),
                    key=lambda item: item[1],
                    reverse=True,
                )
            },
            "importance_limitation": "Training-snapshot gain importance; association, not causal effect.",
        }
    metadata_path = MODELS_DIR / "lightgbm_metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    paths["lightgbm_metadata"] = metadata_path
    return paths


def save_artifacts(
    predictions: pd.DataFrame,
    metrics: pd.DataFrame,
    forecasts: list[dict[str, Any]],
    economic: dict[str, Any],
    registry: list[dict[str, Any]],
    config: BacktestConfig,
) -> dict[str, Path]:
    for path in (ARTIFACTS_DIR, FORECASTS_DIR, MODELS_DIR, REPORTS_DIR):
        path.mkdir(parents=True, exist_ok=True)
    paths = {
        "predictions": FORECASTS_DIR / "backtest_predictions.csv",
        "metrics": REPORTS_DIR / "leaderboard.csv",
        "forecasts": FORECASTS_DIR / "latest.json",
        "economic": REPORTS_DIR / "economic_backtest.json",
        "registry": MODELS_DIR / "registry.json",
        "run": ARTIFACTS_DIR / "run_metadata.json",
    }
    export = predictions.copy()
    for column in export.select_dtypes(include=["datetime", "datetimetz"]).columns:
        export[column] = export[column].astype(str)
    export.to_csv(paths["predictions"], index=False)
    metrics.to_csv(paths["metrics"], index=False)
    for key, payload in (
        ("forecasts", forecasts),
        ("economic", economic),
        ("registry", registry),
    ):
        paths[key].write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    run = {
        "run_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "validation": "expanding-window rolling-origin with inner temporal tuning",
        "config": asdict(config),
        "horizons_days": list(HORIZON_WEEKS),
        "models": BASE_MODELS,
        "observations": int(len(predictions)),
    }
    paths["run"].write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    return paths
