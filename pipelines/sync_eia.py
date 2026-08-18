"""Secure, incremental cache for EIA v2 daily petroleum spot prices.

The API key is read exclusively from ``EIA_API_KEY``.  Network access is
explicitly opt-in from the CLI, every response is validated before use, and
server-echoed credentials are redacted before a raw response is persisted.

The canonical cache is intentionally daily and source-shaped.  Downstream
pipelines can select ``RBRTE`` (Brent) or ``RWTC`` (WTI), rename ``period`` to
their observation-date field, and aggregate it without knowing anything about
API authentication or pagination.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

EIA_API_KEY_ENV = "EIA_API_KEY"
EIA_API_BASE_URL_ENV = "EIA_API_BASE_URL"
DEFAULT_EIA_API_BASE_URL = "https://api.eia.gov/v2"
SPOT_PRICE_ENDPOINT = "/petroleum/pri/spt/data/"
DEFAULT_CACHE_PATH = Path("data/cache/eia/spot-prices-daily.csv")
DEFAULT_RAW_DIR = Path("data/cache/eia/raw")
ALLOWED_SERIES = frozenset({"RBRTE", "RWTC"})
REDACTED = "[REDACTED]"
MAX_RESPONSE_BYTES = 50 * 1024 * 1024

CANONICAL_COLUMNS = (
    "period",
    "series",
    "value",
    "units",
    "series_description",
    "duoarea",
    "area_name",
    "product",
    "product_name",
    "process",
    "process_name",
    "retrieved_at",
    "vintage_id",
)
SOURCE_COLUMNS = CANONICAL_COLUMNS[:-2]


class EIAError(RuntimeError):
    """Base error for safe EIA integration failures."""


class EIAConfigurationError(EIAError):
    """Raised when the local EIA configuration is missing or unsafe."""


class EIARequestError(EIAError):
    """Raised when an EIA request fails without exposing its credential."""


class EIAResponseError(EIAError):
    """Raised when an EIA response violates the expected data contract."""


@dataclass(frozen=True)
class EIAPage:
    """One sanitized API page and the pagination facts used to fetch it."""

    offset: int
    total: int
    row_count: int
    payload: dict[str, Any]


@dataclass(frozen=True)
class EIAFetchResult:
    """Validated rows plus sanitized raw pages for one request range."""

    series: tuple[str, ...]
    start: date
    end: date
    records: tuple[dict[str, str], ...]
    pages: tuple[EIAPage, ...]


@dataclass(frozen=True)
class EIAWorkbookSnapshot:
    """Validated rows and release metadata from an official EIA XLS vintage."""

    series: str
    description: str
    frequency: str
    latest_period: date
    release_date: date
    next_release_date: date | None
    records: tuple[dict[str, str], ...]
    bytes: int
    sha256: str


def _normalize_series(series: Iterable[str] | str) -> tuple[str, ...]:
    values = (series,) if isinstance(series, str) else tuple(series)
    normalized = tuple(dict.fromkeys(str(item).strip().upper() for item in values))
    if not normalized:
        raise ValueError("At least one EIA series is required")
    invalid = sorted(set(normalized) - ALLOWED_SERIES)
    if invalid:
        raise ValueError(
            f"Unsupported EIA series: {invalid}; allowed={sorted(ALLOWED_SERIES)}"
        )
    return normalized


def _coerce_date(value: date | str, field: str) -> date:
    if isinstance(value, datetime):
        result = value.date()
    elif isinstance(value, date):
        result = value
    else:
        try:
            result = date.fromisoformat(str(value))
        except ValueError:
            raise ValueError(f"{field} must use YYYY-MM-DD") from None
    return result


def _normalize_retrieved_at(value: datetime | None) -> datetime:
    stamp = value or datetime.now(UTC)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp.astimezone(UTC).replace(microsecond=0)


def _normalize_base_url(value: str, *, allow_loopback_for_testing: bool = False) -> str:
    raw = value.strip().rstrip("/")
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise EIAConfigurationError("EIA API base URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise EIAConfigurationError(
            "EIA API base URL cannot contain credentials, query parameters, or fragments"
        )
    try:
        port = parsed.port
    except ValueError:
        raise EIAConfigurationError("EIA API base URL contains an invalid port") from None
    hostname = (parsed.hostname or "").casefold()
    is_loopback = hostname in {"localhost", "127.0.0.1", "::1"}
    if is_loopback:
        if not allow_loopback_for_testing:
            raise EIAConfigurationError(
                "Loopback EIA base URLs require explicit test-only authorization"
            )
    elif hostname != "api.eia.gov" or parsed.scheme != "https" or port not in {None, 443}:
        raise EIAConfigurationError(
            "Production EIA requests are restricted to https://api.eia.gov"
        )
    return raw


def _is_sensitive_key(key: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
    return normalized in {"apikey", "authorization", "accesstoken", "token"}


def _redact_payload(value: Any, secret: str) -> Any:
    """Return a deep copy with sensitive fields and literal secrets removed."""

    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if _is_sensitive_key(key) else _redact_payload(item, secret)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_payload(item, secret) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_payload(item, secret) for item in value)
    if isinstance(value, str):
        redacted = value
        for candidate in {
            secret,
            urllib.parse.quote(secret, safe=""),
            urllib.parse.quote_plus(secret),
        }:
            if candidate:
                redacted = redacted.replace(candidate, REDACTED)
        return redacted
    return value


def _canonical_decimal(value: object) -> str:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise EIAResponseError("EIA row contains a non-numeric price") from None
    if not number.is_finite() or not (-250 <= number <= 1_000):
        raise EIAResponseError("EIA row contains an implausible spot price")
    rendered = format(number, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _normalize_api_row(
    row: object,
    requested_series: tuple[str, ...],
    start: date,
    end: date,
) -> dict[str, str]:
    if not isinstance(row, Mapping):
        raise EIAResponseError("EIA response data contains a non-object row")
    required = {"period", "series", "series-description", "value", "units"}
    missing = sorted(required - set(row))
    if missing:
        raise EIAResponseError(f"EIA row is missing required fields: {missing}")

    series = str(row["series"]).strip().upper()
    if series not in requested_series or series not in ALLOWED_SERIES:
        raise EIAResponseError("EIA response returned an unexpected series")
    try:
        period = date.fromisoformat(str(row["period"]))
    except ValueError:
        raise EIAResponseError("EIA row period must use YYYY-MM-DD") from None
    if not start <= period <= end:
        raise EIAResponseError("EIA response returned a period outside the request range")

    units = str(row["units"]).strip().upper()
    if units != "$/BBL":
        raise EIAResponseError("EIA spot-price units must be $/BBL")

    def text_field(source_name: str) -> str:
        raw = row.get(source_name, "")
        return "" if raw is None else str(raw).strip()

    return {
        "period": period.isoformat(),
        "series": series,
        "value": _canonical_decimal(row["value"]),
        "units": units,
        "series_description": text_field("series-description"),
        "duoarea": text_field("duoarea"),
        "area_name": text_field("area-name"),
        "product": text_field("product"),
        "product_name": text_field("product-name"),
        "process": text_field("process"),
        "process_name": text_field("process-name"),
    }


def _parse_workbook_date(value: object, field: str) -> date:
    text = str(value).strip()
    for pattern in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise EIAResponseError(f"EIA workbook {field} is not a recognized date")


def _contents_label_value(sheet: Any, label: str) -> object:
    for row_index in range(sheet.nrows):
        for column_index in range(sheet.ncols):
            if str(sheet.cell_value(row_index, column_index)).strip() != label:
                continue
            for value_column in range(column_index + 1, sheet.ncols):
                value = sheet.cell_value(row_index, value_column)
                if str(value).strip():
                    return value
    raise EIAResponseError(f"EIA workbook Contents sheet has no {label!r} field")


def parse_eia_xls_snapshot(
    path: Path | str,
    *,
    expected_series: str | None = None,
) -> EIAWorkbookSnapshot:
    """Validate an official EIA historical XLS and normalize its daily rows.

    The parser checks the ``Contents`` release ledger as well as the ``Data 1``
    source key, units implied by the official description, monotonically
    increasing dates, unique observations, numeric prices, and agreement
    between the declared and observed latest date.
    """

    source_path = Path(path)
    if not source_path.is_file():
        raise FileNotFoundError(f"EIA XLS snapshot not found: {source_path}")
    if source_path.stat().st_size < 1_024:
        raise EIAResponseError("EIA XLS snapshot is unexpectedly small")
    expected = _normalize_series(expected_series)[0] if expected_series else None

    try:
        import xlrd
    except ImportError:
        raise EIAConfigurationError(
            "Reading an EIA XLS snapshot requires the project xlrd dependency"
        ) from None
    try:
        workbook = xlrd.open_workbook(source_path, on_demand=True)
    except Exception:
        raise EIAResponseError("EIA XLS snapshot could not be opened") from None
    try:
        required_sheets = {"Contents", "Data 1"}
        if not required_sheets.issubset(workbook.sheet_names()):
            raise EIAResponseError("EIA XLS snapshot is missing Contents or Data 1")
        contents = workbook.sheet_by_name("Contents")
        data_sheet = workbook.sheet_by_name("Data 1")

        header_row: int | None = None
        data_row: int | None = None
        for row_index in range(contents.nrows):
            values = [
                str(contents.cell_value(row_index, column)).strip()
                for column in range(contents.ncols)
            ]
            if "Worksheet Name" in values and "Frequency" in values:
                header_row = row_index
            if values and "Data 1" in values:
                data_row = row_index
        if header_row is None or data_row is None or data_row <= header_row:
            raise EIAResponseError("EIA workbook Contents table is malformed")
        headers = {
            str(contents.cell_value(header_row, column)).strip(): column
            for column in range(contents.ncols)
        }
        for required_header in {"Description", "Frequency", "Latest Data for"}:
            if required_header not in headers:
                raise EIAResponseError(
                    f"EIA workbook Contents table has no {required_header!r} column"
                )
        description = str(
            contents.cell_value(data_row, headers["Description"])
        ).strip()
        frequency = str(contents.cell_value(data_row, headers["Frequency"])).strip()
        latest_period = _parse_workbook_date(
            contents.cell_value(data_row, headers["Latest Data for"]),
            "latest-data date",
        )
        release_date = _parse_workbook_date(
            _contents_label_value(contents, "Release Date:"), "release date"
        )
        try:
            next_release_date = _parse_workbook_date(
                _contents_label_value(contents, "Next Release Date:"),
                "next-release date",
            )
        except EIAResponseError:
            next_release_date = None

        if frequency.casefold() != "daily":
            raise EIAResponseError("EIA workbook frequency is not Daily")
        if "dollars per barrel" not in description.casefold():
            raise EIAResponseError("EIA workbook description does not declare barrel-price units")
        if data_sheet.nrows < 4 or data_sheet.ncols < 2:
            raise EIAResponseError("EIA workbook Data 1 sheet has no observations")
        if str(data_sheet.cell_value(1, 0)).strip().casefold() != "sourcekey":
            raise EIAResponseError("EIA workbook Data 1 source-key header is missing")
        source_series = str(data_sheet.cell_value(1, 1)).strip().upper()
        series = _normalize_series(source_series)[0]
        if expected is not None and series != expected:
            raise EIAResponseError(
                f"EIA workbook contains {series}, expected {expected}"
            )
        if str(data_sheet.cell_value(2, 0)).strip().casefold() != "date":
            raise EIAResponseError("EIA workbook Data 1 date header is missing")
        data_description = str(data_sheet.cell_value(2, 1)).strip()
        if data_description != description:
            raise EIAResponseError(
                "EIA workbook Contents and Data 1 descriptions do not agree"
            )

        raw_dates = data_sheet.col_values(0, 3)
        raw_values = data_sheet.col_values(1, 3)
        date_types = data_sheet.col_types(0, 3)
        value_types = data_sheet.col_types(1, 3)
        records: list[dict[str, str]] = []
        periods: list[date] = []
        for excel_date, price, date_type, value_type in zip(
            raw_dates, raw_values, date_types, value_types, strict=True
        ):
            if date_type == xlrd.XL_CELL_EMPTY and value_type == xlrd.XL_CELL_EMPTY:
                continue
            if date_type != xlrd.XL_CELL_DATE or value_type != xlrd.XL_CELL_NUMBER:
                raise EIAResponseError("EIA workbook contains a malformed daily row")
            try:
                period = xlrd.xldate_as_datetime(excel_date, workbook.datemode).date()
            except Exception:
                raise EIAResponseError("EIA workbook contains an invalid Excel date") from None
            periods.append(period)
            records.append(
                {
                    "period": period.isoformat(),
                    "series": series,
                    "value": _canonical_decimal(price),
                    "units": "$/BBL",
                    "series_description": description,
                    "duoarea": "",
                    "area_name": "",
                    "product": "",
                    "product_name": "",
                    "process": "",
                    "process_name": "",
                }
            )

        if not records:
            raise EIAResponseError("EIA workbook contains no valid daily observations")
        if periods != sorted(periods) or len(periods) != len(set(periods)):
            raise EIAResponseError("EIA workbook dates must be strictly increasing and unique")
        if periods[-1] != latest_period:
            raise EIAResponseError(
                "EIA workbook latest-data metadata does not match its final observation"
            )
        if release_date < latest_period:
            raise EIAResponseError("EIA workbook release date precedes its latest observation")
        if next_release_date is not None and next_release_date < release_date:
            raise EIAResponseError("EIA workbook next release precedes its release date")

        return EIAWorkbookSnapshot(
            series=series,
            description=description,
            frequency="daily",
            latest_period=latest_period,
            release_date=release_date,
            next_release_date=next_release_date,
            records=tuple(records),
            bytes=source_path.stat().st_size,
            sha256=_sha256(source_path),
        )
    finally:
        workbook.release_resources()


def normalized_eia_daily_frame(
    records: Iterable[Mapping[str, str]],
    *,
    series: str = "RBRTE",
) -> Any:
    """Convert normalized EIA rows to the daily DataFrame contract in this repo.

    ``RBRTE`` yields ``data, brent_usd_barril`` and ``RWTC`` yields
    ``data, wti_usd_barril``.  Pandas is imported lazily so cache validation and
    API collection do not need to initialize the analytical stack.
    """

    import pandas as pd

    selected = _normalize_series(series)[0]
    value_column = "brent_usd_barril" if selected == "RBRTE" else "wti_usd_barril"
    source_rows = [dict(row) for row in records if str(row.get("series", "")).upper() == selected]
    if not source_rows:
        raise EIAResponseError(f"No normalized rows are available for {selected}")
    frame = pd.DataFrame(source_rows)
    frame["data"] = pd.to_datetime(frame["period"], format="%Y-%m-%d", errors="coerce")
    frame[value_column] = pd.to_numeric(frame["value"], errors="coerce")
    if frame[["data", value_column]].isna().any().any():
        raise EIAResponseError("Normalized EIA rows contain an invalid date or price")
    if frame["data"].duplicated().any():
        raise EIAResponseError(f"Normalized EIA rows contain duplicate {selected} dates")
    return frame[["data", value_column]].sort_values("data").reset_index(drop=True)


def load_eia_xls_daily(
    path: Path | str,
    *,
    expected_series: str = "RBRTE",
) -> tuple[Any, dict[str, Any]]:
    """Load an official XLS into the repo's daily analytical DataFrame contract."""

    snapshot = parse_eia_xls_snapshot(path, expected_series=expected_series)
    frame = normalized_eia_daily_frame(snapshot.records, series=snapshot.series)
    quality = {
        "source": "U.S. Energy Information Administration",
        "series": snapshot.series,
        "description": snapshot.description,
        "frequency": snapshot.frequency,
        "rows": len(snapshot.records),
        "observation_start": snapshot.records[0]["period"],
        "observation_end": snapshot.latest_period.isoformat(),
        "release_date": snapshot.release_date.isoformat(),
        "next_release_date": (
            snapshot.next_release_date.isoformat() if snapshot.next_release_date else None
        ),
        "bytes": snapshot.bytes,
        "sha256": snapshot.sha256,
    }
    return frame, quality


