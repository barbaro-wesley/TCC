"""Limpeza da serie-alvo de preco de revenda da ANP."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


SOURCE_COLUMNS = [
    "Estado - Sigla",
    "Municipio",
    "Revenda",
    "CNPJ da Revenda",
    "Produto",
    "Data da Coleta",
    "Valor de Venda",
]

COLUMN_NAMES = {
    "Estado - Sigla": "uf",
    "Municipio": "municipio",
    "Revenda": "revenda",
    "CNPJ da Revenda": "cnpj",
    "Produto": "produto",
    "Data da Coleta": "data_coleta",
    "Valor de Venda": "preco_venda",
}


def find_revenda_files(raw_dir: Path | str = "raw") -> list[Path]:
    """Localiza os CSVs semestrais de precos automotivos da ANP."""
    raw_path = Path(raw_dir)
    return sorted(raw_path.glob("anp/*/gasolina-etanol/*.csv"))


def load_target_observations(
    files: Iterable[Path],
    uf: str = "RS",
    product: str = "DIESEL S10",
    chunksize: int = 100_000,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Le os arquivos em chunks e conserva somente o alvo solicitado."""
    selected_frames: list[pd.DataFrame] = []
    diagnostics: list[dict[str, Any]] = []
    target_uf = uf.strip().upper()
    target_product = product.strip().upper()

    for file_path in files:
        file_stats: dict[str, Any] = {
            "arquivo": str(file_path),
            "linhas_lidas": 0,
            "linhas_alvo": 0,
            "datas_invalidas": 0,
            "precos_invalidos": 0,
        }
        for chunk in pd.read_csv(
            file_path,
            sep=";",
            encoding="utf-8-sig",
            dtype="string",
            usecols=SOURCE_COLUMNS,
            chunksize=chunksize,
            low_memory=False,
        ):
            file_stats["linhas_lidas"] += len(chunk)
            state = chunk["Estado - Sigla"].str.strip().str.upper()
            item = chunk["Produto"].str.strip().str.upper()
            target = chunk.loc[state.eq(target_uf) & item.eq(target_product)].copy()
            file_stats["linhas_alvo"] += len(target)
            if target.empty:
                continue

            target = target.rename(columns=COLUMN_NAMES)
            target["uf"] = target_uf
            target["produto"] = target_product
            target["municipio"] = target["municipio"].str.strip().str.upper()
            target["revenda"] = target["revenda"].str.strip()
            target["cnpj"] = target["cnpj"].str.replace(r"\D", "", regex=True)
            target["data_coleta"] = pd.to_datetime(
                target["data_coleta"], format="%d/%m/%Y", errors="coerce"
            )
            target["preco_venda"] = pd.to_numeric(
                target["preco_venda"].str.replace(",", ".", regex=False),
                errors="coerce",
            )
            file_stats["datas_invalidas"] += int(target["data_coleta"].isna().sum())
            file_stats["precos_invalidos"] += int(target["preco_venda"].isna().sum())
            target["arquivo_origem"] = file_path.name
            selected_frames.append(target)

        diagnostics.append(file_stats)

    columns = [*COLUMN_NAMES.values(), "arquivo_origem"]
    if not selected_frames:
        return pd.DataFrame(columns=columns), pd.DataFrame(diagnostics)

    observations = pd.concat(selected_frames, ignore_index=True)
    observations = observations.dropna(subset=["data_coleta", "preco_venda"])
    observations = observations.loc[observations["preco_venda"].gt(0)].copy()
    observations = observations.sort_values(["data_coleta", "municipio", "cnpj"])
    return observations.reset_index(drop=True), pd.DataFrame(diagnostics)


def build_weekly_target(observations: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Gera uma observacao semanal, sem preencher semanas sem preco."""
    if observations.empty:
        raise ValueError("Nenhuma observacao valida foi encontrada para o alvo.")

    data = observations.copy()
    fallback_id = "SEM_CNPJ|" + data["municipio"].fillna("") + "|" + data["revenda"].fillna("")
    data["posto_id"] = data["cnpj"].where(data["cnpj"].str.len().gt(0), fallback_id)

    station_day_key = ["data_coleta", "posto_id", "municipio"]
    duplicated_key_rows = int(data.duplicated(station_day_key, keep=False).sum())
    station_day = (
        data.groupby(station_day_key, as_index=False, dropna=False)
        .agg(preco_venda=("preco_venda", "median"))
        .sort_values("data_coleta")
    )
    station_day["semana_fim"] = (
        station_day["data_coleta"].dt.to_period("W-SUN").dt.end_time.dt.normalize()
    )

    weekly = (
        station_day.groupby("semana_fim", as_index=False)
        .agg(
            preco_medio=("preco_venda", "mean"),
            preco_mediano=("preco_venda", "median"),
            preco_minimo=("preco_venda", "min"),
            preco_maximo=("preco_venda", "max"),
            preco_desvio_padrao=("preco_venda", "std"),
            numero_observacoes=("preco_venda", "size"),
            numero_postos=("posto_id", "nunique"),
            numero_municipios=("municipio", "nunique"),
        )
        .sort_values("semana_fim")
    )

    calendar = pd.DataFrame(
        {
            "semana_fim": pd.date_range(
                weekly["semana_fim"].min(), weekly["semana_fim"].max(), freq="W-SUN"
            )
        }
    )
    weekly = calendar.merge(weekly, on="semana_fim", how="left")
    weekly["semana_sem_dados"] = weekly["preco_medio"].isna()
    count_columns = ["numero_observacoes", "numero_postos", "numero_municipios"]
    weekly[count_columns] = weekly[count_columns].fillna(0).astype("int64")

    quality = {
        "primeira_coleta": data["data_coleta"].min().date().isoformat(),
        "ultima_coleta": data["data_coleta"].max().date().isoformat(),
        "observacoes_validas": int(len(data)),
        "posto_dias": int(len(station_day)),
        "linhas_em_chaves_repetidas_posto_dia": duplicated_key_rows,
        "semanas_no_calendario": int(len(weekly)),
        "semanas_sem_dados": int(weekly["semana_sem_dados"].sum()),
        "convencao_semanal": "segunda-feira a domingo; semana_fim e domingo",
        "imputacao_de_preco": "nenhuma",
    }
    return weekly, quality


def save_target_data(
    observations: pd.DataFrame,
    weekly: pd.DataFrame,
    diagnostics: pd.DataFrame,
    quality: dict[str, Any],
    output_dir: Path | str = "processed/anp/revenda",
) -> dict[str, Path]:
    """Salva dados intermediarios e relatorio de qualidade."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    paths = {
        "observacoes": output_path / "diesel_s10_rs_observacoes.csv",
        "semanal": output_path / "diesel_s10_rs_semanal.csv",
        "diagnostico": output_path / "diesel_s10_rs_diagnostico_arquivos.csv",
        "qualidade": output_path / "diesel_s10_rs_qualidade.json",
    }
    observations.to_csv(paths["observacoes"], index=False, encoding="utf-8", date_format="%Y-%m-%d")
    weekly.to_csv(paths["semanal"], index=False, encoding="utf-8", date_format="%Y-%m-%d")
    diagnostics.to_csv(paths["diagnostico"], index=False, encoding="utf-8")
    paths["qualidade"].write_text(
        json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return paths

