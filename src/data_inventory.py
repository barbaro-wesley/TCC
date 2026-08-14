"""Inventario leve das bases, sem carregar os arquivos grandes por inteiro."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pandas as pd


BCB_COLUMNS = [
    "data",
    "codigo_moeda",
    "tipo",
    "moeda",
    "taxa_compra",
    "taxa_venda",
    "paridade_compra",
    "paridade_venda",
]


def _encoding(path: Path) -> str:
    with path.open("rb") as stream:
        sample = stream.read(65_536)
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            sample.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "latin-1"


def _csv_options(path: Path) -> dict[str, Any]:
    normalized = str(path).replace("\\", "/").lower()
    options: dict[str, Any] = {
        "sep": ";",
        "encoding": _encoding(path),
        "decimal": ",",
    }
    if "/dolar/" in normalized:
        options.update(header=None, names=BCB_COLUMNS)
    return options


def _read_csv_sample(path: Path, sample_rows: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    options = _csv_options(path)
    normalized = str(path).replace("\\", "/").lower()

    # O export atual do SIDRA e um relatorio, nao uma serie historica tabular.
    if "/ibge/ipca/" in normalized:
        with path.open(encoding=options["encoding"], newline="") as stream:
            rows = list(csv.reader(stream, delimiter=";"))
        brasil_index = next(
            (index for index, row in enumerate(rows) if row and row[0] == "Brasil"), None
        )
        if brasil_index is None or brasil_index == 0:
            return pd.DataFrame(), {
                "observacao": "Export SIDRA sem uma linha tabular identificavel."
            }
        item_row = rows[brasil_index - 1]
        month_row = rows[brasil_index - 2]
        month_row.extend([""] * (len(item_row) - len(month_row)))
        current_month = "periodo_nao_identificado"
        columns = ["localidade"]
        periods: list[str] = []
        for month, item in zip(month_row[1:], item_row[1:]):
            if month:
                current_month = month
                periods.append(month)
            columns.append(f"{current_month} | {item}")
        values = rows[brasil_index]
        frame = pd.DataFrame([values], columns=columns)
        return frame, {
            "periodo_relatorio": (
                f"{periods[0]} a {periods[-1]} ({len(periods)} meses)"
                if periods
                else "nao identificado"
            ),
            "observacao": "Export SIDRA em formato largo: meses x 8 itens do IPCA.",
        }

    frame = pd.read_csv(path, nrows=sample_rows, low_memory=False, **options)
    return frame, {}


def _read_excel_sample(path: Path, sample_rows: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    suffix = path.suffix.lower()
    engine = "openpyxl" if suffix == ".xlsx" else "xlrd"
    try:
        book = pd.ExcelFile(path, engine=engine)
        sheet = book.sheet_names[0]
        frame = pd.read_excel(book, sheet_name=sheet, nrows=sample_rows)
        return frame, {"planilhas": book.sheet_names, "planilha_amostrada": sheet}
    except ImportError:
        return pd.DataFrame(), {
            "observacao": f"Instale a dependencia '{engine}' para inspecionar este arquivo."
        }
    except Exception as exc:  # Mantem o inventario util mesmo com uma planilha irregular.
        return pd.DataFrame(), {"erro_leitura": f"{type(exc).__name__}: {exc}"}


def inspect_file(path: Path, sample_rows: int = 2_000) -> dict[str, Any]:
    """Coleta metadados e estatisticas de uma amostra limitada do arquivo."""
    record: dict[str, Any] = {
        "arquivo": str(path),
        "formato": path.suffix.lower().lstrip("."),
        "tamanho_mb": round(path.stat().st_size / 1_048_576, 3),
        "linhas_amostradas": 0,
        "colunas": [],
        "tipos_amostra": {},
        "ausentes_amostra": {},
        "encoding": None,
        "separador": None,
        "periodo_relatorio": None,
        "observacao": None,
        "erro_leitura": None,
    }

    try:
        if path.suffix.lower() == ".csv":
            frame, extra = _read_csv_sample(path, sample_rows)
            record["encoding"] = _csv_options(path)["encoding"]
            record["separador"] = ";"
        elif path.suffix.lower() in {".xls", ".xlsx"}:
            frame, extra = _read_excel_sample(path, sample_rows)
        else:
            record["observacao"] = "Formato nao suportado pelo inventario."
            return record
    except Exception as exc:
        record["erro_leitura"] = f"{type(exc).__name__}: {exc}"
        return record

    record.update(extra)
    record["linhas_amostradas"] = len(frame)
    record["colunas"] = [str(column) for column in frame.columns]
    record["tipos_amostra"] = {str(k): str(v) for k, v in frame.dtypes.items()}
    record["ausentes_amostra"] = {
        str(k): int(v) for k, v in frame.isna().sum().items() if int(v) > 0
    }
    return record


def build_inventory(raw_dir: Path | str = "raw", sample_rows: int = 2_000) -> pd.DataFrame:
    """Inventaria CSV/XLS/XLSX usando no maximo ``sample_rows`` linhas por arquivo."""
    raw_path = Path(raw_dir)
    files = sorted(
        path
        for path in raw_path.rglob("*")
        if path.is_file() and path.suffix.lower() in {".csv", ".xls", ".xlsx"}
    )
    return pd.DataFrame(inspect_file(path, sample_rows) for path in files)


def save_inventory(
    inventory: pd.DataFrame, output_dir: Path | str = "processed/inventory"
) -> tuple[Path, Path]:
    """Salva uma visao tabular e outra detalhada do inventario."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    csv_path = output_path / "files.csv"
    json_path = output_path / "files.json"

    scalar_columns = [
        "arquivo",
        "formato",
        "tamanho_mb",
        "linhas_amostradas",
        "encoding",
        "separador",
        "observacao",
        "erro_leitura",
    ]
    existing = [column for column in scalar_columns if column in inventory.columns]
    inventory[existing].to_csv(csv_path, index=False, encoding="utf-8")
    json_path.write_text(
        json.dumps(inventory.to_dict(orient="records"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return csv_path, json_path