class EIAClient:
    """Small EIA API v2 client whose credential can only come from the environment."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float = 60,
        opener: Callable[..., Any] | None = None,
        allow_loopback_for_testing: bool = False,
    ) -> None:
        api_key = os.getenv(EIA_API_KEY_ENV, "").strip()
        if not api_key:
            raise EIAConfigurationError(
                f"Set {EIA_API_KEY_ENV} in the local environment before enabling EIA sync"
            )
        if any(character in api_key for character in "\r\n"):
            raise EIAConfigurationError(f"{EIA_API_KEY_ENV} contains invalid control characters")
        configured_base = base_url or os.getenv(
            EIA_API_BASE_URL_ENV, DEFAULT_EIA_API_BASE_URL
        )
        self.base_url = _normalize_base_url(
            configured_base,
            allow_loopback_for_testing=allow_loopback_for_testing,
        )
        if allow_loopback_for_testing and urllib.parse.urlsplit(self.base_url).hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
        } and opener is None:
            raise EIAConfigurationError(
                "Test-only loopback requires an injected transport; live requests are disabled"
            )
        self.timeout_seconds = float(timeout_seconds)
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.__api_key = api_key
        self._opener = opener or urllib.request.urlopen

    def __repr__(self) -> str:
        return f"EIAClient(base_url={self.base_url!r}, timeout_seconds={self.timeout_seconds!r})"

    def _request_url(
        self,
        series: tuple[str, ...],
        start: date,
        end: date,
        offset: int,
        page_size: int,
    ) -> str:
        query: list[tuple[str, str]] = [
            ("api_key", self.__api_key),
            ("frequency", "daily"),
            ("data[0]", "value"),
        ]
        query.extend(("facets[series][]", item) for item in series)
        query.extend(
            [
                ("start", start.isoformat()),
                ("end", end.isoformat()),
                ("sort[0][column]", "period"),
                ("sort[0][direction]", "asc"),
                ("offset", str(offset)),
                ("length", str(page_size)),
            ]
        )
        return f"{self.base_url}{SPOT_PRICE_ENDPOINT}?{urllib.parse.urlencode(query)}"

    def _open_page(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Atlas-S10/0.1 (+local research cache)",
            },
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except Exception:
            # urllib exceptions may embed the full request URL, including api_key.
            raise EIARequestError(
                f"EIA request failed for {SPOT_PRICE_ENDPOINT}; credential omitted"
            ) from None
        if len(body) > MAX_RESPONSE_BYTES:
            raise EIAResponseError("EIA response exceeded the configured safety limit")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise EIAResponseError("EIA returned malformed JSON") from None
        if not isinstance(payload, dict):
            raise EIAResponseError("EIA response root must be a JSON object")
        return payload

    def fetch_daily_spot_prices(
        self,
        *,
        series: Iterable[str] | str,
        start: date | str,
        end: date | str,
        page_size: int = 5_000,
    ) -> EIAFetchResult:
        """Fetch and validate all pages for RBRTE and/or RWTC."""

        requested_series = _normalize_series(series)
        start_date = _coerce_date(start, "start")
        end_date = _coerce_date(end, "end")
        if start_date > end_date:
            raise ValueError("start cannot be after end")
        if not 1 <= page_size <= 5_000:
            raise ValueError("page_size must be between 1 and 5000")

        pages: list[EIAPage] = []
        records: list[dict[str, str]] = []
        seen_keys: set[tuple[str, str]] = set()
        expected_total: int | None = None
        offset = 0

        while expected_total is None or offset < expected_total:
            url = self._request_url(
                requested_series, start_date, end_date, offset, page_size
            )
            payload = self._open_page(url)
            response = payload.get("response")
            if not isinstance(response, Mapping) or not isinstance(response.get("data"), list):
                raise EIAResponseError("EIA response has no response.data array")
            if response.get("frequency") not in {None, "daily"}:
                raise EIAResponseError("EIA response frequency is not daily")
            if response.get("dateFormat") not in {None, "YYYY-MM-DD"}:
                raise EIAResponseError("EIA response date format is unexpected")
            try:
                page_total = int(response.get("total"))
            except (TypeError, ValueError):
                raise EIAResponseError("EIA response total is not an integer") from None
            if page_total < 0:
                raise EIAResponseError("EIA response total cannot be negative")
            if expected_total is None:
                expected_total = page_total
            elif expected_total != page_total:
                raise EIAResponseError("EIA response total changed during pagination")

            normalized_page: list[dict[str, str]] = []
            for raw_row in response["data"]:
                row = _normalize_api_row(
                    raw_row, requested_series, start_date, end_date
                )
                key = (row["series"], row["period"])
                if key in seen_keys:
                    raise EIAResponseError("EIA response contains a duplicate series/period")
                seen_keys.add(key)
                normalized_page.append(row)

            sanitized = _redact_payload(payload, self.__api_key)
            pages.append(
                EIAPage(
                    offset=offset,
                    total=page_total,
                    row_count=len(normalized_page),
                    payload=sanitized,
                )
            )
            records.extend(normalized_page)

            if not normalized_page:
                if offset < page_total:
                    raise EIAResponseError("EIA pagination ended before the advertised total")
                break
            offset += len(normalized_page)
            if len(pages) > 10_000:
                raise EIAResponseError("EIA pagination exceeded the defensive page limit")

        if expected_total is None or len(records) != expected_total:
            raise EIAResponseError("EIA pagination row count does not match response.total")
        records.sort(key=lambda row: (row["series"], row["period"]))
        return EIAFetchResult(
            series=requested_series,
            start=start_date,
            end=end_date,
            records=tuple(records),
            pages=tuple(pages),
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            temporary = Path(handle.name)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _serialize_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def _serialize_canonical(rows: Iterable[Mapping[str, str]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CANONICAL_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in CANONICAL_COLUMNS})
    return buffer.getvalue()


def _validate_canonical_row(row: Mapping[str, str]) -> dict[str, str]:
    missing = sorted(set(CANONICAL_COLUMNS) - set(row))
    if missing:
        raise EIAResponseError(f"EIA canonical cache is missing columns: {missing}")
    normalized = {column: str(row.get(column, "")).strip() for column in CANONICAL_COLUMNS}
    normalized["series"] = _normalize_series(normalized["series"])[0]
    try:
        normalized["period"] = date.fromisoformat(normalized["period"]).isoformat()
    except ValueError:
        raise EIAResponseError("EIA canonical cache contains an invalid period") from None
    normalized["value"] = _canonical_decimal(normalized["value"])
    normalized["units"] = normalized["units"].upper()
    if normalized["units"] != "$/BBL":
        raise EIAResponseError("EIA canonical cache units must be $/BBL")
    if not normalized["retrieved_at"] or not normalized["vintage_id"]:
        raise EIAResponseError("EIA canonical cache is missing vintage metadata")
    try:
        datetime.fromisoformat(normalized["retrieved_at"].replace("Z", "+00:00"))
    except ValueError:
        raise EIAResponseError("EIA canonical cache has an invalid retrieved_at") from None
    return normalized


def load_canonical_cache(path: Path) -> list[dict[str, str]]:
    """Load and strictly validate a canonical EIA daily cache."""

    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CANONICAL_COLUMNS:
            raise EIAResponseError("EIA canonical cache header does not match its contract")
        rows = [_validate_canonical_row(row) for row in reader]
    keys = [(row["series"], row["period"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise EIAResponseError("EIA canonical cache contains duplicate series/period rows")
    return sorted(rows, key=lambda row: (row["series"], row["period"]))


def _relative_to_root(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _create_vintage_directory(raw_root: Path, stem: str) -> Path:
    raw_root.mkdir(parents=True, exist_ok=True)
    for suffix in range(1_000):
        candidate = raw_root / (stem if suffix == 0 else f"{stem}-{suffix:02d}")
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise EIAError("Could not allocate a unique EIA vintage directory")


def import_eia_xls_snapshot(
    path: Path | str,
    *,
    root: Path = ROOT,
    expected_series: str = "RBRTE",
    retrieved_at: datetime | None = None,
    cache_path: Path = DEFAULT_CACHE_PATH,
    raw_dir: Path = DEFAULT_RAW_DIR,
) -> dict[str, Any]:
    """Merge a validated official XLS snapshot into the canonical daily cache."""

    root = root.resolve()
    source_path = Path(path).resolve()
    try:
        source_relative = source_path.relative_to(root).as_posix()
    except ValueError:
        raise ValueError("EIA XLS snapshot must be copied inside the project root") from None
    snapshot = parse_eia_xls_snapshot(source_path, expected_series=expected_series)
    if retrieved_at is None:
        retrieved_at = datetime.fromtimestamp(source_path.stat().st_mtime, UTC)
    stamp = _normalize_retrieved_at(retrieved_at)
    retrieved_iso = stamp.isoformat().replace("+00:00", "Z")

    canonical_path = cache_path if cache_path.is_absolute() else root / cache_path
    raw_root = raw_dir if raw_dir.is_absolute() else root / raw_dir
    existing = load_canonical_cache(canonical_path)
    stem = f"xls-{snapshot.release_date:%Y%m%d}-{snapshot.sha256[:12]}"
    vintage_dir = _create_vintage_directory(raw_root, stem)
    vintage_id = vintage_dir.name

    existing_by_key = {(row["series"], row["period"]): row for row in existing}
    merged_by_key = dict(existing_by_key)
    inserted = 0
    revised = 0
    confirmed = 0
    for source_row in snapshot.records:
        key = (source_row["series"], source_row["period"])
        old = existing_by_key.get(key)
        if old is None:
            inserted += 1
        elif any(old[column] != source_row[column] for column in SOURCE_COLUMNS):
            revised += 1
        else:
            confirmed += 1
        merged_by_key[key] = {
            **source_row,
            "retrieved_at": retrieved_iso,
            "vintage_id": vintage_id,
        }
    merged = sorted(merged_by_key.values(), key=lambda row: (row["series"], row["period"]))
    _atomic_write(canonical_path, _serialize_canonical(merged))

    merge = {
        "previous_rows": len(existing),
        "inserted_rows": inserted,
        "revised_rows": revised,
        "confirmed_rows": confirmed,
        "canonical_rows": len(merged),
    }
    manifest = {
        "schema_version": 1,
        "source": "U.S. Energy Information Administration",
        "ingestion": "official_historical_xls",
        "retrieved_at": retrieved_iso,
        "vintage_id": vintage_id,
        "series": snapshot.series,
        "frequency": snapshot.frequency,
        "release_date": snapshot.release_date.isoformat(),
        "next_release_date": (
            snapshot.next_release_date.isoformat() if snapshot.next_release_date else None
        ),
        "observation_start": snapshot.records[0]["period"],
        "observation_end": snapshot.latest_period.isoformat(),
        "source_snapshot": {
            "path": source_relative,
            "bytes": snapshot.bytes,
            "sha256": snapshot.sha256,
        },
        "merge": merge,
        "canonical": {
            "path": _relative_to_root(canonical_path, root),
            "bytes": canonical_path.stat().st_size,
            "sha256": _sha256(canonical_path),
        },
    }
    manifest_path = vintage_dir / "manifest.json"
    _atomic_write(manifest_path, _serialize_json(manifest))
    return {
        "status": "imported",
        "retrieved_at": retrieved_iso,
        "vintage_id": vintage_id,
        "manifest": _relative_to_root(manifest_path, root),
        "merge": merge,
        "cache": eia_cache_status(root, canonical_path),
    }


def eia_cache_status(
    root: Path = ROOT,
    cache_path: Path = DEFAULT_CACHE_PATH,
) -> dict[str, Any]:
    """Validate and summarize the local canonical cache without network access."""

    root = root.resolve()
    path = cache_path if cache_path.is_absolute() else root / cache_path
    rows = load_canonical_cache(path)
    if not rows:
        return {
            "status": "empty",
            "path": _relative_to_root(path, root),
            "rows": 0,
            "series": {},
        }
    coverage: dict[str, dict[str, Any]] = {}
    for series in sorted({row["series"] for row in rows}):
        periods = [row["period"] for row in rows if row["series"] == series]
        coverage[series] = {
            "rows": len(periods),
            "start": min(periods),
            "end": max(periods),
        }
    return {
        "status": "validated",
        "path": _relative_to_root(path, root),
        "rows": len(rows),
        "sha256": _sha256(path),
        "series": coverage,
    }


def sync_eia_spot_prices(
    *,
    root: Path = ROOT,
    series: Iterable[str] | str = ("RBRTE",),
    start: date | str | None = None,
    end: date | str | None = None,
    revision_lookback_days: int = 7,
    page_size: int = 5_000,
    retrieved_at: datetime | None = None,
    cache_path: Path = DEFAULT_CACHE_PATH,
    raw_dir: Path = DEFAULT_RAW_DIR,
    client: EIAClient | None = None,
) -> dict[str, Any]:
    """Incrementally refresh canonical daily spot prices and save a raw vintage.

    Existing series are refreshed from their latest period minus the configured
    revision lookback.  A caller-supplied ``start`` acts as a lower bound.  A
    missing series requires ``start`` so that the initial historical range is
    explicit rather than silently truncated.
    """

    requested_series = _normalize_series(series)
    if revision_lookback_days < 0:
        raise ValueError("revision_lookback_days cannot be negative")
    stamp = _normalize_retrieved_at(retrieved_at)
    end_date = _coerce_date(end or stamp.date(), "end")
    explicit_start = _coerce_date(start, "start") if start is not None else None
    if explicit_start is not None and explicit_start > end_date:
        raise ValueError("start cannot be after end")

    root = root.resolve()
    canonical_path = cache_path if cache_path.is_absolute() else root / cache_path
    raw_root = raw_dir if raw_dir.is_absolute() else root / raw_dir
    existing = load_canonical_cache(canonical_path)

    latest_by_series: dict[str, date] = {}
    for row in existing:
        current = date.fromisoformat(row["period"])
        latest_by_series[row["series"]] = max(
            latest_by_series.get(row["series"], current), current
        )

    requests: list[tuple[str, date]] = []
    for item in requested_series:
        latest = latest_by_series.get(item)
        if latest is None:
            if explicit_start is None:
                raise ValueError(
                    f"Initial sync for {item} requires an explicit --start date"
                )
            fetch_start = explicit_start
        else:
            fetch_start = latest - timedelta(days=revision_lookback_days)
            if explicit_start is not None:
                fetch_start = max(fetch_start, explicit_start)
        if fetch_start <= end_date:
            requests.append((item, fetch_start))

    if not requests:
        return {
            "status": "up_to_date",
            "retrieved_at": stamp.isoformat().replace("+00:00", "Z"),
            "cache": eia_cache_status(root, canonical_path),
            "requests": [],
        }

    active_client = client or EIAClient()
    fetches: list[EIAFetchResult] = []
    request_manifest: list[dict[str, Any]] = []
    for item, fetch_start in requests:
        fetched = active_client.fetch_daily_spot_prices(
            series=(item,),
            start=fetch_start,
            end=end_date,
            page_size=page_size,
        )
        fetches.append(fetched)
        request_manifest.append(
            {
                "series": item,
                "start": fetch_start.isoformat(),
                "end": end_date.isoformat(),
                "frequency": "daily",
                "rows": len(fetched.records),
                "pages": len(fetched.pages),
            }
        )

    fingerprint = hashlib.sha256(
        json.dumps(request_manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    stem = f"{stamp:%Y%m%dT%H%M%SZ}-{fingerprint}"
    vintage_dir = _create_vintage_directory(raw_root, stem)
    vintage_id = vintage_dir.name
    retrieved_iso = stamp.isoformat().replace("+00:00", "Z")

    raw_pages: list[dict[str, Any]] = []
    for fetched in fetches:
        label = "-".join(item.casefold() for item in fetched.series)
        for page in fetched.pages:
            page_path = vintage_dir / f"{label}-offset-{page.offset:08d}.json"
            _atomic_write(page_path, _serialize_json(page.payload))
            raw_pages.append(
                {
                    "path": _relative_to_root(page_path, root),
                    "series": list(fetched.series),
                    "offset": page.offset,
                    "rows": page.row_count,
                    "total": page.total,
                    "bytes": page_path.stat().st_size,
                    "sha256": _sha256(page_path),
                }
            )

    existing_by_key = {(row["series"], row["period"]): row for row in existing}
    merged_by_key = dict(existing_by_key)
    inserted = 0
    revised = 0
    confirmed = 0
    for fetched in fetches:
        for source_row in fetched.records:
            key = (source_row["series"], source_row["period"])
            old = existing_by_key.get(key)
            if old is None:
                inserted += 1
            elif any(old[column] != source_row[column] for column in SOURCE_COLUMNS):
                revised += 1
            else:
                confirmed += 1
            merged_by_key[key] = {
                **source_row,
                "retrieved_at": retrieved_iso,
                "vintage_id": vintage_id,
            }

    merged = sorted(merged_by_key.values(), key=lambda row: (row["series"], row["period"]))
    _atomic_write(canonical_path, _serialize_canonical(merged))

    manifest = {
        "schema_version": 1,
        "source": "U.S. Energy Information Administration",
        "endpoint": f"{active_client.base_url}{SPOT_PRICE_ENDPOINT}",
        "retrieved_at": retrieved_iso,
        "vintage_id": vintage_id,
        "credential_policy": (
            "EIA_API_KEY is read from the environment and redacted before persistence"
        ),
        "requests": request_manifest,
        "raw_pages": raw_pages,
        "merge": {
            "previous_rows": len(existing),
            "inserted_rows": inserted,
            "revised_rows": revised,
            "confirmed_rows": confirmed,
            "canonical_rows": len(merged),
        },
        "canonical": {
            "path": _relative_to_root(canonical_path, root),
            "bytes": canonical_path.stat().st_size,
            "sha256": _sha256(canonical_path),
        },
    }
    manifest_path = vintage_dir / "manifest.json"
    _atomic_write(manifest_path, _serialize_json(manifest))

    return {
        "status": "synced",
        "retrieved_at": retrieved_iso,
        "vintage_id": vintage_id,
        "manifest": _relative_to_root(manifest_path, root),
        "requests": request_manifest,
        "merge": manifest["merge"],
        "cache": eia_cache_status(root, canonical_path),
    }


def _parse_cli_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--network",
        action="store_true",
        help="Allow EIA HTTP requests; otherwise only validate the local cache.",
    )
    mode.add_argument(
        "--import-xls",
        type=Path,
        help="Import a local official EIA historical XLS without using an API key.",
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--series",
        nargs="+",
        choices=sorted(ALLOWED_SERIES),
        default=["RBRTE"],
    )
    parser.add_argument("--start", type=_parse_cli_date)
    parser.add_argument("--end", type=_parse_cli_date)
    parser.add_argument("--revision-lookback-days", type=int, default=7)
    parser.add_argument("--page-size", type=int, default=5_000)
    parser.add_argument(
        "--base-url",
        help=f"Override {EIA_API_BASE_URL_ENV}; credentials are not accepted here.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.import_xls:
            if len(args.series) != 1:
                raise ValueError("--import-xls accepts exactly one --series")
            result = import_eia_xls_snapshot(
                args.import_xls,
                root=args.root,
                expected_series=args.series[0],
            )
        elif args.network:
            load_dotenv(Path(args.root) / ".env", override=False)
            result = sync_eia_spot_prices(
                root=args.root,
                series=args.series,
                start=args.start,
                end=args.end,
                revision_lookback_days=args.revision_lookback_days,
                page_size=args.page_size,
                client=EIAClient(base_url=args.base_url),
            )
        else:
            result = eia_cache_status(args.root)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (EIAError, ValueError) as error:
        print(
            json.dumps({"status": "error", "message": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
