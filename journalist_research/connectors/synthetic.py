"""
DOA Phase 3 - Synthetic Search Connector

No network access.

This connector exists solely to prove that:

SearchTask
    -> ConnectorResult
    -> SearchResultRecord
    -> SourceRecord
    -> DocumentRecord
    -> ProvenanceChain

works without losing provenance or safety invariants.
"""

from __future__ import annotations

from typing import List

from .base import (
    ConnectorResult,
    SearchConnector,
)

from journalist_research.evidence.source_provenance import (
    SearchResultRecord,
)


class SyntheticSearchConnector(SearchConnector):

    connector_name = "synthetic"
    provider_name = "synthetic_provider"

    def search(
        self,
        query: str,
        query_id: str,
        max_results: int = 10,
    ) -> List[ConnectorResult]:

        if not query or not query.strip():
            raise ValueError("query is required")

        if not query_id or not query_id.strip():
            raise ValueError("query_id is required")

        if max_results < 1:
            raise ValueError("max_results must be >= 1")

        fixtures = [
            ConnectorResult(
                query_id=query_id,
                query=query,
                url="https://example.test/example-corp",
                title="Example Corp - Corporate Profile",
                snippet=(
                    "Synthetic corporate profile used only for "
                    "connector contract testing."
                ),
                content=(
                    "Example Corp was incorporated in 2018. "
                    "This is synthetic test content and is not "
                    "evidence about a real organization."
                ),
                rank=1,
                provider=self.provider_name,
                publisher="Synthetic Test Publisher",
                source_type="CORPORATE",
                mime_type="text/html",
                http_status=200,
                language="en",
                metadata={
                    "synthetic": True,
                    "fixture_id": "SYN-001",
                },
                search_performed=True,
                fact_establishment=False,
                identity_establishment=False,
                guilt_establishment=False,
                non_existence_establishment=False,
            ),
            ConnectorResult(
                query_id=query_id,
                query=query,
                url="https://archive.example.test/example-corp",
                title="Archived Example Corp Page",
                snippet=(
                    "Synthetic archived result used to test "
                    "multiple-source provenance."
                ),
                content=(
                    "Archived synthetic material states that "
                    "Example Corp began operations in 2019."
                ),
                rank=2,
                provider=self.provider_name,
                publisher="Synthetic Archive",
                source_type="ARCHIVED_WEB",
                mime_type="text/html",
                http_status=200,
                language="en",
                metadata={
                    "synthetic": True,
                    "fixture_id": "SYN-002",
                },
                search_performed=True,
                fact_establishment=False,
                identity_establishment=False,
                guilt_establishment=False,
                non_existence_establishment=False,
            ),
        ]

        return fixtures[:max_results]


def to_search_result_record(
    result: ConnectorResult,
) -> SearchResultRecord:

    errors = validate_result_for_conversion(result)

    if errors:
        raise ValueError(
            "Invalid ConnectorResult: " +
            "; ".join(errors)
        )

    return SearchResultRecord(
        query_id=result.query_id,
        query=result.query,
        url=result.url,
        title=result.title,
        snippet=result.snippet,
        rank=result.rank,
        provider=result.provider,
        retrieved_at=result.retrieved_at,
        metadata={
            **result.metadata,
            "connector_name": "synthetic",
            "publisher": result.publisher,
            "published_at": result.published_at,
            "source_type": result.source_type,
            "mime_type": result.mime_type,
            "http_status": result.http_status,
            "language": result.language,
            "archive_url": result.archive_url,
        },
        search_performed=result.search_performed,
        fact_establishment=False,
    )


def validate_result_for_conversion(
    result: ConnectorResult,
) -> List[str]:

    from .base import validate_connector_result

    return validate_connector_result(result)
