"""Contrato comum dos conectores de fonte oficial ("agentes de busca de dados").

Cada conector segue o mesmo protocolo:

* download **atômico**: escreve num arquivo temporário, valida o schema e só
  então substitui o alvo — nunca deixa um arquivo meio-baixado no lugar do bom;
* **validação** que falha alto se o contrato da fonte mudar;
* **proveniência**: hash SHA-256, URL, bytes e timestamp de cada snapshot.

A rede é opt-in. Sem rede, os conectores apenas reportam o inventário do cache
local validado — nunca inventam dados.
"""

from __future__ import annotations

import hashlib
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from atlas_s10.config import DATA_DIR, ROOT

CACHE_DIR = DATA_DIR / "cache"
USER_AGENT = "Atlas-S10/0.1 (+research demo)"

Validator = Callable[[Path], dict[str, Any]]


def sha256(path: Path) -> str:
    """Return a streaming SHA-256 digest for provenance."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    """Repo-relative POSIX path for stable provenance records."""
    return str(path.relative_to(ROOT)).replace("\\", "/")


def now_iso() -> str:
    """Current UTC timestamp at second precision."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def atomic_download(
    url: str, target: Path, validator: Validator, *, timeout: int = 60
) -> dict[str, Any]:
    """Download ``url`` to a temp file, validate it, then atomically replace ``target``.

    The target is only ever replaced by a payload that passed ``validator``; a
    failed download or a schema mismatch leaves any previous good file intact.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    temp_path: Path | None = None
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=target.parent, prefix=f".{target.name}.", delete=False
            ) as handle:
                temp_path = Path(handle.name)
                while chunk := response.read(1024 * 1024):
                    handle.write(chunk)
        details = validator(temp_path)
        temp_path.replace(target)
        temp_path = None
        return details
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


@dataclass(frozen=True)
class FetchResult:
    """Provenance record for one downloaded official snapshot."""

    source: str
    url: str
    path: str
    fetched_at: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "url": self.url,
            "path": self.path,
            "fetched_at": self.fetched_at,
            **self.details,
        }


@runtime_checkable
class Connector(Protocol):
    """A source connector: fetches (online) and inventories (offline) one source."""

    id: str
    source: str

    def fetch(self, today: date | None = None) -> FetchResult: ...

    def cached(self) -> list[dict[str, Any]]: ...
