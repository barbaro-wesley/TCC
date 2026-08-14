"""Build the causal national Diesel S10 gold dataset from local snapshots.

The pipeline deliberately does not download or mutate raw data.  It reads the
five ANP retail-price semester files, collapses repeated measurements to one
station-day median, aggregates the national target by ``W-SUN`` week and joins
the already-normalized weekly USD/BRL and Brent snapshots.

Availability is intentionally conservative and explicit:

* ANP retail target: end of day eight calendar days after the reference Sunday;
* BCB USD/BRL: end of the following calendar day;
* EIA Brent: end of the third calendar day after the reference Sunday.
* ANP distribution: end of day fourteen days after source period end (unverified);
* ANP producer/importer: end of day twelve days after source period end, as
  estimated by the note embedded in the official workbook.

Except for the producer/importer workbook's estimated schedule, these are
implementation assumptions, not claims about official service-level agreements.
They are persisted in every output and in the quality report.  Cost-driver
features use an as-of join against target availability and never a future row.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

PIPELINE_VERSION = "national_weekly_v1"
TIMEZONE = "America/Sao_Paulo"
TARGET_PRODUCT = "DIESEL S10"
TARGET_UNIT_RAW = "r$ / litro"
TARGET_UNIT = "BRL/L"
DISTRIBUTION_PRODUCT = "ÓLEO DIESEL B S10 - COMUM"
PRODUCER_PRODUCT = "Óleo Diesel S-10 (R$/litro)"
SOURCE_URL = (
    "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/"
    "serie-historica-de-precos-de-combustiveis"
)

SOURCE_COLUMNS = [
    "Estado - Sigla",
    "Municipio",
    "Revenda",
    "CNPJ da Revenda",
    "Produto",
    "Data da Coleta",
    "Valor de Venda",
    "Valor de Compra",
    "Unidade de Medida",
]

USD_COLUMNS = [
    "semana_fim",
    "usd_brl_media",
    "usd_brl_minimo",
    "usd_brl_maximo",
    "usd_brl_ultimo",
    "usd_brl_volatilidade_diaria",
    "usd_brl_observacoes",
    "usd_brl_variacao_semanal_pct",
]

BRENT_COLUMNS = [
    "semana_fim",
    "brent_media",
    "brent_minimo",
    "brent_maximo",
    "brent_ultimo",
    "brent_volatilidade_diaria",
    "brent_observacoes",
    "brent_variacao_semanal_pct",
]

COST_DRIVER_COLUMNS = [
    "distribuicao_s10_preco_asof",
    "distribuicao_s10_desvio_asof",
    "distribuicao_s10_observacao_inicio_asof",
    "distribuicao_s10_observacao_fim_asof",
    "distribuicao_s10_available_at_asof",
    "distribuicao_s10_idade_dias",
    "distribuicao_s10_lag_assumido_dias",
    "produtor_importador_s10_preco_asof",
    "produtor_importador_s10_observacao_inicio_asof",
    "produtor_importador_s10_observacao_fim_asof",
    "produtor_importador_s10_available_at_asof",
    "produtor_importador_s10_idade_dias",
    "produtor_importador_s10_lag_dias",
    "spread_revenda_distribuicao_asof",
    "spread_revenda_produtor_importador_asof",
]


def sha256(path: Path) -> str:
    """Return a streaming SHA-256 digest for provenance."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compact_json(value: Any) -> str:
    """Serialize stable UTF-8 JSON suitable for a CSV metadata cell."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def utc_iso(series: pd.Series) -> pd.Series:
    """Format a timezone-aware series as strict UTC ISO-8601."""
    return pd.to_datetime(series, utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def date_iso(series: pd.Series) -> pd.Series:
    """Format a date-like series without an accidental timezone conversion."""
    return pd.to_datetime(series).dt.strftime("%Y-%m-%d")


def normalize_ingested_at(value: str | None) -> tuple[pd.Timestamp, str]:
    """Normalize the run timestamp to UTC with second precision."""
    stamp = pd.Timestamp(value) if value else pd.Timestamp(datetime.now(UTC))
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    stamp = stamp.floor("s")
    return stamp, stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def availability_at_end_of_day(
    week_end: pd.Series, lag_days: int
) -> pd.Series:
    """Return end-of-day availability in UTC after a conservative local lag."""
    local = (
        pd.to_datetime(week_end)
        + pd.Timedelta(days=lag_days)
        + pd.Timedelta(hours=23, minutes=59, seconds=59)
    )
    return local.dt.tz_localize(TIMEZONE).dt.tz_convert("UTC")


def normalize_text(series: pd.Series) -> pd.Series:
    """Normalize Unicode, trim surrounding space and collapse internal space."""
    return (
        series.astype("string")
        .str.normalize("NFKC")
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )


def discover_retail_files(root: Path) -> list[Path]:
    """Find and validate the five local ANP semester snapshots."""
    files = sorted(
        root.glob("raw/anp/*/gasolina-etanol/Preços semestrais - AUTOMOTIVOS_*.csv")
    )
    if len(files) != 5:
        relative = [str(path.relative_to(root)) for path in files]
        raise FileNotFoundError(
            f"Expected exactly five ANP semester CSVs, found {len(files)}: {relative}"
        )
    return files


def discover_optional_retail_caches(root: Path) -> list[dict[str, Any]]:
    """Return known official ANP cache extensions when present.

    Priority is used only to resolve the same station-day appearing in multiple
    snapshots.  The rolling four-week snapshot is the newest known vintage.
    """
    candidates = [
        {
            "path": root / "data/cache/anp/2026-07-diesel-gnv.csv",
            "snapshot_kind": "official_month_cache",
            "priority": 1,
            "published_on": None,
        },
        {
            "path": (
                root
                / "data/cache/anp/ultimas-4-semanas-diesel-gnv-2026-08-07.csv"
            ),
            "snapshot_kind": "official_rolling_four_weeks",
            "priority": 2,
            "published_on": "2026-08-07",
        },
    ]
    return [item for item in candidates if item["path"].exists()]


def load_retail_target(
    root: Path,
    files: Iterable[Path],
    chunksize: int,
    optional_caches: Iterable[dict[str, Any]] = (),
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Read all ANP files in chunks and keep validated national Diesel S10 rows."""
    selected: list[pd.DataFrame] = []
    diagnostics: list[dict[str, Any]] = []

    sources = [
        {
            "path": path,
            "snapshot_kind": "official_semester_snapshot",
            "priority": 0,
            "published_on": None,
        }
        for path in files
    ]
    sources.extend(optional_caches)

    for source in sources:
        path = source["path"]
        stats: dict[str, Any] = {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "snapshot_kind": source["snapshot_kind"],
            "snapshot_priority": int(source["priority"]),
            "published_on": source["published_on"],
            "raw_rows": 0,
            "blank_rows": 0,
            "nonblank_rows": 0,
            "target_rows": 0,
            "purchase_value_missing_rows": 0,
        }
        target_parts: list[pd.DataFrame] = []

        for chunk in pd.read_csv(
            path,
            sep=";",
            encoding="utf-8-sig",
            dtype="string",
            usecols=SOURCE_COLUMNS,
            chunksize=chunksize,
            low_memory=False,
        ):
            stats["raw_rows"] += int(len(chunk))
            blank = chunk.isna().all(axis=1)
            stats["blank_rows"] += int(blank.sum())
            stats["purchase_value_missing_rows"] += int(
                chunk["Valor de Compra"].isna().sum()
            )
            nonblank = chunk.loc[~blank].copy()
            stats["nonblank_rows"] += int(len(nonblank))

            product = normalize_text(nonblank["Produto"]).str.upper()
            target = nonblank.loc[product.eq(TARGET_PRODUCT)].copy()
            stats["target_rows"] += int(len(target))
            if not target.empty:
                target_parts.append(target)

        if target_parts:
            file_target = pd.concat(target_parts, ignore_index=True)
            file_target["source_file"] = path.relative_to(root).as_posix()
            file_target["source_priority"] = int(source["priority"])
            file_target["source_published_on"] = source["published_on"]
            selected.append(file_target)
        diagnostics.append(stats)

    if not selected:
        raise ValueError("No national Diesel S10 observations were found in the ANP snapshots")

    target = pd.concat(selected, ignore_index=True)
    target = target.rename(
        columns={
            "Estado - Sigla": "state_code",
            "Municipio": "municipality_name",
            "Revenda": "station_name",
            "CNPJ da Revenda": "station_id",
            "Data da Coleta": "observation_date",
            "Valor de Venda": "value_raw",
            "Unidade de Medida": "unit_raw",
        }
    )
    target["state_code"] = normalize_text(target["state_code"]).str.upper()
    target["municipality_name"] = normalize_text(target["municipality_name"]).str.upper()
    target["station_name"] = normalize_text(target["station_name"])
    target["station_id"] = target["station_id"].str.replace(r"\D", "", regex=True)
    target["observation_date"] = pd.to_datetime(
        target["observation_date"], format="%d/%m/%Y", errors="coerce"
    )
    target["value"] = pd.to_numeric(
        target["value_raw"].str.replace(",", ".", regex=False), errors="coerce"
    )
    target["normalized_unit"] = normalize_text(target["unit_raw"]).str.casefold()
    target["source_published_on"] = pd.to_datetime(
        target["source_published_on"], errors="coerce"
    )

    invalid_units = target.loc[
        target["normalized_unit"].ne(TARGET_UNIT_RAW), "unit_raw"
    ].value_counts(dropna=False)
    if not invalid_units.empty:
        raise ValueError(f"Unexpected unit in Diesel S10 rows: {invalid_units.to_dict()}")
    if target["observation_date"].isna().any():
        raise ValueError(
            f"Invalid Diesel S10 dates: {int(target['observation_date'].isna().sum())}"
        )
    if target["value"].isna().any():
        raise ValueError(f"Invalid Diesel S10 prices: {int(target['value'].isna().sum())}")
    if not target["value"].between(1, 20).all():
        bad = target.loc[~target["value"].between(1, 20), "value"]
        raise ValueError(f"Diesel S10 prices outside BRL 1-20/L: {bad.tolist()[:10]}")
    if not target["station_id"].str.fullmatch(r"\d{14}", na=False).all():
        bad = int((~target["station_id"].str.fullmatch(r"\d{14}", na=False)).sum())
        raise ValueError(f"Invalid or missing 14-digit station CNPJ: {bad}")
    if not target["state_code"].str.fullmatch(r"[A-Z]{2}", na=False).all():
        raise ValueError("Invalid or missing state code in Diesel S10 rows")
    if target["municipality_name"].isna().any():
        raise ValueError("Missing municipality in Diesel S10 rows")

    return target, diagnostics


