"""Funcoes auxiliares para a analise exploratoria da serie semanal."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def load_weekly_series(
    weekly_path: Path | str,
    quality_path: Path | str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Carrega a serie semanal e os metadados produzidos na limpeza."""
    weekly = pd.read_csv(weekly_path, parse_dates=["semana_fim"])
    quality = json.loads(Path(quality_path).read_text(encoding="utf-8"))
    return weekly.sort_values("semana_fim").reset_index(drop=True), quality


def prepare_eda(
    weekly: pd.DataFrame,
    quality: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Cria variaveis descritivas e marca semanas utilizaveis na modelagem."""
    data = weekly.copy().sort_values("semana_fim").reset_index(drop=True)
    last_collection = pd.Timestamp(quality["ultima_coleta"])
    data["semana_completa_na_fonte"] = data["semana_fim"].le(last_collection)
    data["utilizar_modelagem"] = (
        data["semana_completa_na_fonte"] & ~data["semana_sem_dados"]
    )
    data["variacao_abs"] = data["preco_medio"].diff()
    data["variacao_pct"] = data["preco_medio"].pct_change() * 100
    data["media_movel_4"] = data["preco_medio"].rolling(4).mean()
    data["media_movel_12"] = data["preco_medio"].rolling(12).mean()
    data["volatilidade_4"] = data["variacao_pct"].rolling(4).std()

    modeling = data.loc[data["utilizar_modelagem"], "variacao_pct"].dropna()
    q1, q3 = modeling.quantile([0.25, 0.75])
    iqr = q3 - q1
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    data["variacao_atipica_iqr"] = data["variacao_pct"].lt(lower) | data[
        "variacao_pct"
    ].gt(upper)

    summary = {
        "primeira_semana": data["semana_fim"].min().date().isoformat(),
        "ultima_semana": data["semana_fim"].max().date().isoformat(),
        "ultima_coleta": last_collection.date().isoformat(),
        "semanas_totais": int(len(data)),
        "semanas_para_modelagem": int(data["utilizar_modelagem"].sum()),
        "semanas_incompletas_no_fim": int((~data["semana_completa_na_fonte"]).sum()),
        "semanas_sem_dados": int(data["semana_sem_dados"].sum()),
        "limite_inferior_outlier_pct": float(lower),
        "limite_superior_outlier_pct": float(upper),
        "variacoes_atipicas": int(
            (data["variacao_atipica_iqr"] & data["utilizar_modelagem"]).sum()
        ),
    }
    return data, summary


def autocorrelation_table(data: pd.DataFrame, max_lag: int = 12) -> pd.DataFrame:
    """Calcula autocorrelacao do nivel de preco e da variacao semanal."""
    modeling = data.loc[data["utilizar_modelagem"]].copy()
    return pd.DataFrame(
        {
            "lag_semanas": range(1, max_lag + 1),
            "autocorr_preco": [
                modeling["preco_medio"].autocorr(lag=lag)
                for lag in range(1, max_lag + 1)
            ],
            "autocorr_variacao": [
                modeling["variacao_abs"].autocorr(lag=lag)
                for lag in range(1, max_lag + 1)
            ],
        }
    )


def chronological_split(
    data: pd.DataFrame, test_weeks: int = 26
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separa um holdout final; nao embaralha observacoes temporais."""
    modeling = data.loc[data["utilizar_modelagem"]].copy()
    if len(modeling) <= test_weeks:
        raise ValueError("A serie nao possui semanas suficientes para o holdout solicitado.")
    return modeling.iloc[:-test_weeks].copy(), modeling.iloc[-test_weeks:].copy()

