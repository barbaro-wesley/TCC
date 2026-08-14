"""Criacao de features temporais para prever o Diesel S10 uma semana a frente."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.eda import prepare_eda


LAGS = (1, 2, 3, 4, 12)

FEATURE_COLUMNS = [
    "preco_t",
    "preco_lag_1",
    "preco_lag_2",
    "preco_lag_3",
    "preco_lag_4",
    "preco_lag_12",
    "variacao_1_semana_pct",
    "variacao_4_semanas_pct",
    "media_movel_4",
    "media_movel_12",
    "volatilidade_4_semanas",
    "amplitude_preco_t",
    "desvio_preco_t",
    "numero_postos_t",
    "numero_municipios_t",
]

TARGET_COLUMNS = [
    "target_preco_t_mais_1",
    "target_variacao_abs",
    "target_variacao_pct",
    "target_subiu",
]


def build_univariate_features(
    weekly: pd.DataFrame,
    quality: dict[str, Any],
    test_weeks: int = 26,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Cria features conhecidas em t e targets referentes a t+1."""
    prepared, eda_summary = prepare_eda(weekly, quality)
    data = prepared.loc[prepared["utilizar_modelagem"]].copy()
    data = data.sort_values("semana_fim").reset_index(drop=True)

    features = pd.DataFrame(
        {
            "semana_referencia": data["semana_fim"],
            "semana_alvo": data["semana_fim"].shift(-1),
            "preco_t": data["preco_medio"],
            "amplitude_preco_t": data["preco_maximo"] - data["preco_minimo"],
            "desvio_preco_t": data["preco_desvio_padrao"],
            "numero_postos_t": data["numero_postos"],
            "numero_municipios_t": data["numero_municipios"],
        }
    )
    for lag in LAGS:
        features[f"preco_lag_{lag}"] = data["preco_medio"].shift(lag)

    features["variacao_1_semana_pct"] = data["preco_medio"].pct_change(1) * 100
    features["variacao_4_semanas_pct"] = data["preco_medio"].pct_change(4) * 100
    features["media_movel_4"] = data["preco_medio"].rolling(4).mean()
    features["media_movel_12"] = data["preco_medio"].rolling(12).mean()
    features["volatilidade_4_semanas"] = (
        features["variacao_1_semana_pct"].rolling(4).std()
    )

    features["target_preco_t_mais_1"] = data["preco_medio"].shift(-1)
    features["target_variacao_abs"] = (
        features["target_preco_t_mais_1"] - features["preco_t"]
    )
    features["target_variacao_pct"] = (
        features["target_variacao_abs"] / features["preco_t"] * 100
    )
    valid_target = features["target_preco_t_mais_1"].notna()
    features["target_subiu"] = pd.Series(pd.NA, index=features.index, dtype="Int64")
    features.loc[valid_target, "target_subiu"] = (
        features.loc[valid_target, "target_variacao_abs"].gt(0).astype("int64")
    )

    required = [*FEATURE_COLUMNS, *TARGET_COLUMNS, "semana_alvo"]
    before_drop = len(features)
    features = features.dropna(subset=required).reset_index(drop=True)
    features["target_subiu"] = features["target_subiu"].astype("int64")

    if len(features) <= test_weeks:
        raise ValueError("O dataset nao possui linhas suficientes para o holdout solicitado.")
    features["conjunto"] = "treino"
    features.loc[features.index[-test_weeks:], "conjunto"] = "teste"

    expected_target_date = features["semana_referencia"] + pd.Timedelta(days=7)
    if not features["semana_alvo"].eq(expected_target_date).all():
        raise ValueError("Foram encontradas datas nao consecutivas entre t e t+1.")

    metadata = {
        "versao": "univariate_v0",
        "frequencia": "semanal",
        "horizonte": "uma semana a frente",
        "linhas_semana_completa": int(len(data)),
        "linhas_descartadas_por_lag_ou_target": int(before_drop - len(features)),
        "linhas_dataset": int(len(features)),
        "linhas_treino": int(features["conjunto"].eq("treino").sum()),
        "linhas_teste": int(features["conjunto"].eq("teste").sum()),
        "primeira_semana_alvo": features["semana_alvo"].min().date().isoformat(),
        "ultima_semana_alvo": features["semana_alvo"].max().date().isoformat(),
        "features": FEATURE_COLUMNS,
        "targets": TARGET_COLUMNS,
        "regra_anti_leakage": "features em t; target e data-alvo em t+1",
        "semanas_incompletas_excluidas": eda_summary["semanas_incompletas_no_fim"],
    }
    return features, metadata


def save_feature_dataset(
    features: pd.DataFrame,
    metadata: dict[str, Any],
    output_dir: Path | str = "final",
) -> tuple[Path, Path]:
    """Salva o Dataset V0 e seus metadados."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    csv_path = output_path / "diesel_s10_rs_features_univariate_v0.csv"
    json_path = output_path / "diesel_s10_rs_features_univariate_v0_metadata.json"
    features.to_csv(csv_path, index=False, encoding="utf-8", date_format="%Y-%m-%d")
    json_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return csv_path, json_path