def station_day_medians(target: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Resolve snapshot overlap, then collapse every station-day to its median."""
    keys = ["observation_date", "state_code", "municipality_name", "station_id"]
    source_keys = [
        *keys,
        "source_file",
        "source_priority",
        "source_published_on",
    ]
    per_snapshot = (
        target.sort_values([*source_keys, "station_name"])
        .groupby(source_keys, as_index=False, dropna=False)
        .agg(
            station_name=("station_name", "first"),
            value=("value", "median"),
            raw_record_count=("value", "size"),
        )
    )
    overlap_rows = int(per_snapshot.duplicated(keys, keep=False).sum())
    overlap_extra = int(per_snapshot.duplicated(keys, keep="last").sum())
    conflicting_overlap_keys = int(
        per_snapshot.groupby(keys, dropna=False)["value"].nunique().gt(1).sum()
    )
    source_counts_before = {
        str(key): int(value) for key, value in target["source_file"].value_counts().items()
    }
    station_day = (
        per_snapshot.sort_values(
            [*keys, "source_priority", "source_published_on", "source_file"],
            na_position="first",
        )
        .drop_duplicates(keys, keep="last")
        .copy()
    )
    source_counts_after = {
        str(key): int(value)
        for key, value in station_day["source_file"].value_counts().items()
    }
    station_day["week_end"] = (
        station_day["observation_date"]
        .dt.to_period("W-SUN")
        .dt.end_time.dt.normalize()
    )
    station_day["municipality_id"] = (
        station_day["state_code"] + "|" + station_day["municipality_name"]
    )
    station_day = station_day.sort_values(keys).reset_index(drop=True)
    stats = {
        "raw_target_rows": int(len(target)),
        "station_day_rows": int(len(station_day)),
        "snapshot_overlap_rows": overlap_rows,
        "snapshot_overlap_extra_rows_removed": overlap_extra,
        "snapshot_overlap_conflicting_keys": conflicting_overlap_keys,
        "target_rows_by_source_before_deduplication": source_counts_before,
        "station_days_by_source_after_deduplication": source_counts_after,
        "rows_in_repeated_station_days": int(
            station_day.loc[station_day["raw_record_count"].gt(1), "raw_record_count"].sum()
        ),
        "extra_rows_collapsed": int(len(target) - len(station_day)),
    }
    return station_day, stats


def aggregate_national_weekly(
    station_day: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the complete national target and return excluded partial weeks."""
    weekly = (
        station_day.groupby("week_end", as_index=False)
        .agg(
            preco_medio=("value", "mean"),
            preco_mediano=("value", "median"),
            preco_minimo=("value", "min"),
            preco_maximo=("value", "max"),
            preco_desvio_padrao=("value", "std"),
            numero_observacoes=("value", "size"),
            numero_postos=("station_id", "nunique"),
            numero_municipios=("municipality_id", "nunique"),
            numero_ufs=("state_code", "nunique"),
        )
        .sort_values("week_end")
        .reset_index(drop=True)
    )
    last_observation = station_day["observation_date"].max().normalize()
    complete = weekly["week_end"].le(last_observation)
    excluded = weekly.loc[~complete].copy()
    weekly = weekly.loc[complete].copy().reset_index(drop=True)
    weekly["semana_inicio"] = weekly["week_end"] - pd.Timedelta(days=6)
    weekly["semana_sem_dados"] = False
    weekly["is_complete_week"] = True
    return weekly, excluded


def load_external_weekly(root: Path) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    """Combine historical USD closes with an optional official BCB JSON cache."""
    usd_path = root / "processed/external/usd_brl_diario.csv"
    brent_path = root / "processed/external/brent_semanal.csv"
    missing = [path for path in (usd_path, brent_path) if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing processed external snapshots: {missing}")

    usd_history = pd.read_csv(usd_path, parse_dates=["data"])
    required_daily = {"data", "usd_brl", "usd_brl_compra"}
    missing_usd_daily = sorted(required_daily - set(usd_history.columns))
    if missing_usd_daily:
        raise ValueError(f"Historical USD daily snapshot missing: {missing_usd_daily}")
    usd_history = usd_history[["data", "usd_brl", "usd_brl_compra"]].copy()
    usd_history["source_priority"] = 0
    usd_history["source_timestamp"] = pd.NaT
    usd_history["source_file"] = usd_path.relative_to(root).as_posix()

    bcb_cache_path = (
        root / "data/cache/bcb/ptax-usd-2026-07-01_2026-08-13.json"
    )
    usd_parts = [usd_history]
    bcb_provenance: list[dict[str, Any]] = []
    bcb_closing_rows = 0
    if bcb_cache_path.exists():
        payload = json.loads(bcb_cache_path.read_text(encoding="utf-8"))
        if not isinstance(payload.get("value"), list):
            raise ValueError("BCB PTAX cache does not contain an OData value array")
        cache_raw = pd.DataFrame(payload["value"])
        cache_schema = {
            "cotacaoCompra",
            "cotacaoVenda",
            "dataHoraCotacao",
            "tipoBoletim",
        }
        missing_cache = sorted(cache_schema - set(cache_raw.columns))
        if missing_cache:
            raise ValueError(f"BCB PTAX cache missing columns: {missing_cache}")
        bulletin = normalize_text(cache_raw["tipoBoletim"]).str.casefold()
        cache = cache_raw.loc[bulletin.eq("fechamento")].copy()
        cache["source_timestamp"] = pd.to_datetime(
            cache["dataHoraCotacao"], errors="coerce"
        )
        cache["data"] = cache["source_timestamp"].dt.normalize()
        cache["usd_brl"] = pd.to_numeric(cache["cotacaoVenda"], errors="coerce")
        cache["usd_brl_compra"] = pd.to_numeric(
            cache["cotacaoCompra"], errors="coerce"
        )
        if cache[["data", "usd_brl", "usd_brl_compra"]].isna().any().any():
            raise ValueError("Invalid date or value in BCB PTAX closing cache")
        cache = cache.sort_values("source_timestamp")
        if cache["data"].duplicated().any():
            raise ValueError("More than one PTAX closing bulletin for a cached date")
        if not cache["usd_brl"].between(1, 15).all():
            raise ValueError("Implausible PTAX closing quote in cache")
        cache["source_priority"] = 1
        cache["source_file"] = bcb_cache_path.relative_to(root).as_posix()
        cache = cache[
            [
                "data",
                "usd_brl",
                "usd_brl_compra",
                "source_priority",
                "source_timestamp",
                "source_file",
            ]
        ]
        usd_parts.append(cache)
        bcb_closing_rows = int(len(cache))
        bcb_provenance.append(
            {
                "path": bcb_cache_path.relative_to(root).as_posix(),
                "bytes": bcb_cache_path.stat().st_size,
                "sha256": sha256(bcb_cache_path),
                "snapshot_kind": "official_bcb_odata_cache",
                "odata_context": payload.get("@odata.context"),
                "raw_bulletins": int(len(cache_raw)),
                "closing_bulletins": int(len(cache)),
                "observation_start": cache["data"].min().date().isoformat(),
                "observation_end": cache["data"].max().date().isoformat(),
                "first_closing_timestamp": cache["source_timestamp"].min().isoformat(),
                "last_closing_timestamp": cache["source_timestamp"].max().isoformat(),
            }
        )

    usd_all = pd.concat(usd_parts, ignore_index=True)
    usd_all["data"] = pd.to_datetime(usd_all["data"], errors="coerce")
    duplicate_date_rows = int(usd_all.duplicated("data", keep=False).sum())
    conflicting_dates = int(
        usd_all.groupby("data")[["usd_brl", "usd_brl_compra"]]
        .nunique()
        .max(axis=1)
        .gt(1)
        .sum()
    )
    usd_daily = (
        usd_all.sort_values(
            ["data", "source_priority", "source_timestamp"], na_position="first"
        )
        .drop_duplicates("data", keep="last")
        .sort_values("data")
        .reset_index(drop=True)
    )
    if usd_daily["data"].duplicated().any():
        raise AssertionError("USD daily deduplication failed")
    usd_daily["retorno_diario_pct"] = usd_daily["usd_brl"].pct_change() * 100
    usd_daily["semana_fim"] = (
        usd_daily["data"].dt.to_period("W-SUN").dt.end_time.dt.normalize()
    )
    usd = (
        usd_daily.groupby("semana_fim", as_index=False)
        .agg(
            usd_brl_media=("usd_brl", "mean"),
            usd_brl_minimo=("usd_brl", "min"),
            usd_brl_maximo=("usd_brl", "max"),
            usd_brl_ultimo=("usd_brl", "last"),
            usd_brl_volatilidade_diaria=("retorno_diario_pct", "std"),
            usd_brl_observacoes=("usd_brl", "size"),
        )
        .sort_values("semana_fim")
        .reset_index(drop=True)
    )
    usd["usd_brl_variacao_semanal_pct"] = usd["usd_brl_ultimo"].pct_change() * 100
    brent = pd.read_csv(brent_path, parse_dates=["semana_fim"])
    missing_usd = sorted(set(USD_COLUMNS) - set(usd.columns))
    missing_brent = sorted(set(BRENT_COLUMNS) - set(brent.columns))
    if missing_usd or missing_brent:
        raise ValueError(
            f"Unexpected external schema; USD missing={missing_usd}, Brent missing={missing_brent}"
        )
    if usd["semana_fim"].duplicated().any() or brent["semana_fim"].duplicated().any():
        raise ValueError("Duplicate week in a processed external snapshot")

    provenance = [
        {
            "path": usd_path.relative_to(root).as_posix(),
            "bytes": usd_path.stat().st_size,
            "sha256": sha256(usd_path),
            "snapshot_kind": "normalized_historical_daily",
            "rows": int(len(usd_history)),
            "observation_start": usd_history["data"].min().date().isoformat(),
            "observation_end": usd_history["data"].max().date().isoformat(),
            "combined_daily_rows": int(len(usd_daily)),
            "combined_weekly_rows": int(len(usd)),
            "combined_observation_end": usd_daily["data"].max().date().isoformat(),
            "cache_closing_rows": bcb_closing_rows,
            "overlap_rows": duplicate_date_rows,
            "overlap_conflicting_dates": conflicting_dates,
        },
        {
            "path": brent_path.relative_to(root).as_posix(),
            "bytes": brent_path.stat().st_size,
            "sha256": sha256(brent_path),
            "rows": int(len(brent)),
            "observation_start": brent["semana_fim"].min().date().isoformat(),
            "observation_end": brent["semana_fim"].max().date().isoformat(),
        },
        *bcb_provenance,
    ]
    return usd[USD_COLUMNS], brent[BRENT_COLUMNS], provenance


def validate_weekly_periods(frame: pd.DataFrame, source_name: str) -> None:
    """Fail on duplicated, malformed or non-contiguous weekly source periods."""
    if frame.empty:
        raise ValueError(f"No target rows found in {source_name}")
    if frame.duplicated(["period_start", "period_end"]).any():
        raise ValueError(f"Duplicate target period in {source_name}")
    if not (frame["period_end"] - frame["period_start"]).dt.days.eq(6).all():
        raise ValueError(f"Non-seven-day target period in {source_name}")
    starts = frame["period_start"].sort_values().reset_index(drop=True)
    if not starts.diff().dropna().dt.days.eq(7).all():
        raise ValueError(f"Weekly gaps or overlaps in {source_name}")


def load_anp_cost_drivers(
    root: Path,
    distribution_lag_days: int,
    producer_lag_days: int,
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    """Parse and validate national ANP distribution and producer/importer S10."""
    distribution_path = (
        root / "raw/anp/distribuicao/brasil_semanal/combustiveis-liquidos-brasil.xlsx"
    )
    producer_path = (
        root / "raw/anp/produtor_importador/precos-medios-ponderados-semanais-2013.xls"
    )
    missing = [path for path in (distribution_path, producer_path) if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing local ANP cost-driver workbooks: {missing}")

    distribution_raw = pd.read_excel(
        distribution_path,
        sheet_name="BRASIL",
        header=8,
        engine="openpyxl",
    )
    distribution_schema = [
        "DATA INICIAL",
        "DATA FINAL",
        "PRODUTO",
        "UNIDADE DE MEDIDA",
        "PREÇO MÉDIO DE DISTRIBUIÇÃO",
        "DESVIO PADRÃO",
    ]
    missing_columns = sorted(set(distribution_schema) - set(distribution_raw.columns))
    if missing_columns:
        raise ValueError(f"Distribution workbook missing columns: {missing_columns}")
    distribution_valid_rows = int(
        pd.to_datetime(distribution_raw["DATA FINAL"], errors="coerce").notna().sum()
    )
    distribution_product = normalize_text(distribution_raw["PRODUTO"]).str.upper()
    distribution = distribution_raw.loc[
        distribution_product.eq(DISTRIBUTION_PRODUCT), distribution_schema
    ].copy()
    distribution = distribution.rename(
        columns={
            "DATA INICIAL": "period_start",
            "DATA FINAL": "period_end",
            "UNIDADE DE MEDIDA": "unit_raw",
            "PREÇO MÉDIO DE DISTRIBUIÇÃO": "value",
            "DESVIO PADRÃO": "dispersion",
        }
    )
    distribution["period_start"] = pd.to_datetime(
        distribution["period_start"], errors="coerce"
    )
    distribution["period_end"] = pd.to_datetime(
        distribution["period_end"], errors="coerce"
    )
    distribution["value"] = pd.to_numeric(distribution["value"], errors="coerce")
    distribution["dispersion"] = pd.to_numeric(
        distribution["dispersion"], errors="coerce"
    )
    distribution["unit_normalized"] = normalize_text(
        distribution["unit_raw"]
    ).str.casefold()
    if not distribution["unit_normalized"].eq("r$/l").all():
        raise ValueError(
            "Unexpected unit in national Diesel S10 distribution workbook: "
            f"{distribution['unit_raw'].value_counts(dropna=False).to_dict()}"
        )
    if distribution[
        ["period_start", "period_end", "value", "dispersion"]
    ].isna().any().any():
        raise ValueError("Invalid date or numeric value in Diesel S10 distribution rows")
    if not distribution["value"].between(1, 20).all():
        raise ValueError("Implausible Diesel S10 distribution price")
    distribution = distribution.sort_values("period_start").reset_index(drop=True)
    validate_weekly_periods(distribution, "ANP distribution")
    distribution["observation_date"] = distribution["period_end"]
    distribution["available_at"] = availability_at_end_of_day(
        distribution["observation_date"], distribution_lag_days
    )

    producer_raw = pd.read_excel(
        producer_path,
        sheet_name="Preços Produtor e Importador",
        header=None,
        engine="xlrd",
    )
    if producer_raw.shape[1] < 9:
        raise ValueError(
            f"Producer/importer workbook has {producer_raw.shape[1]} columns; expected at least 9"
        )
    producer_text = [
        str(value)
        for value in producer_raw.astype("string").stack().dropna().tolist()
    ]
    lag_evidence = next(
        (text for text in producer_text if "doze dias" in text.casefold()), None
    )
    if lag_evidence is None:
        raise ValueError("The producer/importer workbook no longer contains its 12-day lag note")
    updated_label = next(
        (text for text in producer_text if "atualizado em" in text.casefold()), None
    )

    producer = producer_raw.iloc[9:, :9].copy()
    producer.columns = [
        "product",
        "period_start",
        "period_end",
        "north",
        "northeast",
        "center_west",
        "south",
        "southeast",
        "value",
    ]
    producer_product = normalize_text(producer["product"])
    producer = producer.loc[producer_product.eq(PRODUCER_PRODUCT)].copy()
    producer["period_start"] = pd.to_datetime(producer["period_start"], errors="coerce")
    producer["period_end"] = pd.to_datetime(producer["period_end"], errors="coerce")
    producer["value"] = pd.to_numeric(producer["value"], errors="coerce")
    if producer[["period_start", "period_end", "value"]].isna().any().any():
        raise ValueError("Invalid national value or date in Diesel S10 producer/importer rows")
    if not producer["value"].between(0.5, 20).all():
        raise ValueError("Implausible Diesel S10 producer/importer price")
    producer = producer.sort_values("period_start").reset_index(drop=True)
    validate_weekly_periods(producer, "ANP producer/importer")
    producer["observation_date"] = producer["period_end"]
    producer["available_at"] = availability_at_end_of_day(
        producer["observation_date"], producer_lag_days
    )

    provenance = [
        {
            "path": distribution_path.relative_to(root).as_posix(),
            "bytes": distribution_path.stat().st_size,
            "sha256": sha256(distribution_path),
            "sheet": "BRASIL",
            "workbook_rows_after_header": int(len(distribution_raw)),
            "valid_data_rows": distribution_valid_rows,
            "target_rows": int(len(distribution)),
            "product": DISTRIBUTION_PRODUCT,
            "unit": "BRL/L",
            "observation_start": distribution["period_start"].min().date().isoformat(),
            "observation_end": distribution["period_end"].max().date().isoformat(),
            "publication_lag_days": distribution_lag_days,
            "publication_lag_status": "assumed_unverified",
        },
        {
            "path": producer_path.relative_to(root).as_posix(),
            "bytes": producer_path.stat().st_size,
            "sha256": sha256(producer_path),
            "sheet": "Preços Produtor e Importador",
            "workbook_rows": int(len(producer_raw)),
            "target_rows": int(len(producer)),
            "product": PRODUCER_PRODUCT,
            "unit": "BRL/L excluding ICMS",
            "observation_start": producer["period_start"].min().date().isoformat(),
            "observation_end": producer["period_end"].max().date().isoformat(),
            "publication_lag_days": producer_lag_days,
            "publication_lag_status": "official_estimate_in_workbook",
            "publication_lag_evidence": lag_evidence,
            "workbook_updated_label": updated_label,
        },
    ]
    return distribution, producer, provenance


def align_cost_drivers_asof(
    market: pd.DataFrame,
    distribution: pd.DataFrame,
    producer: pd.DataFrame,
    distribution_lag_days: int,
    producer_lag_days: int,
) -> pd.DataFrame:
    """Attach only the most recent cost observations known at target availability."""
    result = market.copy().reset_index(drop=True)
    left = result[["semana_fim", "anp_available_at"]].copy()
    left["_market_row"] = left.index
    left = left.sort_values("anp_available_at")

    distribution_right = distribution[
        ["period_start", "period_end", "available_at", "value", "dispersion"]
    ].rename(
        columns={
            "period_start": "source_period_start",
            "period_end": "source_period_end",
            "available_at": "source_available_at",
            "value": "source_value",
            "dispersion": "source_dispersion",
        }
    ).sort_values("source_available_at")
    distribution_asof = pd.merge_asof(
        left,
        distribution_right,
        left_on="anp_available_at",
        right_on="source_available_at",
        direction="backward",
        allow_exact_matches=True,
    ).sort_values("_market_row")
    result["distribuicao_s10_preco_asof"] = distribution_asof["source_value"].to_numpy()
    result["distribuicao_s10_desvio_asof"] = distribution_asof[
        "source_dispersion"
    ].to_numpy()
    result["distribuicao_s10_observacao_inicio_asof"] = distribution_asof[
        "source_period_start"
    ].to_numpy()
    result["distribuicao_s10_observacao_fim_asof"] = distribution_asof[
        "source_period_end"
    ].to_numpy()
    result["distribuicao_s10_available_at_asof"] = distribution_asof[
        "source_available_at"
    ].to_numpy()
    result["distribuicao_s10_idade_dias"] = (
        result["semana_fim"] - result["distribuicao_s10_observacao_fim_asof"]
    ).dt.days
    result["distribuicao_s10_lag_assumido_dias"] = distribution_lag_days

    producer_right = producer[
        ["period_start", "period_end", "available_at", "value"]
    ].rename(
        columns={
            "period_start": "source_period_start",
            "period_end": "source_period_end",
            "available_at": "source_available_at",
            "value": "source_value",
        }
    ).sort_values("source_available_at")
    producer_asof = pd.merge_asof(
        left,
        producer_right,
        left_on="anp_available_at",
        right_on="source_available_at",
        direction="backward",
        allow_exact_matches=True,
    ).sort_values("_market_row")
    result["produtor_importador_s10_preco_asof"] = producer_asof[
        "source_value"
    ].to_numpy()
    result["produtor_importador_s10_observacao_inicio_asof"] = producer_asof[
        "source_period_start"
    ].to_numpy()
    result["produtor_importador_s10_observacao_fim_asof"] = producer_asof[
        "source_period_end"
    ].to_numpy()
    result["produtor_importador_s10_available_at_asof"] = producer_asof[
        "source_available_at"
    ].to_numpy()
    result["produtor_importador_s10_idade_dias"] = (
        result["semana_fim"]
        - result["produtor_importador_s10_observacao_fim_asof"]
    ).dt.days
    result["produtor_importador_s10_lag_dias"] = producer_lag_days
    result["spread_revenda_distribuicao_asof"] = (
        result["preco_medio"] - result["distribuicao_s10_preco_asof"]
    )
    result["spread_revenda_produtor_importador_asof"] = (
        result["preco_medio"] - result["produtor_importador_s10_preco_asof"]
    )

    required = [
        "distribuicao_s10_preco_asof",
        "distribuicao_s10_available_at_asof",
        "produtor_importador_s10_preco_asof",
        "produtor_importador_s10_available_at_asof",
    ]
    if result[required].isna().any().any():
        raise ValueError("Cost-driver as-of coverage is incomplete for the target window")
    if not result["distribuicao_s10_available_at_asof"].le(
        result["anp_available_at"]
    ).all():
        raise AssertionError("Future distribution release entered an as-of feature")
    if not result["produtor_importador_s10_available_at_asof"].le(
        result["anp_available_at"]
    ).all():
        raise AssertionError("Future producer/importer release entered an as-of feature")
    return result


def merge_market(
    weekly: pd.DataFrame,
    usd: pd.DataFrame,
    brent: pd.DataFrame,
    ingested_at: str,
    anp_lag_days: int,
    usd_lag_days: int,
    brent_lag_days: int,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Join one-to-one weekly sources and attach the causal contract."""
    market = weekly.rename(columns={"week_end": "semana_fim"})
    market = market.merge(usd, on="semana_fim", how="left", validate="one_to_one")
    market = market.merge(brent, on="semana_fim", how="left", validate="one_to_one")

    missing = {
        "usd_brl": int(market["usd_brl_ultimo"].isna().sum()),
        "brent": int(market["brent_ultimo"].isna().sum()),
    }
    if any(missing.values()):
        raise ValueError(f"External weekly coverage is incomplete: {missing}")

    market["anp_available_at"] = availability_at_end_of_day(
        market["semana_fim"], anp_lag_days
    )
    market["usd_brl_available_at"] = availability_at_end_of_day(
        market["semana_fim"], usd_lag_days
    )
    market["brent_available_at"] = availability_at_end_of_day(
        market["semana_fim"], brent_lag_days
    )
    market["available_at"] = market["anp_available_at"]
    market["ingested_at"] = ingested_at
    market["series_id"] = "anp.diesel_s10.revenda.br.mean"
    market["observation_date"] = market["semana_fim"]
    market["value"] = market["preco_medio"]
    market["unit"] = TARGET_UNIT
    market["source"] = "ANP"
    market["revision"] = 0
    market["geography_type"] = "country"
    market["geography_code"] = "BR"
    market["geography"] = "Brasil"
    market["metadata"] = compact_json(
        {
            "aggregation": "station-day median, then unweighted national mean",
            "availability_assumption": (
                f"end of day {anp_lag_days} calendar days after reference Sunday"
            ),
            "product": TARGET_PRODUCT,
            "source_url": SOURCE_URL,
            "week_convention": "W-SUN",
        }
    )
    return market.sort_values("semana_fim").reset_index(drop=True), missing


def build_normalized_observations(
    market: pd.DataFrame,
    distribution: pd.DataFrame,
    producer: pd.DataFrame,
    ingested_at: str,
    anp_lag_days: int,
    usd_lag_days: int,
    brent_lag_days: int,
    distribution_lag_days: int,
    producer_lag_days: int,
) -> pd.DataFrame:
    """Create the long point-in-time contract for every integrated source."""
    definitions = [
        {
            "series_id": "anp.diesel_s10.revenda.br.mean",
            "value_column": "preco_medio",
            "available_column": "anp_available_at",
            "unit": "BRL/L",
            "source": "ANP",
            "geography_type": "country",
            "geography_code": "BR",
            "geography": "Brasil",
            "metadata": lambda row: {
                "aggregation": "station-day median, then unweighted national mean",
                "number_of_municipalities": int(row["numero_municipios"]),
                "number_of_station_days": int(row["numero_observacoes"]),
                "number_of_stations": int(row["numero_postos"]),
                "number_of_states": int(row["numero_ufs"]),
                "product": TARGET_PRODUCT,
                "publication_lag_assumption_days": anp_lag_days,
                "week_convention": "W-SUN",
            },
        },
        {
            "series_id": "bcb.usd_brl.ptax.sell.weekly_last",
            "value_column": "usd_brl_ultimo",
            "available_column": "usd_brl_available_at",
            "unit": "BRL/USD",
            "source": "BCB",
            "geography_type": "country",
            "geography_code": "BR",
            "geography": "Brasil",
            "metadata": lambda row: {
                "aggregation": "last business-day observation in W-SUN week",
                "daily_observations": int(row["usd_brl_observacoes"]),
                "publication_lag_assumption_days": usd_lag_days,
                "week_convention": "W-SUN",
            },
        },
        {
            "series_id": "eia.brent.rbrte.weekly_last",
            "value_column": "brent_ultimo",
            "available_column": "brent_available_at",
            "unit": "USD/bbl",
            "source": "EIA",
            "geography_type": "global",
            "geography_code": "GLOBAL",
            "geography": "Global",
            "metadata": lambda row: {
                "aggregation": "last business-day observation in W-SUN week",
                "daily_observations": int(row["brent_observacoes"]),
                "publication_lag_assumption_days": brent_lag_days,
                "series": "RBRTE",
                "week_convention": "W-SUN",
            },
        },
    ]

    parts: list[pd.DataFrame] = []
    for definition in definitions:
        part = pd.DataFrame(
            {
                "series_id": definition["series_id"],
                "observation_date": market["semana_fim"],
                "available_at": market[definition["available_column"]],
                "ingested_at": ingested_at,
                "value": market[definition["value_column"]],
                "unit": definition["unit"],
                "source": definition["source"],
                "revision": 0,
                "geography_type": definition["geography_type"],
                "geography_code": definition["geography_code"],
                "geography": definition["geography"],
                "metadata": [
                    compact_json(definition["metadata"](row))
                    for _, row in market.iterrows()
                ],
            }
        )
        parts.append(part)

    distribution_part = pd.DataFrame(
        {
            "series_id": "anp.distribution.diesel_s10.br.mean",
            "observation_date": distribution["observation_date"],
            "available_at": distribution["available_at"],
            "ingested_at": ingested_at,
            "value": distribution["value"],
            "unit": "BRL/L",
            "source": "ANP",
            "revision": 0,
            "geography_type": "country",
            "geography_code": "BR",
            "geography": "Brasil",
            "metadata": [
                compact_json(
                    {
                        "availability_status": "assumed_unverified",
                        "dispersion": float(row["dispersion"]),
                        "period_start": row["period_start"].date().isoformat(),
                        "period_end": row["period_end"].date().isoformat(),
                        "product": DISTRIBUTION_PRODUCT,
                        "publication_lag_assumption_days": distribution_lag_days,
                        "revision_warning": "Source labels observations as preliminary and revisable",
                    }
                )
                for _, row in distribution.iterrows()
            ],
        }
    )
    parts.append(distribution_part)

    producer_part = pd.DataFrame(
        {
            "series_id": "anp.producer_importer.diesel_s10.br.weighted_mean",
            "observation_date": producer["observation_date"],
            "available_at": producer["available_at"],
            "ingested_at": ingested_at,
            "value": producer["value"],
            "unit": "BRL/L",
            "source": "ANP",
            "revision": 0,
            "geography_type": "country",
            "geography_code": "BR",
            "geography": "Brasil",
            "metadata": [
                compact_json(
                    {
                        "availability_status": "official_estimate_in_workbook",
                        "excludes_icms": True,
                        "period_start": row["period_start"].date().isoformat(),
                        "period_end": row["period_end"].date().isoformat(),
                        "product": PRODUCER_PRODUCT,
                        "publication_lag_days": producer_lag_days,
                        "weighted_average": True,
                    }
                )
                for _, row in producer.iterrows()
            ],
        }
    )
    parts.append(producer_part)

    observations = pd.concat(parts, ignore_index=True).dropna(subset=["value"])
    observations = observations.sort_values(
        ["observation_date", "series_id", "geography_code"]
    ).reset_index(drop=True)
    return observations


def quality_check(
    check_id: str,
    passed: bool,
    detail: str,
    severity: str = "critical",
) -> dict[str, str]:
    """Build a consistent machine-readable quality result."""
    status = "pass" if passed else ("warning" if severity == "warning" else "fail")
    return {
        "check": check_id,
        "status": status,
        "severity": severity,
        "detail": detail,
    }


def build_quality_report(
    root: Path,
    retail_files: list[Path],
    file_diagnostics: list[dict[str, Any]],
    external_provenance: list[dict[str, Any]],
    cost_provenance: list[dict[str, Any]],
    target: pd.DataFrame,
    station_day: pd.DataFrame,
    station_stats: dict[str, int],
    distribution: pd.DataFrame,
    producer: pd.DataFrame,
    market: pd.DataFrame,
    normalized: pd.DataFrame,
    excluded_weeks: pd.DataFrame,
    ingested_stamp: pd.Timestamp,
    ingested_at: str,
    anp_lag_days: int,
    usd_lag_days: int,
    brent_lag_days: int,
    distribution_lag_days: int,
    producer_lag_days: int,
) -> dict[str, Any]:
    """Build checks, diagnostics, coverage and explicit assumptions."""
    expected_weeks = pd.date_range(
        market["semana_fim"].min(), market["semana_fim"].max(), freq="W-SUN"
    )
    required_contract = {
        "series_id",
        "observation_date",
        "available_at",
        "ingested_at",
        "value",
        "unit",
        "source",
        "revision",
        "geography_type",
        "geography_code",
        "geography",
        "metadata",
    }
    normalized_availability = pd.to_datetime(normalized["available_at"], utc=True)
    normalized_observation = pd.to_datetime(normalized["observation_date"], utc=True)
    blank_rows = sum(item["blank_rows"] for item in file_diagnostics)
    exact_duplicates = int(
        target.duplicated(
            [
                "state_code",
                "municipality_name",
                "station_name",
                "station_id",
                "observation_date",
                "value",
                "normalized_unit",
                "source_file",
            ]
        ).sum()
    )
    all_states = set(target["state_code"].dropna().unique())
    included_weeks = set(market["semana_fim"])
    state_sets = station_day.groupby("week_end")["state_code"].agg(
        lambda values: set(values.dropna())
    )
    geography_gaps = [
        {
            "week_end": week_end.date().isoformat(),
            "states_observed": len(observed),
            "missing_states": sorted(all_states - observed),
        }
        for week_end, observed in state_sets.items()
        if week_end in included_weeks and observed != all_states
    ]
    optional_retail_inputs = [
        item
        for item in file_diagnostics
        if item["snapshot_kind"] != "official_semester_snapshot"
    ]
    bcb_cache_inputs = [
        item
        for item in external_provenance
        if item.get("snapshot_kind") == "official_bcb_odata_cache"
    ]
    checks = [
        quality_check(
            "five_anp_snapshots",
            len(retail_files) == 5,
            f"Found {len(retail_files)} semester files",
        ),
        quality_check(
            "blank_source_rows",
            blank_rows == 0,
            f"{blank_rows} delimiter-only source rows were ignored",
            "warning",
        ),
        quality_check(
            "diesel_unit",
            target["normalized_unit"].eq(TARGET_UNIT_RAW).all(),
            f"All {len(target)} target rows validated as R$ / litro",
        ),
        quality_check(
            "target_dates",
            not target["observation_date"].isna().any(),
            "No invalid target dates",
        ),
        quality_check(
            "target_prices",
            target["value"].between(1, 20).all(),
            f"Observed range BRL {target['value'].min():.2f}-{target['value'].max():.2f}/L",
        ),
        quality_check(
            "station_day_unique",
            not station_day.duplicated(
                ["observation_date", "state_code", "municipality_name", "station_id"]
            ).any(),
            f"{station_stats['extra_rows_collapsed']} repeated rows collapsed by median",
        ),
        quality_check(
            "retail_snapshot_overlap",
            station_stats["snapshot_overlap_conflicting_keys"] == 0,
            (
                f"Removed {station_stats['snapshot_overlap_extra_rows_removed']} "
                "lower-priority duplicate station-days; "
                f"{station_stats['snapshot_overlap_conflicting_keys']} conflicting keys"
            ),
        ),
        quality_check(
            "optional_retail_cache_provenance",
            all(item.get("sha256") for item in optional_retail_inputs),
            f"{len(optional_retail_inputs)} optional ANP cache snapshot(s) checksummed",
        ),
        quality_check(
            "weekly_unique",
            not market["semana_fim"].duplicated().any(),
            "One national row per reference week",
        ),
        quality_check(
            "weekly_gaps",
            len(expected_weeks) == len(market)
            and market["semana_fim"].reset_index(drop=True).equals(
                pd.Series(expected_weeks, name="semana_fim")
            ),
            f"{len(expected_weeks) - len(market)} missing W-SUN weeks",
        ),
        quality_check(
            "weekly_geography_coverage",
            not geography_gaps,
            (
                f"{len(geography_gaps)} week(s) cover fewer than all "
                f"{len(all_states)} states"
            ),
            "warning",
        ),
        quality_check(
            "partial_final_week_excluded",
            market["semana_fim"].max() <= target["observation_date"].max(),
            f"Excluded {len(excluded_weeks)} partial boundary week(s)",
        ),
        quality_check(
            "external_coverage",
            market[["usd_brl_ultimo", "brent_ultimo"]].notna().all().all(),
            f"USD/BRL and Brent cover all {len(market)} target weeks",
        ),
        quality_check(
            "bcb_closing_cache",
            all(item.get("closing_bulletins", 0) > 0 for item in bcb_cache_inputs),
            (
                f"{len(bcb_cache_inputs)} optional BCB cache(s); only explicit "
                "Fechamento bulletins enter daily deduplication"
            ),
        ),
        quality_check(
            "cost_driver_coverage",
            market[
                [
                    "distribuicao_s10_preco_asof",
                    "produtor_importador_s10_preco_asof",
                ]
            ].notna().all().all(),
            f"Both ANP cost drivers cover all {len(market)} target origins",
        ),
        quality_check(
            "cost_driver_asof_availability",
            pd.to_datetime(
                market["distribuicao_s10_available_at_asof"], utc=True
            ).le(pd.to_datetime(market["anp_available_at"], utc=True)).all()
            and pd.to_datetime(
                market["produtor_importador_s10_available_at_asof"], utc=True
            ).le(pd.to_datetime(market["anp_available_at"], utc=True)).all(),
            "Selected cost-driver releases are known at every ANP target origin",
        ),
        quality_check(
            "cost_driver_observation_not_future",
            pd.to_datetime(market["distribuicao_s10_observacao_fim_asof"])
            .le(market["semana_fim"])
            .all()
            and pd.to_datetime(
                market["produtor_importador_s10_observacao_fim_asof"]
            ).le(market["semana_fim"]).all(),
            "Selected source periods never end after the target reference week",
        ),
        quality_check(
            "distribution_publication_lag_provenance",
            False,
            (
                f"Distribution uses an assumed conservative {distribution_lag_days}-day "
                "lag because the local workbook has no release ledger"
            ),
            "warning",
        ),
        quality_check(
            "producer_publication_lag",
            producer_lag_days >= 12,
            (
                f"Producer/importer uses {producer_lag_days} days; "
                "the workbook states an estimated 12-day update schedule"
            ),
        ),
        quality_check(
            "causal_contract",
            required_contract.issubset(normalized.columns),
            "Normalized observations contain the full point-in-time contract",
        ),
        quality_check(
            "availability_after_observation",
            normalized_availability.gt(normalized_observation).all(),
            "Every observation is unavailable until after its reference date",
        ),
        quality_check(
            "external_known_before_target_release",
            market["usd_brl_available_at"].le(market["anp_available_at"]).all()
            and market["brent_available_at"].le(market["anp_available_at"]).all(),
            "Same-week external aggregates are available before the ANP target release assumption",
        ),
        quality_check(
            "normalized_key_unique",
            not normalized.duplicated(
                ["series_id", "observation_date", "geography_code", "revision"]
            ).any(),
            "One normalized row per series/date/geography/revision",
        ),
    ]
    critical_failures = [
        item for item in checks if item["severity"] == "critical" and item["status"] == "fail"
    ]
    current_local_date = ingested_stamp.tz_convert(TIMEZONE).normalize().tz_localize(None)
    latest_target = target["observation_date"].max().normalize()

    report = {
        "pipeline": PIPELINE_VERSION,
        "status": "pass" if not critical_failures else "fail",
        "generated_at": ingested_at,
        "timezone": TIMEZONE,
        "target": {
            "product": TARGET_PRODUCT,
            "unit": TARGET_UNIT,
            "geography_type": "country",
            "geography_code": "BR",
            "geography": "Brasil",
            "source_rows": int(sum(item["raw_rows"] for item in file_diagnostics)),
            "source_nonblank_rows": int(
                sum(item["nonblank_rows"] for item in file_diagnostics)
            ),
            "blank_rows_ignored": int(blank_rows),
            "target_rows": int(len(target)),
            "exact_duplicate_target_rows": exact_duplicates,
            **station_stats,
            "unique_stations": int(target["station_id"].nunique()),
            "unique_municipalities": int(
                target[["state_code", "municipality_name"]].drop_duplicates().shape[0]
            ),
            "states": int(target["state_code"].nunique()),
            "first_collection": target["observation_date"].min().date().isoformat(),
            "last_collection": latest_target.date().isoformat(),
            "freshness_days_at_ingestion": max(
                0, int((current_local_date - latest_target).days)
            ),
            "weekly_rows": int(len(market)),
            "first_complete_week": market["semana_fim"].min().date().isoformat(),
            "last_complete_week": market["semana_fim"].max().date().isoformat(),
            "partial_weeks_excluded": [
                date.date().isoformat() for date in excluded_weeks["week_end"]
            ],
            "weekly_price_min": float(market["preco_medio"].min()),
            "weekly_price_max": float(market["preco_medio"].max()),
            "weekly_station_days_min": int(market["numero_observacoes"].min()),
            "weekly_station_days_max": int(market["numero_observacoes"].max()),
            "weekly_states_min": int(market["numero_ufs"].min()),
            "weekly_states_max": int(market["numero_ufs"].max()),
            "weekly_geography_gaps": geography_gaps,
        },
        "normalized_observations": {
            "rows": int(len(normalized)),
            "series": {
                str(key): int(value)
                for key, value in normalized["series_id"].value_counts().sort_index().items()
            },
            "null_values": int(normalized["value"].isna().sum()),
        },
        "cache_extensions": {
            "anp": {
                "files_used": len(optional_retail_inputs),
                "paths": [item["path"] for item in optional_retail_inputs],
                "published_snapshots": [
                    {
                        "path": item["path"],
                        "published_on": item["published_on"],
                        "availability_policy": (
                            f"Target weeks retain conservative +{anp_lag_days}-day "
                            "availability even when snapshot publication is known"
                        ),
                    }
                    for item in optional_retail_inputs
                    if item.get("published_on")
                ],
                "overlap_rows": station_stats["snapshot_overlap_rows"],
                "overlap_extra_rows_removed": station_stats[
                    "snapshot_overlap_extra_rows_removed"
                ],
                "overlap_conflicting_keys": station_stats[
                    "snapshot_overlap_conflicting_keys"
                ],
            },
            "bcb": {
                "files_used": len(bcb_cache_inputs),
                "closing_bulletins": int(
                    sum(item["closing_bulletins"] for item in bcb_cache_inputs)
                ),
                "paths": [item["path"] for item in bcb_cache_inputs],
            },
        },
        "cost_drivers": {
            "distribution": {
                "series_id": "anp.distribution.diesel_s10.br.mean",
                "source_rows": int(len(distribution)),
                "observation_start": distribution["period_start"].min().date().isoformat(),
                "observation_end": distribution["period_end"].max().date().isoformat(),
                "value_min": float(distribution["value"].min()),
                "value_max": float(distribution["value"].max()),
                "publication_lag_days": distribution_lag_days,
                "publication_lag_status": "assumed_unverified",
                "asof_feature_rows": int(
                    market["distribuicao_s10_preco_asof"].notna().sum()
                ),
                "asof_source_age_days_min": int(
                    market["distribuicao_s10_idade_dias"].min()
                ),
                "asof_source_age_days_max": int(
                    market["distribuicao_s10_idade_dias"].max()
                ),
            },
            "producer_importer": {
                "series_id": "anp.producer_importer.diesel_s10.br.weighted_mean",
                "source_rows": int(len(producer)),
                "observation_start": producer["period_start"].min().date().isoformat(),
                "observation_end": producer["period_end"].max().date().isoformat(),
                "value_min": float(producer["value"].min()),
                "value_max": float(producer["value"].max()),
                "publication_lag_days": producer_lag_days,
                "publication_lag_status": "official_estimate_in_workbook",
                "asof_feature_rows": int(
                    market["produtor_importador_s10_preco_asof"].notna().sum()
                ),
                "asof_source_age_days_min": int(
                    market["produtor_importador_s10_idade_dias"].min()
                ),
                "asof_source_age_days_max": int(
                    market["produtor_importador_s10_idade_dias"].max()
                ),
            },
        },
        "availability_assumptions": {
            "anp_retail": {
                "lag_calendar_days": anp_lag_days,
                "available_time": f"23:59:59 {TIMEZONE}",
                "basis": "Conservative implementation assumption; verify against publication history",
            },
            "bcb_usd_brl": {
                "lag_calendar_days": usd_lag_days,
                "available_time": f"23:59:59 {TIMEZONE}",
                "basis": "Conservative weekly snapshot assumption",
            },
            "eia_brent": {
                "lag_calendar_days": brent_lag_days,
                "available_time": f"23:59:59 {TIMEZONE}",
                "basis": "Conservative weekly snapshot assumption",
            },
            "anp_distribution": {
                "lag_calendar_days": distribution_lag_days,
                "available_time": f"23:59:59 {TIMEZONE}",
                "basis": (
                    "Conservative sensitivity assumption; exact historical release "
                    "timestamps are absent locally"
                ),
                "feature_status": "experimental",
            },
            "anp_producer_importer": {
                "lag_calendar_days": producer_lag_days,
                "available_time": f"23:59:59 {TIMEZONE}",
                "basis": "Official estimated schedule stated inside the workbook",
                "unit_note": "BRL/L excluding ICMS",
            },
        },
        "aggregation": {
            "station_day": "median of repeated prices for CNPJ/date/state/municipality",
            "national_week": "unweighted mean across station-day medians",
            "week_convention": "Monday through Sunday; reference date is Sunday",
            "imputation": "none",
        },
        "inputs": [*file_diagnostics, *external_provenance, *cost_provenance],
        "checks": checks,
        "warnings": [
            "Valor de Compra is entirely absent in the ANP semester snapshots and is not used.",
            "ANP publication lag is a conservative assumption, not a verified historical release calendar.",
            "The national mean is not volume weighted and the station sample composition changes over time.",
            (
                "Distribution publication timing is unverified; its as-of feature "
                f"uses a conservative {distribution_lag_days}-day lag and remains experimental."
            ),
            "Both ANP cost workbooks describe preliminary or revisable information without a historical vintage ledger.",
            *(
                [
                    "The rolling ANP snapshot was published on 2026-08-07, but target available_at remains the more conservative configured release rule."
                ]
                if any(item.get("published_on") for item in optional_retail_inputs)
                else []
            ),
        ],
    }
    return report


def prepare_data(
    root: Path,
    output_dir: Path,
    chunksize: int = 100_000,
    ingested_at_value: str | None = None,
    anp_lag_days: int = 8,
    usd_lag_days: int = 1,
    brent_lag_days: int = 3,
    distribution_lag_days: int = 14,
    producer_lag_days: int = 12,
) -> dict[str, Any]:
    """Execute the complete read/validate/aggregate/join/write pipeline."""
    if min(
        anp_lag_days,
        usd_lag_days,
        brent_lag_days,
        distribution_lag_days,
        producer_lag_days,
    ) < 0:
        raise ValueError("Availability lags cannot be negative")
    if anp_lag_days < max(usd_lag_days, brent_lag_days):
        raise ValueError("ANP target availability must not precede same-week external availability")

    root = root.resolve()
    output_dir = output_dir if output_dir.is_absolute() else root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    ingested_stamp, ingested_at = normalize_ingested_at(ingested_at_value)

    retail_files = discover_retail_files(root)
    optional_retail_caches = discover_optional_retail_caches(root)
    target, file_diagnostics = load_retail_target(
        root,
        retail_files,
        chunksize,
        optional_retail_caches,
    )
    station_day, station_stats = station_day_medians(target)
    weekly, excluded_weeks = aggregate_national_weekly(station_day)
    usd, brent, external_provenance = load_external_weekly(root)
    distribution, producer, cost_provenance = load_anp_cost_drivers(
        root,
        distribution_lag_days,
        producer_lag_days,
    )
    market, _ = merge_market(
        weekly,
        usd,
        brent,
        ingested_at,
        anp_lag_days,
        usd_lag_days,
        brent_lag_days,
    )
    market = align_cost_drivers_asof(
        market,
        distribution,
        producer,
        distribution_lag_days,
        producer_lag_days,
    )
    normalized = build_normalized_observations(
        market,
        distribution,
        producer,
        ingested_at,
        anp_lag_days,
        usd_lag_days,
        brent_lag_days,
        distribution_lag_days,
        producer_lag_days,
    )
    report = build_quality_report(
        root,
        retail_files,
        file_diagnostics,
        external_provenance,
        cost_provenance,
        target,
        station_day,
        station_stats,
        distribution,
        producer,
        market,
        normalized,
        excluded_weeks,
        ingested_stamp,
        ingested_at,
        anp_lag_days,
        usd_lag_days,
        brent_lag_days,
        distribution_lag_days,
        producer_lag_days,
    )
    if report["status"] != "pass":
        failures = [
            check["check"] for check in report["checks"] if check["status"] == "fail"
        ]
        raise AssertionError(f"Critical data-quality checks failed: {failures}")

    market_path = output_dir / "market_weekly.csv"
    normalized_path = output_dir / "normalized_observations.csv"
    report_path = output_dir / "quality_report.json"

    market_output = market.copy()
    market_output["semana_inicio"] = date_iso(market_output["semana_inicio"])
    market_output["semana_fim"] = date_iso(market_output["semana_fim"])
    market_output["observation_date"] = date_iso(market_output["observation_date"])
    for column in [
        "distribuicao_s10_observacao_inicio_asof",
        "distribuicao_s10_observacao_fim_asof",
        "produtor_importador_s10_observacao_inicio_asof",
        "produtor_importador_s10_observacao_fim_asof",
    ]:
        market_output[column] = date_iso(market_output[column])
    for column in [
        "available_at",
        "anp_available_at",
        "usd_brl_available_at",
        "brent_available_at",
        "distribuicao_s10_available_at_asof",
        "produtor_importador_s10_available_at_asof",
    ]:
        market_output[column] = utc_iso(market_output[column])

    contract_columns = [
        "series_id",
        "observation_date",
        "available_at",
        "ingested_at",
        "value",
        "unit",
        "source",
        "revision",
        "geography_type",
        "geography_code",
        "geography",
        "metadata",
    ]
    weekly_columns = [
        "semana_inicio",
        "semana_fim",
        "preco_medio",
        "preco_mediano",
        "preco_minimo",
        "preco_maximo",
        "preco_desvio_padrao",
        "numero_observacoes",
        "numero_postos",
        "numero_municipios",
        "numero_ufs",
        "semana_sem_dados",
        "is_complete_week",
        *USD_COLUMNS[1:],
        *BRENT_COLUMNS[1:],
        "anp_available_at",
        "usd_brl_available_at",
        "brent_available_at",
        *COST_DRIVER_COLUMNS,
    ]
    market_output = market_output[[*contract_columns, *weekly_columns]]

    normalized_output = normalized.copy()
    normalized_output["observation_date"] = date_iso(
        normalized_output["observation_date"]
    )
    normalized_output["available_at"] = utc_iso(normalized_output["available_at"])
    normalized_output = normalized_output[contract_columns]

    market_output.to_csv(
        market_path, index=False, encoding="utf-8", float_format="%.12g", lineterminator="\n"
    )
    normalized_output.to_csv(
        normalized_path,
        index=False,
        encoding="utf-8",
        float_format="%.12g",
        lineterminator="\n",
    )
    report["outputs"] = {
        "market_weekly": {
            "path": market_path.relative_to(root).as_posix(),
            "rows": int(len(market_output)),
            "columns": int(len(market_output.columns)),
            "bytes": market_path.stat().st_size,
            "sha256": sha256(market_path),
        },
        "normalized_observations": {
            "path": normalized_path.relative_to(root).as_posix(),
            "rows": int(len(normalized_output)),
            "columns": int(len(normalized_output.columns)),
            "bytes": normalized_path.stat().st_size,
            "sha256": sha256(normalized_path),
        },
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    return {
        "status": report["status"],
        "market_weekly": str(market_path),
        "normalized_observations": str(normalized_path),
        "quality_report": str(report_path),
        "weekly_rows": len(market_output),
        "normalized_rows": len(normalized_output),
    }


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=default_root)
    parser.add_argument("--output-dir", type=Path, default=Path("data/gold"))
    parser.add_argument("--chunksize", type=int, default=100_000)
    parser.add_argument(
        "--ingested-at",
        help="Optional reproducible ISO timestamp; naive timestamps are interpreted as UTC",
    )
    parser.add_argument("--anp-lag-days", type=int, default=8)
    parser.add_argument("--usd-lag-days", type=int, default=1)
    parser.add_argument("--brent-lag-days", type=int, default=3)
    parser.add_argument(
        "--distribution-lag-days",
        type=int,
        default=14,
        help="Conservative assumed lag; exact historical distribution releases are unavailable",
    )
    parser.add_argument(
        "--producer-lag-days",
        type=int,
        default=12,
        help="Workbook-stated estimated lag after the reference week",
    )
    return parser.parse_args()


def main() -> None:
    """CLI entry point."""
    args = parse_args()
    result = prepare_data(
        root=args.root,
        output_dir=args.output_dir,
        chunksize=args.chunksize,
        ingested_at_value=args.ingested_at,
        anp_lag_days=args.anp_lag_days,
        usd_lag_days=args.usd_lag_days,
        brent_lag_days=args.brent_lag_days,
        distribution_lag_days=args.distribution_lag_days,
        producer_lag_days=args.producer_lag_days,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
