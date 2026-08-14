"""Leakage-safe weekly feature construction."""

from __future__ import annotations

import pandas as pd

HORIZON_WEEKS = {7: 1, 14: 2, 30: 4}


def build_features(market: pd.DataFrame) -> pd.DataFrame:
    data = market.sort_values("semana_fim").reset_index(drop=True).copy()
    price = data["preco_medio"]
    result = pd.DataFrame(
        {
            "observation_date": data["semana_fim"],
            "available_at": data["available_at"],
            "price": price,
            "price_min": data["preco_minimo"],
            "price_max": data["preco_maximo"],
            "price_dispersion": data["preco_desvio_padrao"],
            "stations": data["numero_postos"],
            "municipalities": data["numero_municipios"],
            "usd_brl": data["usd_brl_ultimo"],
            "usd_brl_weekly_return": data["usd_brl_variacao_semanal_pct"] / 100,
            "usd_brl_volatility": data["usd_brl_volatilidade_diaria"],
            "brent": data["brent_ultimo"],
            "brent_weekly_return": data["brent_variacao_semanal_pct"] / 100,
            "brent_volatility": data["brent_volatilidade_diaria"],
        }
    )
    optional_chain_features = {
        "distribution_price": "distribuicao_s10_preco_asof",
        "distribution_dispersion": "distribuicao_s10_desvio_asof",
        "producer_importer_price": "produtor_importador_s10_preco_asof",
        "retail_distribution_spread": "spread_revenda_distribuicao_asof",
        "retail_producer_spread": "spread_revenda_produtor_importador_asof",
    }
    for output_column, market_column in optional_chain_features.items():
        if market_column in data.columns:
            result[output_column] = data[market_column]
    for lag in (1, 2, 3, 4, 8, 12):
        result[f"price_lag_{lag}"] = price.shift(lag)
    result["price_change_1"] = price.diff(1)
    result["price_return_1"] = price.pct_change(1)
    result["price_return_4"] = price.pct_change(4)
    result["price_acceleration"] = result["price_change_1"].diff(1)
    for window in (4, 8, 12):
        result[f"price_ma_{window}"] = price.rolling(window).mean()
        result[f"price_std_{window}"] = price.rolling(window).std()
    result["price_ema_4"] = price.ewm(span=4, adjust=False).mean()
    result["price_rolling_min_8"] = price.rolling(8).min()
    result["price_rolling_max_8"] = price.rolling(8).max()
    result["price_momentum_4"] = price - price.shift(4)
    result["landed_oil_brl"] = result["brent"] * result["usd_brl"]
    result["oil_fx_impulse"] = result["brent_weekly_return"] + result["usd_brl_weekly_return"]
    result["sampling_ratio"] = result["stations"] / result["stations"].rolling(12).median()
    for lag in (1, 2, 4):
        result[f"brent_lag_{lag}"] = result["brent"].shift(lag)
        result[f"usd_brl_lag_{lag}"] = result["usd_brl"].shift(lag)
        if "distribution_price" in result:
            result[f"distribution_lag_{lag}"] = result["distribution_price"].shift(lag)
        if "producer_importer_price" in result:
            result[f"producer_importer_lag_{lag}"] = result["producer_importer_price"].shift(lag)
    for days, weeks in HORIZON_WEEKS.items():
        result[f"target_{days}"] = price.shift(-weeks)
        result[f"target_date_{days}"] = data["semana_fim"].shift(-weeks)
        result[f"target_available_at_{days}"] = data["available_at"].shift(-weeks)
    return result


def model_feature_columns(features: pd.DataFrame) -> list[str]:
    blocked_prefixes = ("target_",)
    blocked = {"observation_date", "available_at", "price_min", "price_max"}
    return [
        column
        for column in features.columns
        if column not in blocked
        and not column.startswith(blocked_prefixes)
        and pd.api.types.is_numeric_dtype(features[column])
    ]


def assert_causal_training(train: pd.DataFrame, origin: pd.Series, horizon_days: int) -> None:
    target_available = train[f"target_available_at_{horizon_days}"]
    if target_available.isna().any():
        raise AssertionError("Training contains targets that were not yet published")
    if target_available.gt(origin["available_at"]).any():
        raise AssertionError("Future publication leakage detected in training fold")
    if train["observation_date"].ge(origin["observation_date"]).any():
        raise AssertionError("Forecast origin contaminated the training fold")


def latest_driver_snapshot(features: pd.DataFrame) -> list[dict[str, float | str]]:
    latest = features.iloc[-1]
    previous = features.iloc[-2]
    drivers = [
        {
            "id": "brent",
            "label": "Brent",
            "value": float(latest["brent"]),
            "unit": "US$/bbl",
            "change_pct": float((latest["brent"] / previous["brent"] - 1) * 100),
        },
        {
            "id": "usd_brl",
            "label": "USD/BRL",
            "value": float(latest["usd_brl"]),
            "unit": "R$/US$",
            "change_pct": float((latest["usd_brl"] / previous["usd_brl"] - 1) * 100),
        },
        {
            "id": "diesel_momentum",
            "label": "Momentum S10 (4 sem.)",
            "value": float(latest["price_momentum_4"]),
            "unit": "R$/L",
            "change_pct": float(latest["price_return_4"] * 100),
        },
    ]
    return drivers
