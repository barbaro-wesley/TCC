"""Limpeza e agregacao semanal de USD/BRL e Brent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


USD_COLUMNS = [
    "data",
    "codigo_moeda",
    "tipo",
    "moeda",
    "taxa_compra",
    "taxa_venda",
    "paridade_compra",
    "paridade_venda",
]


def find_usd_files(raw_dir: Path | str = "raw") -> list[Path]:
    """Localiza os arquivos de cotacao USD/BRL coletados do BCB."""
    return sorted(Path(raw_dir).glob("anp/*/dolar/*.csv"))


def load_usd_daily(files: Iterable[Path]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Une e padroniza as cotacoes diarias, usando a taxa de venda."""
    frames: list[pd.DataFrame] = []
    source_files = list(files)
    for path in source_files:
        frame = pd.read_csv(
            path,
            sep=";",
            header=None,
            names=USD_COLUMNS,
            dtype="string",
            encoding="utf-8-sig",
        )
        frame["arquivo_origem"] = path.name
        frames.append(frame)
    if not frames:
        raise FileNotFoundError("Nenhum arquivo de USD/BRL foi encontrado.")

    data = pd.concat(frames, ignore_index=True)
    original_rows = len(data)
    data["data"] = pd.to_datetime(data["data"], format="%d%m%Y", errors="coerce")
    for column in ["taxa_compra", "taxa_venda"]:
        data[column] = pd.to_numeric(
            data[column].str.replace(",", ".", regex=False), errors="coerce"
        )
    invalid_dates = int(data["data"].isna().sum())
    invalid_values = int(data["taxa_venda"].isna().sum())
    data = data.dropna(subset=["data", "taxa_venda"])
    duplicate_dates = int(data.duplicated("data", keep=False).sum())
    data = (
        data.groupby("data", as_index=False)
        .agg(
            usd_brl=("taxa_venda", "median"),
            usd_brl_compra=("taxa_compra", "median"),
        )
        .sort_values("data")
        .reset_index(drop=True)
    )
    quality = {
        "fonte": "Banco Central do Brasil",
        "serie": "USD/BRL - taxa de venda",
        "arquivos": len(source_files),
        "linhas_brutas": original_rows,
        "datas_invalidas": invalid_dates,
        "valores_invalidos": invalid_values,
        "linhas_em_datas_duplicadas": duplicate_dates,
        "observacoes_diarias": int(len(data)),
        "data_inicial": data["data"].min().date().isoformat(),
        "data_final": data["data"].max().date().isoformat(),
    }
    return data, quality


def load_brent_daily(path: Path | str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Le a serie EIA RBRTE da planilha XLS."""
    source_path = Path(path)
    data = pd.read_excel(
        source_path,
        sheet_name="Data 1",
        skiprows=2,
        engine="xlrd",
    )
    data = data.iloc[:, :2].copy()
    data.columns = ["data", "brent_usd_barril"]
    original_rows = len(data)
    data["data"] = pd.to_datetime(data["data"], errors="coerce")
    data["brent_usd_barril"] = pd.to_numeric(data["brent_usd_barril"], errors="coerce")
    invalid_dates = int(data["data"].isna().sum())
    invalid_values = int(data["brent_usd_barril"].isna().sum())
    data = data.dropna(subset=["data", "brent_usd_barril"])
    duplicate_dates = int(data.duplicated("data", keep=False).sum())
    data = (
        data.groupby("data", as_index=False)
        .agg(brent_usd_barril=("brent_usd_barril", "median"))
        .sort_values("data")
        .reset_index(drop=True)
    )
    quality = {
        "fonte": "U.S. Energy Information Administration (EIA)",
        "serie": "Europe Brent Spot Price FOB - RBRTE",
        "linhas_brutas": original_rows,
        "datas_invalidas": invalid_dates,
        "valores_invalidos": invalid_values,
        "linhas_em_datas_duplicadas": duplicate_dates,
        "observacoes_diarias": int(len(data)),
        "data_inicial": data["data"].min().date().isoformat(),
        "data_final": data["data"].max().date().isoformat(),
    }
    return data, quality


def aggregate_daily_to_weekly(
    daily: pd.DataFrame,
    value_column: str,
    prefix: str,
) -> pd.DataFrame:
    """Agrega dias uteis para semanas de segunda a domingo."""
    data = daily[["data", value_column]].dropna().sort_values("data").copy()
    data["retorno_diario_pct"] = data[value_column].pct_change() * 100
    data["semana_fim"] = data["data"].dt.to_period("W-SUN").dt.end_time.dt.normalize()

    grouped = data.groupby("semana_fim", as_index=False)
    weekly = grouped.agg(
        **{
            f"{prefix}_media": (value_column, "mean"),
            f"{prefix}_minimo": (value_column, "min"),
            f"{prefix}_maximo": (value_column, "max"),
            f"{prefix}_ultimo": (value_column, "last"),
            f"{prefix}_volatilidade_diaria": ("retorno_diario_pct", "std"),
            f"{prefix}_observacoes": (value_column, "size"),
        }
    )
    weekly[f"{prefix}_variacao_semanal_pct"] = weekly[f"{prefix}_ultimo"].pct_change() * 100
    return weekly.sort_values("semana_fim").reset_index(drop=True)


def weekly_coverage(
    target_weeks: pd.Series,
    external_weekly: pd.DataFrame,
) -> dict[str, Any]:
    """Verifica cobertura da fonte externa nas semanas do alvo."""
    target = pd.DataFrame({"semana_fim": pd.to_datetime(target_weeks).drop_duplicates()})
    merged = target.merge(external_weekly[["semana_fim"]], on="semana_fim", how="left", indicator=True)
    missing = merged.loc[merged["_merge"].eq("left_only"), "semana_fim"]
    return {
        "semanas_alvo": int(len(target)),
        "semanas_cobertas": int(len(target) - len(missing)),
        "semanas_ausentes": int(len(missing)),
        "datas_ausentes": [date.date().isoformat() for date in missing],
    }


def save_external_data(
    usd_daily: pd.DataFrame,
    usd_weekly: pd.DataFrame,
    brent_daily: pd.DataFrame,
    brent_weekly: pd.DataFrame,
    quality: dict[str, Any],
    output_dir: Path | str = "processed/external",
) -> dict[str, Path]:
    """Salva as series externas padronizadas e o relatorio de qualidade."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    paths = {
        "usd_diario": output_path / "usd_brl_diario.csv",
        "usd_semanal": output_path / "usd_brl_semanal.csv",
        "brent_diario": output_path / "brent_diario.csv",
        "brent_semanal": output_path / "brent_semanal.csv",
        "qualidade": output_path / "external_data_qualidade.json",
    }
    for key, frame in [
        ("usd_diario", usd_daily),
        ("usd_semanal", usd_weekly),
        ("brent_diario", brent_daily),
        ("brent_semanal", brent_weekly),
    ]:
        frame.to_csv(paths[key], index=False, encoding="utf-8", date_format="%Y-%m-%d")
    paths["qualidade"].write_text(
        json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return paths

