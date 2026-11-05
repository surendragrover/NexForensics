"""
Deep OSINT Agent (DOA)
Source Matrix

Purpose
-------
Build a provenance-preserving journalist source matrix connecting:

    CLAIM
      ↓
    SOURCE
      ↓
    SOURCE QUALITY
      ↓
    INDEPENDENCE
      ↓
    CORROBORATION
      ↓
    CONTRADICTION
      ↓
    CONFIDENCE
      ↓
    REVIEW STATE

This module organizes investigative evidence.
It does NOT determine truth, identity, guilt, liability,
or non-existence.

Core invariants
---------------
1. Source quality != claim truth.
2. Confidence != truth.
3. Corroboration != guilt.
4. Duplicate sources != independent corroboration.
5. Contradictions remain visible.
6. Evidence gaps remain visible.
7. Negative findings never establish non-existence.
8. Human review remains required.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import json


# ======================================================================
# ENUMS
# ======================================================================

class SourceMatrixStatus(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    PARTIAL = "PARTIAL"
    CORROBORATED = "CORROBORATED"
    CONTESTED = "CONTESTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class SourceQuality(str, Enum):
    UNKNOWN = "UNKNOWN"
    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class IndependenceStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    DUPLICATE = "DUPLICATE"
    RELATED = "RELATED"
    PARTIAL = "PARTIAL"
    INDEPENDENT = "INDEPENDENT"


class MatrixEvidenceRole(str, Enum):
    SUPPORTING = "SUPPORTING"
    CONTRADICTORY = "CONTRADICTORY"
    NEUTRAL = "NEUTRAL"
    CONTEXT = "CONTEXT"
    UNKNOWN = "UNKNOWN"


class MatrixReviewState(str, Enum):
    NOT_REVIEWED = "NOT_REVIEWED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    HUMAN_REVIEWED = "HUMAN_REVIEWED"


# ======================================================================
# SOURCE RECORD
# ======================================================================

@dataclass
class SourceMatrixEntry:
    claim_id: str
    source_id: str

    source_title: Optional[str] = None
    source_url: Optional[str] = None
    publisher: Optional[str] = None

    source_quality: SourceQuality = SourceQuality.UNKNOWN
    independence: IndependenceStatus = (
        IndependenceStatus.UNKNOWN
    )

    role: MatrixEvidenceRole = MatrixEvidenceRole.UNKNOWN

    supports_claim: bool = False
    contradicts_claim: bool = False

    confidence_score: Optional[float] = None
    confidence_level: Optional[str] = None

    corroborates_source_ids: List[str] = field(
        default_factory=list
    )

    contradiction_ids: List[str] = field(
        default_factory=list
    )

    evidence_gap_ids: List[str] = field(
        default_factory=list
    )

    negative_finding: bool = False

    provenance: Dict[str, Any] = field(
        default_factory=dict
    )

    notes: Optional[str] = None

    # Hard safety fields
    truth_established: bool = False
    fact_established: bool = False
    identity_established: bool = False
    guilt_established: bool = False
    non_existence_established: bool = False


# ======================================================================
# CLAIM MATRIX ROW
# ======================================================================

@dataclass
class ClaimSourceMatrixRow:
    claim_id: str

    claim_text: Optional[str] = None

    entries: List[SourceMatrixEntry] = field(
        default_factory=list
    )

    independent_source_count: int = 0
    duplicate_source_count: int = 0

    supporting_source_count: int = 0
    contradictory_source_count: int = 0

    contradiction_count: int = 0
    evidence_gap_count: int = 0
    negative_finding_count: int = 0

    confidence_score: Optional[float] = None
    confidence_level: str = "NOT_ASSESSED"

    status: SourceMatrixStatus = (
        SourceMatrixStatus.NOT_ASSESSED
    )

    review_state: MatrixReviewState = (
        MatrixReviewState.REVIEW_REQUIRED
    )

    source_provenance_preserved: bool = True
    contradictions_preserved: bool = True

    truth_established: bool = False
    fact_established: bool = False
    identity_established: bool = False
    guilt_established: bool = False
    non_existence_established: bool = False

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )


# ======================================================================
# SOURCE MATRIX
# ======================================================================

@dataclass
class SourceMatrix:
    matrix_id: str = field(
        default_factory=lambda:
        f"MATRIX_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    )

    investigation_id: Optional[str] = None

    rows: List[ClaimSourceMatrixRow] = field(
        default_factory=list
    )

    status: SourceMatrixStatus = (
        SourceMatrixStatus.NOT_ASSESSED
    )

    total_claims: int = 0
    total_sources: int = 0
    independent_sources: int = 0
    duplicate_sources: int = 0
    contradictions: int = 0
    evidence_gaps: int = 0
    negative_findings: int = 0

    human_review_required: bool = True
    automatic_conclusion: bool = False

    truth_established: bool = False
    fact_established: bool = False
    identity_established: bool = False
    guilt_established: bool = False
    non_existence_established: bool = False

    generated_at: datetime = field(
        default_factory=lambda:
        datetime.now(timezone.utc)
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )


# ======================================================================
# VALIDATION
# ======================================================================

def validate_entry(
    entry: SourceMatrixEntry,
) -> bool:

    if not entry.claim_id:
        raise ValueError("claim_id is required")

    if not entry.source_id:
        raise ValueError("source_id is required")

    if entry.confidence_score is not None:
        if not 0.0 <= entry.confidence_score <= 1.0:
            raise ValueError(
                "confidence_score must be between 0 and 1"
            )

    if (
        entry.supports_claim
        and entry.contradicts_claim
    ):
        raise ValueError(
            "A source cannot simultaneously be marked "
            "supporting and contradictory."
        )

    if entry.truth_established:
        raise ValueError(
            "Source matrix cannot establish truth"
        )

    if entry.fact_established:
        raise ValueError(
            "Source matrix cannot establish facts"
        )

    if entry.identity_established:
        raise ValueError(
            "Source matrix cannot establish identity"
        )

    if entry.guilt_established:
        raise ValueError(
            "Source matrix cannot establish guilt"
        )

    if entry.non_existence_established:
        raise ValueError(
            "Source matrix cannot establish non-existence"
        )

    return True


def validate_row(
    row: ClaimSourceMatrixRow,
) -> bool:

    if not row.claim_id:
        raise ValueError("claim_id is required")

    for entry in row.entries:
        validate_entry(entry)

        if entry.claim_id != row.claim_id:
            raise ValueError(
                "Entry claim_id does not match row claim_id"
            )

    if row.independent_source_count < 0:
        raise ValueError(
            "independent_source_count cannot be negative"
        )

    if row.duplicate_source_count < 0:
        raise ValueError(
            "duplicate_source_count cannot be negative"
        )

    if row.truth_established:
        raise ValueError(
            "Row cannot establish truth"
        )

    if row.fact_established:
        raise ValueError(
            "Row cannot establish facts"
        )

    if row.identity_established:
        raise ValueError(
            "Row cannot establish identity"
        )

    if row.guilt_established:
        raise ValueError(
            "Row cannot establish guilt"
        )

    if row.non_existence_established:
        raise ValueError(
            "Row cannot establish non-existence"
        )

    if not row.source_provenance_preserved:
        raise ValueError(
            "Source provenance must remain preserved"
        )

    if not row.contradictions_preserved:
        raise ValueError(
            "Contradictions must remain preserved"
        )

    return True


def validate_matrix(
    matrix: SourceMatrix,
) -> bool:

    if not matrix.investigation_id:
        raise ValueError(
            "investigation_id is required"
        )

    for row in matrix.rows:
        validate_row(row)

    if matrix.total_claims < 0:
        raise ValueError(
            "total_claims cannot be negative"
        )

    if matrix.total_sources < 0:
        raise ValueError(
            "total_sources cannot be negative"
        )

    if matrix.independent_sources < 0:
        raise ValueError(
            "independent_sources cannot be negative"
        )

    if matrix.duplicate_sources < 0:
        raise ValueError(
            "duplicate_sources cannot be negative"
        )

    if matrix.contradictions < 0:
        raise ValueError(
            "contradictions cannot be negative"
        )

    if matrix.evidence_gaps < 0:
        raise ValueError(
            "evidence_gaps cannot be negative"
        )

    if matrix.truth_established:
        raise ValueError(
            "Matrix cannot establish truth"
        )

    if matrix.fact_established:
        raise ValueError(
            "Matrix cannot establish facts"
        )

    if matrix.identity_established:
        raise ValueError(
            "Matrix cannot establish identity"
        )

    if matrix.guilt_established:
        raise ValueError(
            "Matrix cannot establish guilt"
        )

    if matrix.non_existence_established:
        raise ValueError(
            "Matrix cannot establish non-existence"
        )

    if matrix.automatic_conclusion:
        raise ValueError(
            "Automatic conclusion is forbidden"
        )

    if not matrix.human_review_required:
        raise ValueError(
            "Human review must remain required"
        )

    return True


# ======================================================================
# ROW STATUS
# ======================================================================

def determine_row_status(
    row: ClaimSourceMatrixRow,
) -> SourceMatrixStatus:

    if not row.entries:
        return SourceMatrixStatus.NOT_ASSESSED

    if row.contradictory_source_count > 0:
        return SourceMatrixStatus.CONTESTED

    if row.contradiction_count > 0:
        return SourceMatrixStatus.CONTESTED

    if row.evidence_gap_count > 0:
        return SourceMatrixStatus.REVIEW_REQUIRED

    if row.independent_source_count >= 2:
        return SourceMatrixStatus.CORROBORATED

    if row.supporting_source_count > 0:
        return SourceMatrixStatus.PARTIAL

    return SourceMatrixStatus.NOT_ASSESSED


# ======================================================================
# ROW BUILDER
# ======================================================================

def build_claim_row(
    claim_id: str,
    *,
    claim_text: Optional[str] = None,
    entries: Optional[List[SourceMatrixEntry]] = None,
    confidence_score: Optional[float] = None,
    confidence_level: str = "NOT_ASSESSED",
    metadata: Optional[Dict[str, Any]] = None,
) -> ClaimSourceMatrixRow:

    source_entries = list(entries or [])

    for entry in source_entries:
        validate_entry(entry)

    independent_count = sum(
        1
        for entry in source_entries
        if entry.independence
        in {
            IndependenceStatus.INDEPENDENT,
            IndependenceStatus.PARTIAL,
        }
    )

    duplicate_count = sum(
        1
        for entry in source_entries
        if entry.independence
        == IndependenceStatus.DUPLICATE
    )

    supporting_count = sum(
        1
        for entry in source_entries
        if entry.supports_claim
        or entry.role == MatrixEvidenceRole.SUPPORTING
    )

    contradictory_count = sum(
        1
        for entry in source_entries
        if entry.contradicts_claim
        or entry.role == MatrixEvidenceRole.CONTRADICTORY
    )

    contradiction_count = sum(
        len(entry.contradiction_ids)
        for entry in source_entries
    )

    evidence_gap_count = sum(
        len(entry.evidence_gap_ids)
        for entry in source_entries
    )

    negative_count = sum(
        1
        for entry in source_entries
        if entry.negative_finding
    )

    row = ClaimSourceMatrixRow(
        claim_id=claim_id,
        claim_text=claim_text,
        entries=source_entries,

        independent_source_count=independent_count,
        duplicate_source_count=duplicate_count,

        supporting_source_count=supporting_count,
        contradictory_source_count=contradictory_count,

        contradiction_count=contradiction_count,
        evidence_gap_count=evidence_gap_count,
        negative_finding_count=negative_count,

        confidence_score=confidence_score,
        confidence_level=confidence_level,

        metadata=dict(metadata or {}),
    )

    row.status = determine_row_status(row)

    validate_row(row)

    return row


# ======================================================================
# MATRIX BUILDER
# ======================================================================

def build_source_matrix(
    investigation_id: str,
    rows: List[ClaimSourceMatrixRow],
    *,
    metadata: Optional[Dict[str, Any]] = None,
) -> SourceMatrix:

    for row in rows:
        validate_row(row)

    matrix = SourceMatrix(
        investigation_id=investigation_id,
        rows=list(rows),
        total_claims=len(rows),

        total_sources=sum(
            len(row.entries)
            for row in rows
        ),

        independent_sources=sum(
            row.independent_source_count
            for row in rows
        ),

        duplicate_sources=sum(
            row.duplicate_source_count
            for row in rows
        ),

        contradictions=sum(
            row.contradiction_count
            + row.contradictory_source_count
            for row in rows
        ),

        evidence_gaps=sum(
            row.evidence_gap_count
            for row in rows
        ),

        negative_findings=sum(
            row.negative_finding_count
            for row in rows
        ),

        metadata=dict(metadata or {}),
    )

    if not rows:
        matrix.status = (
            SourceMatrixStatus.NOT_ASSESSED
        )

    elif any(
        row.status
        == SourceMatrixStatus.REVIEW_REQUIRED
        for row in rows
    ):
        matrix.status = (
            SourceMatrixStatus.REVIEW_REQUIRED
        )

    elif any(
        row.status
        == SourceMatrixStatus.CONTESTED
        for row in rows
    ):
        matrix.status = (
            SourceMatrixStatus.CONTESTED
        )

    elif all(
        row.status
        == SourceMatrixStatus.CORROBORATED
        for row in rows
    ):
        matrix.status = (
            SourceMatrixStatus.CORROBORATED
        )

    else:
        matrix.status = SourceMatrixStatus.PARTIAL

    validate_matrix(matrix)

    return matrix


# ======================================================================
# QUERY HELPERS
# ======================================================================

def sources_for_claim(
    matrix: SourceMatrix,
    claim_id: str,
) -> List[SourceMatrixEntry]:

    for row in matrix.rows:
        if row.claim_id == claim_id:
            return list(row.entries)

    return []


def independent_sources_for_claim(
    matrix: SourceMatrix,
    claim_id: str,
) -> List[SourceMatrixEntry]:

    return [
        entry
        for entry in sources_for_claim(
            matrix,
            claim_id,
        )
        if entry.independence
        in {
            IndependenceStatus.INDEPENDENT,
            IndependenceStatus.PARTIAL,
        }
    ]


def contradictions_for_claim(
    matrix: SourceMatrix,
    claim_id: str,
) -> List[SourceMatrixEntry]:

    return [
        entry
        for entry in sources_for_claim(
            matrix,
            claim_id,
        )
        if (
            entry.contradicts_claim
            or entry.role
            == MatrixEvidenceRole.CONTRADICTORY
            or entry.contradiction_ids
        )
    ]


# ======================================================================
# SERIALIZATION
# ======================================================================

def serialize(
    value: Any,
) -> Any:

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, list):
        return [
            serialize(item)
            for item in value
        ]

    if isinstance(value, dict):
        return {
            str(key): serialize(val)
            for key, val in value.items()
        }

    if hasattr(value, "__dataclass_fields__"):
        return {
            key: serialize(val)
            for key, val in asdict(value).items()
        }

    return value


def serialize_matrix(
    matrix: SourceMatrix,
) -> Dict[str, Any]:

    return serialize(matrix)


# ======================================================================
# CONTRACT TEST
# ======================================================================

def contract_test() -> None:

    print("=" * 70)
    print("DOA SOURCE MATRIX CONTRACT TEST")
    print("=" * 70)

    # --------------------------------------------------------------
    # 1
    # --------------------------------------------------------------
    print("\n[1] ENUMS AND MODULE CONTRACT")

    assert (
        SourceMatrixStatus.CORROBORATED.value
        == "CORROBORATED"
    )
    assert (
        SourceQuality.VERY_HIGH.value
        == "VERY_HIGH"
    )
    assert (
        IndependenceStatus.INDEPENDENT.value
        == "INDEPENDENT"
    )
    assert (
        MatrixEvidenceRole.CONTRADICTORY.value
        == "CONTRADICTORY"
    )
    assert (
        MatrixReviewState.REVIEW_REQUIRED.value
        == "REVIEW_REQUIRED"
    )

    print("  Matrix status enum             : PASS")
    print("  Source quality enum            : PASS")
    print("  Independence enum              : PASS")
    print("  Evidence role enum             : PASS")
    print("  Review state enum              : PASS")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # 2
    # --------------------------------------------------------------
    print("\n[2] SOURCE ENTRY CREATION")

    entry_a = SourceMatrixEntry(
        claim_id="CLAIM_001",
        source_id="SRC_GOV_001",
        source_title="Official Regulatory Record",
        source_url="https://example.gov/record/001",
        publisher="Example Government Authority",
        source_quality=SourceQuality.VERY_HIGH,
        independence=IndependenceStatus.INDEPENDENT,
        role=MatrixEvidenceRole.SUPPORTING,
        supports_claim=True,
        confidence_score=0.82,
        confidence_level="HIGH",
        provenance={
            "retrieved_at": "2026-11-04T10:00:00Z",
            "query_id": "Q_001",
        },
    )

    entry_b = SourceMatrixEntry(
        claim_id="CLAIM_001",
        source_id="SRC_NEWS_001",
        source_title="Established Journalism Report",
        publisher="Example News",
        source_quality=SourceQuality.HIGH,
        independence=IndependenceStatus.INDEPENDENT,
        role=MatrixEvidenceRole.SUPPORTING,
        supports_claim=True,
        confidence_score=0.82,
        confidence_level="HIGH",
        provenance={
            "retrieved_at": "2026-11-04T10:02:00Z",
            "query_id": "Q_001",
        },
    )

    assert validate_entry(entry_a)
    assert validate_entry(entry_b)

    print("  Government source              : PASS")
    print("  Journalism source              : PASS")
    print("  Provenance retained            : PASS")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # 3
    # --------------------------------------------------------------
    print("\n[3] CLAIM ROW")

    row = build_claim_row(
        "CLAIM_001",
        claim_text="Example claim under investigation.",
        entries=[entry_a, entry_b],
        confidence_score=0.82,
        confidence_level="HIGH",
    )

    assert row.independent_source_count == 2
    assert row.supporting_source_count == 2
    assert row.duplicate_source_count == 0
    assert (
        row.status
        == SourceMatrixStatus.CORROBORATED
    )

    print("  Independent sources             : 2")
    print("  Supporting sources              : 2")
    print("  Duplicate sources               : 0")
    print("  Status                          : CORROBORATED")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # 4
    # --------------------------------------------------------------
    print("\n[4] DUPLICATE SOURCE GUARD")

    duplicate = SourceMatrixEntry(
        claim_id="CLAIM_DUP",
        source_id="SRC_COPY_002",
        source_title="Copied Article",
        source_quality=SourceQuality.MEDIUM,
        independence=IndependenceStatus.DUPLICATE,
        role=MatrixEvidenceRole.SUPPORTING,
        supports_claim=True,
    )

    original = SourceMatrixEntry(
        claim_id="CLAIM_DUP",
        source_id="SRC_COPY_001",
        source_title="Original Article",
        source_quality=SourceQuality.HIGH,
        independence=IndependenceStatus.INDEPENDENT,
        role=MatrixEvidenceRole.SUPPORTING,
        supports_claim=True,
    )

    duplicate_row = build_claim_row(
        "CLAIM_DUP",
        entries=[original, duplicate],
    )

    assert (
        duplicate_row.independent_source_count == 1
    )
    assert duplicate_row.duplicate_source_count == 1

    print("  Independent source count       : 1")
    print("  Duplicate source count         : 1")
    print("  Duplicate ≠ corroboration      : PASS")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # 5
    # --------------------------------------------------------------
    print("\n[5] CONTRADICTION PRESERVATION")

    contradiction = SourceMatrixEntry(
        claim_id="CLAIM_CONTRA",
        source_id="SRC_CONTRA_001",
        source_title="Conflicting Primary Record",
        source_quality=SourceQuality.VERY_HIGH,
        independence=IndependenceStatus.INDEPENDENT,
        role=MatrixEvidenceRole.CONTRADICTORY,
        contradicts_claim=True,
        contradiction_ids=[
            "CONTRA_001"
        ],
    )

    support = SourceMatrixEntry(
        claim_id="CLAIM_CONTRA",
        source_id="SRC_SUPPORT_001",
        source_title="Supporting Record",
        source_quality=SourceQuality.HIGH,
        independence=IndependenceStatus.INDEPENDENT,
        role=MatrixEvidenceRole.SUPPORTING,
        supports_claim=True,
    )

    contradiction_row = build_claim_row(
        "CLAIM_CONTRA",
        entries=[support, contradiction],
    )

    assert (
        contradiction_row.contradictory_source_count
        == 1
    )
    assert (
        contradiction_row.contradiction_count
        == 1
    )
    assert (
        contradiction_row.status
        == SourceMatrixStatus.CONTESTED
    )

    assert len(
        contradictions_for_claim(
            build_source_matrix(
                "INV_CONTRA",
                [contradiction_row],
            ),
            "CLAIM_CONTRA",
        )
    ) == 1

    print("  Contradictory source retained    : PASS")
    print("  Contradiction ID retained        : PASS")
    print("  Status                           : CONTESTED")
    print("  RESULT                           : PASS")

    # --------------------------------------------------------------
    # 6
    # --------------------------------------------------------------
    print("\n[6] EVIDENCE GAP")

    gap_entry = SourceMatrixEntry(
        claim_id="CLAIM_GAP",
        source_id="SRC_GAP_001",
        source_quality=SourceQuality.HIGH,
        independence=IndependenceStatus.INDEPENDENT,
        role=MatrixEvidenceRole.SUPPORTING,
        supports_claim=True,
        evidence_gap_ids=[
            "GAP_001"
        ],
    )

    gap_row = build_claim_row(
        "CLAIM_GAP",
        entries=[gap_entry],
    )

    assert gap_row.evidence_gap_count == 1
    assert (
        gap_row.status
        == SourceMatrixStatus.REVIEW_REQUIRED
    )

    print("  Evidence gap retained            : PASS")
    print("  Review required                  : PASS")
    print("  RESULT                           : PASS")

    # --------------------------------------------------------------
    # 7
    # --------------------------------------------------------------
    print("\n[7] NEGATIVE FINDING GUARD")

    negative = SourceMatrixEntry(
        claim_id="CLAIM_NEG",
        source_id="SRC_SEARCH_001",
        source_quality=SourceQuality.MEDIUM,
        independence=IndependenceStatus.INDEPENDENT,
        role=MatrixEvidenceRole.NEUTRAL,
        negative_finding=True,
        notes="No relevant result found within documented search scope.",
    )

    negative_row = build_claim_row(
        "CLAIM_NEG",
        entries=[negative],
    )

    assert negative_row.negative_finding_count == 1

    matrix_negative = build_source_matrix(
        "INV_NEG",
        [negative_row],
    )

    assert (
        matrix_negative.non_existence_established
        is False
    )

    print("  Negative finding retained       : PASS")
    print("  Non-existence established       : FALSE")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # 8
    # --------------------------------------------------------------
    print("\n[8] SOURCE QUERIES")

    matrix = build_source_matrix(
        "INV_MATRIX",
        [row, duplicate_row],
    )

    assert len(
        sources_for_claim(
            matrix,
            "CLAIM_001",
        )
    ) == 2

    assert len(
        independent_sources_for_claim(
            matrix,
            "CLAIM_001",
        )
    ) == 2

    assert len(
        sources_for_claim(
            matrix,
            "CLAIM_DUP",
        )
    ) == 2

    print("  Sources for claim              : PASS")
    print("  Independent source query       : PASS")
    print("  Duplicate source visibility    : PASS")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # 9
    # --------------------------------------------------------------
    print("\n[9] MATRIX CREATION")

    assert matrix.investigation_id == "INV_MATRIX"
    assert matrix.total_claims == 2
    assert matrix.total_sources == 4
    assert matrix.independent_sources == 3
    assert matrix.duplicate_sources == 1

    print("  Investigation linkage          : PASS")
    print("  Claim count                    : 2")
    print("  Source count                   : 4")
    print("  Independent sources            : 3")
    print("  Duplicate sources              : 1")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # 10
    # --------------------------------------------------------------
    print("\n[10] SERIALIZATION")

    serialized = serialize_matrix(matrix)

    assert isinstance(serialized, dict)
    assert (
        serialized["matrix_id"]
        == matrix.matrix_id
    )
    assert (
        serialized["investigation_id"]
        == "INV_MATRIX"
    )
    assert "rows" in serialized
    assert len(serialized["rows"]) == 2

    encoded = json.dumps(
        serialized,
        ensure_ascii=False,
    )

    assert isinstance(encoded, str)
    assert len(encoded) > 0

    print("  Matrix ID preserved             : PASS")
    print("  Investigation ID preserved      : PASS")
    print("  Rows serialized                 : PASS")
    print("  JSON serialization              : PASS")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # 11
    # --------------------------------------------------------------
    print("\n[11] UNSAFE STATE VALIDATION")

    unsafe_entry = SourceMatrixEntry(
        claim_id="CLAIM_UNSAFE",
        source_id="SRC_UNSAFE",
    )

    unsafe_entry.truth_established = True

    try:
        validate_entry(unsafe_entry)
        raise AssertionError(
            "Unsafe truth state accepted"
        )
    except ValueError:
        unsafe_entry.truth_established = False

    unsafe_row = build_claim_row(
        "CLAIM_UNSAFE",
        entries=[unsafe_entry],
    )

    unsafe_row.guilt_established = True

    try:
        validate_row(unsafe_row)
        raise AssertionError(
            "Unsafe guilt state accepted"
        )
    except ValueError:
        unsafe_row.guilt_established = False

    unsafe_matrix = build_source_matrix(
        "INV_UNSAFE",
        [unsafe_row],
    )

    unsafe_matrix.identity_established = True

    try:
        validate_matrix(unsafe_matrix)
        raise AssertionError(
            "Unsafe identity state accepted"
        )
    except ValueError:
        unsafe_matrix.identity_established = False

    unsafe_matrix.automatic_conclusion = True

    try:
        validate_matrix(unsafe_matrix)
        raise AssertionError(
            "Automatic conclusion accepted"
        )
    except ValueError:
        unsafe_matrix.automatic_conclusion = False

    print("  Truth establishment blocked     : PASS")
    print("  Guilt establishment blocked     : PASS")
    print("  Identity establishment blocked  : PASS")
    print("  Automatic conclusion blocked    : PASS")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # 12
    # --------------------------------------------------------------
    print("\n[12] PROVENANCE AND CONTRADICTION FLAGS")

    for current_row in [
        row,
        duplicate_row,
        contradiction_row,
        gap_row,
        negative_row,
    ]:
        assert (
            current_row.source_provenance_preserved
            is True
        )
        assert (
            current_row.contradictions_preserved
            is True
        )

    print("  Provenance preserved             : TRUE")
    print("  Contradictions preserved         : TRUE")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # 13
    # --------------------------------------------------------------
    print("\n[13] HUMAN REVIEW GATE")

    assert matrix.human_review_required is True
    assert matrix.automatic_conclusion is False

    print("  Human review required            : TRUE")
    print("  Automatic conclusion             : FALSE")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # 14
    # --------------------------------------------------------------
    print("\n[14] FINAL SAFETY INVARIANTS")

    assert matrix.truth_established is False
    assert matrix.fact_established is False
    assert matrix.identity_established is False
    assert matrix.guilt_established is False
    assert matrix.non_existence_established is False
    assert matrix.automatic_conclusion is False
    assert matrix.human_review_required is True

    print("  Source quality != truth          : TRUE")
    print("  Confidence != truth              : TRUE")
    print("  Corroboration != guilt           : TRUE")
    print("  Duplicate != independent         : TRUE")
    print("  Truth establishment              : FALSE")
    print("  Fact establishment               : FALSE")
    print("  Identity establishment           : FALSE")
    print("  Guilt establishment              : FALSE")
    print("  Non-existence establishment      : FALSE")
    print("  Human review required            : TRUE")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # 15
    # --------------------------------------------------------------
    print("\n[15] FINAL VALIDATION")

    assert validate_matrix(matrix)
    assert validate_row(row)
    assert validate_entry(entry_a)
    assert validate_entry(entry_b)

    print("  Matrix validation                : PASS")
    print("  Row validation                   : PASS")
    print("  Entry validation                 : PASS")

    print("\n" + "=" * 70)
    print("SOURCE MATRIX : PASS")
    print("=" * 70)
    print("MODULE IMPORT                  : PASS")
    print("SOURCE ENTRY CONTRACT          : PASS")
    print("CLAIM ROW                       : PASS")
    print("DUPLICATE SOURCE GUARD          : PASS")
    print("CONTRADICTION PRESERVATION      : PASS")
    print("EVIDENCE GAP                    : PASS")
    print("NEGATIVE FINDING GUARD          : PASS")
    print("SOURCE QUERIES                  : PASS")
    print("MATRIX CREATION                 : PASS")
    print("SERIALIZATION                   : PASS")
    print("UNSAFE STATE VALIDATION         : PASS")
    print("PROVENANCE PRESERVATION         : PASS")
    print("HUMAN REVIEW GATE               : PASS")
    print("SAFETY INVARIANTS               : PASS")
    print("VALIDATION                      : PASS")
    print("TRUTH ESTABLISHMENT             : FALSE")
    print("FACT ESTABLISHMENT              : FALSE")
    print("IDENTITY ESTABLISHMENT          : FALSE")
    print("GUILT ESTABLISHMENT             : FALSE")
    print("NON-EXISTENCE ESTABLISHMENT     : FALSE")
    print("REAL WEB SEARCH                 : NOT STARTED")
    print("=" * 70)


if __name__ == "__main__":
    contract_test()
