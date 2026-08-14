"""Baselines univariados com avaliacao walk-forward."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


MODEL_COLUMNS = {
    "naive": "pred_naive",
    "media_movel_4": "pred_media_movel_4",
    "regressao_linear": "pred_regressao_linear",
}


def load_feature_dataset(path: Path | str) -> pd.DataFrame:
    """Carrega o Dataset V0 preservando a ordem cronologica."""
    data = pd.read_csv(path, parse_dates=["semana_referencia", "semana_alvo"])
    return data.sort_values("semana_alvo").reset_index(drop=True)


def _fit_simple_linear_regression(x: pd.Series, y: pd.Series) -> tuple[float, float]:
    """Ajusta y = intercepto + coeficiente*x por minimos quadrados."""
    design = np.column_stack([np.ones(len(x)), x.to_numpy(dtype=float)])
    intercept, coefficient = np.linalg.lstsq(
        design, y.to_numpy(dtype=float), rcond=None
    )[0]
    return float(intercept), float(coefficient)


def walk_forward_baselines(data: pd.DataFrame) -> pd.DataFrame:
    """Preve cada semana de teste usando apenas targets anteriores a ela."""
    if not {"treino", "teste"}.issubset(set(data["conjunto"])):
        raise ValueError("O dataset deve conter os conjuntos 'treino' e 'teste'.")

    test_indices = data.index[data["conjunto"].eq("teste")]
    predictions: list[dict[str, Any]] = []
    for index in test_indices:
        current = data.loc[index]
        history = data.loc[data.index < index]
        if not history["semana_alvo"].lt(current["semana_alvo"]).all():
            raise ValueError("O historico walk-forward contem informacao futura.")

        intercept, coefficient = _fit_simple_linear_regression(
            history["preco_t"], history["target_preco_t_mais_1"]
        )
        linear_prediction = intercept + coefficient * float(current["preco_t"])
        predictions.append(
            {
                "semana_referencia": current["semana_referencia"],
                "semana_alvo": current["semana_alvo"],
                "preco_t": float(current["preco_t"]),
                "preco_real": float(current["target_preco_t_mais_1"]),
                "direcao_real": int(current["target_subiu"]),
                "pred_naive": float(current["preco_t"]),
                "pred_media_movel_4": float(current["media_movel_4"]),
                "pred_regressao_linear": float(linear_prediction),
                "regressao_intercepto": intercept,
                "regressao_coeficiente": coefficient,
                "observacoes_treino": int(len(history)),
            }
        )
    return pd.DataFrame(predictions)


def evaluate_predictions(predictions: pd.DataFrame) -> pd.DataFrame:
    """Calcula metricas estatisticas e acerto da direcao para cada baseline."""
    rows: list[dict[str, Any]] = []
    actual = predictions["preco_real"].to_numpy(dtype=float)
    current = predictions["preco_t"].to_numpy(dtype=float)
    actual_direction = predictions["direcao_real"].to_numpy(dtype=int)

    for model, prediction_column in MODEL_COLUMNS.items():
        predicted = predictions[prediction_column].to_numpy(dtype=float)
        errors = predicted - actual
        predicted_direction = (predicted > current).astype(int)
        rows.append(
            {
                "modelo": model,
                "mae": float(np.mean(np.abs(errors))),
                "rmse": float(np.sqrt(np.mean(np.square(errors)))),
                "mape_pct": float(np.mean(np.abs(errors / actual)) * 100),
                "vies_medio": float(np.mean(errors)),
                "acuracia_direcao": float(np.mean(predicted_direction == actual_direction)),
            }
        )

    metrics = pd.DataFrame(rows).sort_values("mae").reset_index(drop=True)
    naive_mae = float(metrics.loc[metrics["modelo"].eq("naive"), "mae"].iloc[0])
    metrics["ganho_mae_vs_naive_pct"] = (naive_mae - metrics["mae"]) / naive_mae * 100
    return metrics


def add_error_columns(predictions: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta erros assinados para graficos e diagnosticos."""
    result = predictions.copy()
    for model, prediction_column in MODEL_COLUMNS.items():
        result[f"erro_{model}"] = result[prediction_column] - result["preco_real"]
        result[f"erro_abs_{model}"] = result[f"erro_{model}"].abs()
    return result


def save_baseline_results(
    predictions: pd.DataFrame,
    metrics: pd.DataFrame,
    output_dir: Path | str = "processed/baseline",
) -> dict[str, Path]:
    """Salva previsoes, metricas e um resumo reproduzivel."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    paths = {
        "previsoes": output_path / "baseline_previsoes_walk_forward.csv",
        "metricas": output_path / "baseline_metricas.csv",
        "resumo": output_path / "baseline_resumo.json",
    }
    predictions.to_csv(
        paths["previsoes"], index=False, encoding="utf-8", date_format="%Y-%m-%d"
    )
    metrics.to_csv(paths["metricas"], index=False, encoding="utf-8")
    best = metrics.iloc[0]
    summary = {
        "metodo_validacao": "walk-forward expansivo nas 26 semanas de teste",
        "melhor_modelo_mae": str(best["modelo"]),
        "melhor_mae": float(best["mae"]),
        "ganho_mae_vs_naive_pct": float(best["ganho_mae_vs_naive_pct"]),
        "semanas_avaliadas": int(len(predictions)),
        "observacao": "O conjunto de teste nao deve ser usado para ajustar hiperparametros.",
    }
    paths["resumo"].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return paths

