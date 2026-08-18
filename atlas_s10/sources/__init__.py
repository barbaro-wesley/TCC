"""Conectores de fonte oficial do Atlas S10 ("agentes de busca de dados").

Cada conector implementa o protocolo ``Connector`` (base.py): ``fetch`` baixa e
valida um snapshot recente (rede opt-in); ``cached`` inventaria o cache local
validado. Novos conectores (EIA Brent, ANP distribuição/produtor, IPCA, biodiesel)
devem ser adicionados aqui e registrados em ``CONNECTORS``.
"""

from __future__ import annotations

from atlas_s10.sources.anp_produtor_importador import AnpProdutorImportadorConnector
from atlas_s10.sources.anp_revenda import AnpRevendaConnector
from atlas_s10.sources.base import Connector, FetchResult, atomic_download, relative, sha256
from atlas_s10.sources.bcb_ptax import BcbPtaxConnector
from atlas_s10.sources.ibge_ipca import IbgeIpcaConnector

CONNECTORS: list[Connector] = [
    AnpRevendaConnector(),
    BcbPtaxConnector(),
    AnpProdutorImportadorConnector(),
    IbgeIpcaConnector(),
]

__all__ = [
    "CONNECTORS",
    "Connector",
    "FetchResult",
    "AnpRevendaConnector",
    "BcbPtaxConnector",
    "AnpProdutorImportadorConnector",
    "IbgeIpcaConnector",
    "atomic_download",
    "relative",
    "sha256",
]
