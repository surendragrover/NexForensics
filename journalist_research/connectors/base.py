"""
DOA Phase 3 - Search Connector Contract

This module defines the boundary between a search provider
and the evidence/provenance pipeline.

IMPORTANT:
- A search result is NOT a fact.
- Connector output does NOT establish identity.
- Connector output does NOT establish guilt.
- Connector output does NOT establish non-existence.
- Provenance must survive connector -> evidence ingestion.
- Network access is deliberately absent from this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from abc import ABC, abstractmethod


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ConnectorResult:
    """
    Provider-neutral result returned by a search connector.

    This is intentionally separate from SearchResultRecord.
    The connector boundary owns provider output; the evidence
    layer owns canonical provenance.
    """

    query_id: str
    query: str
    url: str

    title: str = ""
    snippet: str = ""
    content: str = ""

    rank: Optional[int] = None
    provider: str = ""

    retrieved_at: str = field(default_factory=utc_now)

    published_at: Optional[str] = None
    publisher: str = ""

    source_type: Optional[str] = None

    mime_type: Optional[str] = None
    http_status: Optional[int] = None
    language: Optional[str] = None
    archive_url: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)

    # Safety invariants.
    search_performed: bool = True
    fact_establishment: bool = False
    identity_establishment: bool = False
    guilt_establishment: bool = False
    non_existence_establishment: bool = False


class SearchConnector(ABC):
    """
    Provider-neutral connector interface.

    Implementations may later represent:
      - public web search
      - archive search
      - authorized dark-web search

    This base class performs no network activity.
    """

    connector_name: str = "abstract"
    provider_name: str = "unknown"

    @abstractmethod
    def search(
        self,
        query: str,
        query_id: str,
        max_results: int = 10,
    ) -> List[ConnectorResult]:
        """
        Execute a provider search and return provider-neutral
        ConnectorResult objects.
        """
        raise NotImplementedError


def validate_connector_result(
    result: ConnectorResult,
) -> List[str]:
    """
    Validate the connector safety contract.

    Returns an empty list when valid.
    """

    errors: List[str] = []

    if not isinstance(result.query_id, str) or not result.query_id.strip():
        errors.append("query_id is required")

    if not isinstance(result.query, str) or not result.query.strip():
        errors.append("query is required")

    if not isinstance(result.url, str) or not result.url.strip():
        errors.append("url is required")

    if result.search_performed is not True:
        errors.append("search_performed must be True for connector results")

    if result.fact_establishment:
        errors.append("connector cannot establish fact")

    if result.identity_establishment:
        errors.append("connector cannot establish identity")

    if result.guilt_establishment:
        errors.append("connector cannot establish guilt")

    if result.non_existence_establishment:
        errors.append("connector cannot establish non-existence")

    if result.rank is not None and (
        not isinstance(result.rank, int) or result.rank < 1
    ):
        errors.append("rank must be None or positive integer")

    if not isinstance(result.metadata, dict):
        errors.append("metadata must be a dict")

    return errors
