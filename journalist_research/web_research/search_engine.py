"""
DOA Phase 3B - Public Web Search Connector

Provider-neutral public-web search boundary.

The connector itself does not decide:
- truth
- identity
- guilt
- non-existence

It only converts provider results into the canonical
SearchResultRecord contract.

Supported provider adapters are intentionally isolated.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from journalist_research.evidence.source_provenance import (
    SearchResultRecord,
)


@dataclass
class WebSearchItem:
    """Provider-neutral raw web result."""

    url: str
    title: str = ""
    snippet: str = ""
    rank: Optional[int] = None
    published_at: Optional[str] = None

    provider: str = ""
    query_id: str = ""
    query: str = ""

    metadata: Dict[str, Any] = field(default_factory=dict)

    search_performed: bool = True

    # Safety invariants.
    fact_establishment: bool = False
    identity_establishment: bool = False
    guilt_establishment: bool = False
    non_existence_establishment: bool = False


class PublicWebProvider(ABC):
    """
    Provider interface.

    An implementation may use:
      - an approved search API
      - an authorized search service
      - another lawful public-web search backend

    No credentials are stored here.
    """

    provider_name: str = "abstract"

    @abstractmethod
    def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> List[WebSearchItem]:
        raise NotImplementedError


class PublicWebSearchConnector:
    """
    Public-web connector.

    This class owns normalization and safety validation.
    Provider-specific network code remains outside it.
    """

    connector_name = "public_web"

    def __init__(self, provider: PublicWebProvider):
        if not isinstance(provider, PublicWebProvider):
            raise TypeError(
                "provider must implement PublicWebProvider"
            )

        self.provider = provider

    @staticmethod
    def _validate_url(url: str) -> bool:
        try:
            parsed = urlparse(url)

            return (
                parsed.scheme in {"http", "https"}
                and bool(parsed.netloc)
            )

        except Exception:
            return False

    @classmethod
    def validate_item(
        cls,
        item: WebSearchItem,
    ) -> List[str]:

        errors: List[str] = []

        if not item.query_id.strip():
            errors.append("query_id is required")

        if not item.query.strip():
            errors.append("query is required")

        if not cls._validate_url(item.url):
            errors.append("valid http/https URL is required")

        if item.search_performed is not True:
            errors.append("search_performed must be True")

        if item.fact_establishment:
            errors.append(
                "web search cannot establish fact"
            )

        if item.identity_establishment:
            errors.append(
                "web search cannot establish identity"
            )

        if item.guilt_establishment:
            errors.append(
                "web search cannot establish guilt"
            )

        if item.non_existence_establishment:
            errors.append(
                "web search cannot establish non-existence"
            )

        if item.rank is not None and (
            not isinstance(item.rank, int)
            or item.rank < 1
        ):
            errors.append(
                "rank must be None or positive integer"
            )

        return errors

    def search(
        self,
        query: str,
        query_id: str,
        max_results: int = 10,
    ) -> List[SearchResultRecord]:

        if not query or not query.strip():
            raise ValueError("query is required")

        if not query_id or not query_id.strip():
            raise ValueError("query_id is required")

        if max_results < 1:
            raise ValueError(
                "max_results must be >= 1"
            )

        raw_results = self.provider.search(
            query=query,
            max_results=max_results,
        )

        records: List[SearchResultRecord] = []

        for rank, item in enumerate(
            raw_results[:max_results],
            start=1,
        ):

            # Connector owns canonical query identity.
            item.query_id = query_id
            item.query = query

            if item.rank is None:
                item.rank = rank

            if not item.provider:
                item.provider = (
                    self.provider.provider_name
                )

            errors = self.validate_item(item)

            if errors:
                raise ValueError(
                    "Invalid public-web result: "
                    + "; ".join(errors)
                )

            records.append(
                SearchResultRecord(
                    query_id=item.query_id,
                    query=item.query,
                    url=item.url,
                    title=item.title,
                    snippet=item.snippet,
                    rank=item.rank,
                    provider=item.provider,
                    metadata={
                        **item.metadata,
                        "connector": self.connector_name,
                        "provider": item.provider,
                        "public_web": True,
                    },
                    search_performed=True,
                    fact_establishment=False,
                )
            )

        return records
