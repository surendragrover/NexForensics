
"""
Deep OSINT Agent (DOA)
Source Provenance Layer

Purpose:
    Define the immutable provenance contract between a future
    search executor and the evidence system.

Important:
    Search results are NOT facts.
    A URL is NOT evidence by itself.
    A retrieved document is NOT automatically a verified claim.

Pipeline:

    Search Result
        ↓
    Source Record
        ↓
    Document Record
        ↓
    Claim
        ↓
    Evidence
        ↓
    Corroboration / Contradiction
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from uuid import uuid4

from journalist_research.models import (
    Source,
    SourceReliability,
    SourceType,
)


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def new_provenance_id(prefix: str) -> str:
    return (
        f"{prefix}_"
        f"{uuid4().hex}"
    )


def normalize_url(url: str) -> str:
    """
    Normalize URL only for identity/comparison.

    Original URL is preserved separately.
    """

    value = (url or "").strip()

    if not value:
        return ""

    parsed = urlparse(value)

    scheme = (
        parsed.scheme.lower()
        if parsed.scheme
        else ""
    )

    netloc = (
        parsed.netloc.lower()
        if parsed.netloc
        else ""
    )

    path = parsed.path or "/"

    if (
        len(path) > 1
        and path.endswith("/")
    ):
        path = path[:-1]

    query = parsed.query

    normalized = (
        f"{scheme}://{netloc}{path}"
    )

    if query:
        normalized += f"?{query}"

    return normalized


def sha256_text(
    text: str,
) -> str:

    return hashlib.sha256(
        (text or "").encode(
            "utf-8",
            errors="replace",
        )
    ).hexdigest()


def sha256_bytes(
    content: bytes,
) -> str:

    return hashlib.sha256(
        content
    ).hexdigest()


# ============================================================
# SEARCH RESULT
# ============================================================

@dataclass
class SearchResultRecord:
    """
    Raw result returned by a search provider.

    This object is deliberately NOT a Claim.
    """

    query_id: str
    query: str

    url: str
    title: str = ""

    snippet: str = ""

    rank: Optional[int] = None

    provider: str = ""

    retrieved_at: str = field(
        default_factory=utc_now
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    result_id: str = field(
        default_factory=lambda:
            new_provenance_id("RES")
    )

    search_performed: bool = True
    fact_establishment: bool = False


# ============================================================
# SOURCE RECORD
# ============================================================

@dataclass
class SourceRecord:
    """
    Provenance wrapper around a source.

    A SourceRecord identifies WHERE information came from.
    It does not establish whether the information is true.
    """

    source_id: str

    url: str

    source_type: SourceType

    title: str = ""

    publisher: str = ""

    author: str = ""

    published_at: Optional[str] = None

    retrieved_at: str = field(
        default_factory=utc_now
    )

    provider: str = ""

    original_url: str = ""

    normalized_url: str = ""

    reliability: SourceReliability = (
        SourceReliability.UNKNOWN
    )

    result_id: Optional[str] = None

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    fact_establishment: bool = False


# ============================================================
# DOCUMENT RECORD
# ============================================================

@dataclass
class DocumentRecord:
    """
    Retrieved document/page representation.

    Content is fingerprinted so later investigators can detect
    whether the underlying material changed.
    """

    document_id: str

    source_id: str

    url: str

    title: str = ""

    content: str = ""

    content_hash: str = ""

    retrieved_at: str = field(
        default_factory=utc_now
    )

    published_at: Optional[str] = None

    mime_type: Optional[str] = None

    http_status: Optional[int] = None

    language: Optional[str] = None

    archive_url: Optional[str] = None

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    fact_establishment: bool = False


# ============================================================
# PROVENANCE VALIDATION
# ============================================================

def validate_url(
    url: str,
) -> List[str]:

    errors: List[str] = []

    if not url:
        errors.append(
            "URL is empty."
        )
        return errors

    parsed = urlparse(url)

    if parsed.scheme not in {
        "http",
        "https",
    }:
        errors.append(
            "URL must use HTTP or HTTPS."
        )

    if not parsed.netloc:
        errors.append(
            "URL hostname is missing."
        )

    return errors


def validate_search_result(
    result: SearchResultRecord,
) -> List[str]:

    errors = []

    errors.extend(
        validate_url(
            result.url
        )
    )

    if not result.query_id:
        errors.append(
            "query_id is required."
        )

    if not result.query:
        errors.append(
            "query is required."
        )

    if not result.result_id:
        errors.append(
            "result_id is required."
        )

    if result.fact_establishment:
        errors.append(
            "Search result cannot establish a fact."
        )

    if not result.search_performed:
        errors.append(
            "Search result must represent a performed search."
        )

    return errors


def validate_source_record(
    source: SourceRecord,
) -> List[str]:

    errors = []

    errors.extend(
        validate_url(
            source.url
        )
    )

    if not source.source_id:
        errors.append(
            "source_id is required."
        )

    if not source.source_type:
        errors.append(
            "source_type is required."
        )

    if not source.retrieved_at:
        errors.append(
            "retrieved_at is required."
        )

    if source.fact_establishment:
        errors.append(
            "Source provenance cannot establish a fact."
        )

    return errors


def validate_document_record(
    document: DocumentRecord,
) -> List[str]:

    errors = []

    errors.extend(
        validate_url(
            document.url
        )
    )

    if not document.document_id:
        errors.append(
            "document_id is required."
        )

    if not document.source_id:
        errors.append(
            "source_id is required."
        )

    if not document.retrieved_at:
        errors.append(
            "retrieved_at is required."
        )

    if document.content and not document.content_hash:
        errors.append(
            "content_hash required when content exists."
        )

    if document.fact_establishment:
        errors.append(
            "Document cannot establish a fact."
        )

    return errors


# ============================================================
# BUILDERS
# ============================================================

def build_source_record(
    result: SearchResultRecord,
    source_type: SourceType,
    reliability: SourceReliability = SourceReliability.UNKNOWN,
    publisher: str = "",
    author: str = "",
    published_at: Optional[str] = None,
) -> SourceRecord:

    errors = validate_search_result(
        result
    )

    if errors:
        raise ValueError(
            "; ".join(errors)
        )

    normalized = normalize_url(
        result.url
    )

    return SourceRecord(
        source_id=new_provenance_id(
            "SRC"
        ),
        url=result.url,
        original_url=result.url,
        normalized_url=normalized,
        source_type=source_type,
        reliability=reliability,
        title=result.title,
        publisher=publisher,
        author=author,
        published_at=published_at,
        retrieved_at=result.retrieved_at,
        provider=result.provider,
        result_id=result.result_id,
        metadata={
            "query_id": result.query_id,
            "query": result.query,
            "rank": result.rank,
            "snippet": result.snippet,
        },
        fact_establishment=False,
    )


def build_document_record(
    source: SourceRecord,
    content: str,
    mime_type: Optional[str] = None,
    http_status: Optional[int] = None,
    language: Optional[str] = None,
    archive_url: Optional[str] = None,
) -> DocumentRecord:

    errors = validate_source_record(
        source
    )

    if errors:
        raise ValueError(
            "; ".join(errors)
        )

    return DocumentRecord(
        document_id=new_provenance_id(
            "DOC"
        ),
        source_id=source.source_id,
        url=source.url,
        title=source.title,
        content=content or "",
        content_hash=sha256_text(
            content or ""
        ),
        retrieved_at=utc_now(),
        published_at=source.published_at,
        mime_type=mime_type,
        http_status=http_status,
        language=language,
        archive_url=archive_url,
        metadata={
            "source_type":
                source.source_type.value,
            "publisher":
                source.publisher,
        },
        fact_establishment=False,
    )


# ============================================================
# PROVENANCE CHAIN
# ============================================================

@dataclass
class ProvenanceChain:
    """
    Explicit chain:

        Query
          ↓
        Result
          ↓
        Source
          ↓
        Document

    Claims and evidence are attached later.
    """

    query_id: str

    query: str

    result_id: str

    source_id: str

    document_id: str

    created_at: str = field(
        default_factory=utc_now
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    fact_establishment: bool = False


def build_provenance_chain(
    result: SearchResultRecord,
    source: SourceRecord,
    document: DocumentRecord,
) -> ProvenanceChain:

    if result.result_id != source.result_id:
        raise ValueError(
            "Result/source provenance mismatch."
        )

    if source.source_id != document.source_id:
        raise ValueError(
            "Source/document provenance mismatch."
        )

    return ProvenanceChain(
        query_id=result.query_id,
        query=result.query,
        result_id=result.result_id,
        source_id=source.source_id,
        document_id=document.document_id,
        metadata={
            "provider": result.provider,
            "retrieved_at":
                document.retrieved_at,
            "content_hash":
                document.content_hash,
        },
        fact_establishment=False,
    )


# ============================================================
# SERIALIZATION
# ============================================================

def serialize_provenance(
    value: Any,
) -> Dict[str, Any]:

    if hasattr(
        value,
        "__dataclass_fields__",
    ):
        result = {}

        for field_name in value.__dataclass_fields__:
            field_value = getattr(
                value,
                field_name,
            )

            if hasattr(
                field_value,
                "value",
            ):
                field_value = field_value.value

            result[field_name] = field_value

        return result

    raise TypeError(
        "Unsupported provenance object."
    )


# ============================================================
# PUBLIC API
# ============================================================

__all__ = [
    "SearchResultRecord",
    "SourceRecord",
    "DocumentRecord",
    "ProvenanceChain",
    "normalize_url",
    "sha256_text",
    "sha256_bytes",
    "build_source_record",
    "build_document_record",
    "build_provenance_chain",
    "validate_search_result",
    "validate_source_record",
    "validate_document_record",
    "serialize_provenance",
]
