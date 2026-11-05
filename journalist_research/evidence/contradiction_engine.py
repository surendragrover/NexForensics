
"""
Deep OSINT Agent (DOA)
Contradiction Engine

Purpose
-------
Detect and preserve contradictions between investigative claims.

Core principle:

    CONTRADICTION != FALSEHOOD

A contradiction means that available claims/sources are
in conflict. The engine does not decide which source is true.

Rules
-----
1. Preserve both sides of a contradiction.
2. Never silently overwrite conflicting claims.
3. Never mark a claim false merely because another source differs.
4. Preserve source and claim provenance.
5. Distinguish direct contradiction from temporal difference.
6. Identity contradiction is separate from claim contradiction.
7. Confidence is not truth.
8. Human/source review remains necessary for final resolution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


# ============================================================
# ENUMS
# ============================================================

class ContradictionType(str, Enum):
    DIRECT = "DIRECT"
    TEMPORAL = "TEMPORAL"
    IDENTITY = "IDENTITY"
    NUMERIC = "NUMERIC"
    SOURCE = "SOURCE"
    STATUS = "STATUS"
    LOCATION = "LOCATION"
    OWNERSHIP = "OWNERSHIP"
    OTHER = "OTHER"


class ContradictionStatus(str, Enum):
    DETECTED = "DETECTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"


class ContradictionSeverity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ResolutionState(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    SUPPORT_A = "SUPPORT_A"
    SUPPORT_B = "SUPPORT_B"
    BOTH_PLAUSIBLE = "BOTH_PLAUSIBLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


# ============================================================
# CLAIM SIDE
# ============================================================

@dataclass
class ContradictionSide:
    """
    One side of a contradiction.

    The side is preserved verbatim as an investigative claim.
    """

    side_id: str

    claim_id: str

    claim_text: str

    source_ids: List[str] = field(
        default_factory=list
    )

    entity_ids: List[str] = field(
        default_factory=list
    )

    confidence: Optional[float] = None

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )


# ============================================================
# CONTRADICTION
# ============================================================

@dataclass
class Contradiction:
    """
    Structured contradiction between two or more claims.

    Neither side is automatically declared false.
    """

    contradiction_id: str

    contradiction_type: ContradictionType

    side_a: ContradictionSide

    side_b: ContradictionSide

    status: ContradictionStatus = (
        ContradictionStatus.DETECTED
    )

    severity: ContradictionSeverity = (
        ContradictionSeverity.MODERATE
    )

    resolution: ResolutionState = (
        ResolutionState.NOT_ASSESSED
    )

    explanation: str = ""

    source_ids: List[str] = field(
        default_factory=list
    )

    entity_ids: List[str] = field(
        default_factory=list
    )

    detected_by: Optional[str] = None

    resolved_by: Optional[str] = None

    resolution_note: Optional[str] = None

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    fact_established: bool = False

    guilt_established: bool = False


# ============================================================
# VALIDATION
# ============================================================

def validate_side(
    side: ContradictionSide,
) -> List[str]:

    errors = []

    if not side.side_id:
        errors.append(
            "side_id is required."
        )

    if not side.claim_id:
        errors.append(
            "claim_id is required."
        )

    if not side.claim_text:
        errors.append(
            "claim_text is required."
        )

    if side.confidence is not None:

        if not (
            0.0 <= side.confidence <= 1.0
        ):
            errors.append(
                "confidence must be between 0 and 1."
            )

    return errors


def validate_contradiction(
    contradiction: Contradiction,
) -> List[str]:

    errors = []

    if not contradiction.contradiction_id:
        errors.append(
            "contradiction_id is required."
        )

    if (
        contradiction.side_a.claim_id
        == contradiction.side_b.claim_id
    ):
        errors.append(
            "Contradiction sides must reference different claims."
        )

    errors.extend(
        validate_side(
            contradiction.side_a
        )
    )

    errors.extend(
        validate_side(
            contradiction.side_b
        )
    )

    if contradiction.fact_established:
        errors.append(
            "Contradiction engine cannot establish facts."
        )

    if contradiction.guilt_established:
        errors.append(
            "Contradiction engine cannot establish guilt."
        )

    return errors


# ============================================================
# HELPERS
# ============================================================

def new_id(
    prefix: str,
) -> str:

    return (
        f"{prefix}_{uuid4().hex}"
    )


def merge_unique(
    first: List[str],
    second: List[str],
) -> List[str]:

    return list(
        dict.fromkeys(
            first + second
        )
    )


# ============================================================
# BUILD SIDES
# ============================================================

def build_side(
    claim_id: str,
    claim_text: str,
    *,
    source_ids: Optional[List[str]] = None,
    entity_ids: Optional[List[str]] = None,
    confidence: Optional[float] = None,
) -> ContradictionSide:

    side = ContradictionSide(
        side_id=new_id("SIDE"),
        claim_id=claim_id,
        claim_text=claim_text,
        source_ids=list(
            source_ids or []
        ),
        entity_ids=list(
            entity_ids or []
        ),
        confidence=confidence,
    )

    errors = validate_side(
        side
    )

    if errors:
        raise ValueError(
            "; ".join(errors)
        )

    return side


# ============================================================
# BUILD CONTRADICTION
# ============================================================

def build_contradiction(
    side_a: ContradictionSide,
    side_b: ContradictionSide,
    contradiction_type: ContradictionType,
    *,
    severity: ContradictionSeverity = (
        ContradictionSeverity.MODERATE
    ),
    explanation: str = "",
    detected_by: Optional[str] = None,
) -> Contradiction:

    contradiction = Contradiction(
        contradiction_id=new_id("CONTRA"),
        contradiction_type=contradiction_type,
        side_a=side_a,
        side_b=side_b,
        status=ContradictionStatus.DETECTED,
        severity=severity,
        resolution=ResolutionState.NOT_ASSESSED,
        explanation=explanation,
        source_ids=merge_unique(
            side_a.source_ids,
            side_b.source_ids,
        ),
        entity_ids=merge_unique(
            side_a.entity_ids,
            side_b.entity_ids,
        ),
        detected_by=detected_by,
        metadata={
            "automatic_truth_decision": False,
            "both_sides_preserved": True,
            "human_review_possible": True,
        },
        fact_established=False,
        guilt_established=False,
    )

    errors = validate_contradiction(
        contradiction
    )

    if errors:
        raise ValueError(
            "; ".join(errors)
        )

    return contradiction


# ============================================================
# CONTRADICTION CLASSIFICATION
# ============================================================

def classify_contradiction(
    claim_a: str,
    claim_b: str,
) -> ContradictionType:

    a = claim_a.lower().strip()
    b = claim_b.lower().strip()

    # Explicit ownership language
    ownership_terms = (
        "owner",
        "owned by",
        "ownership",
        "shareholder",
    )

    if any(
        term in a or term in b
        for term in ownership_terms
    ):
        return ContradictionType.OWNERSHIP

    # Identity language
    identity_terms = (
        "is",
        "identified as",
        "belongs to",
        "identity",
    )

    if any(
        term in a or term in b
        for term in identity_terms
    ):
        return ContradictionType.IDENTITY

    # Numeric contradiction
    if any(
        character.isdigit()
        for character in a + b
    ):
        return ContradictionType.NUMERIC

    # Temporal contradiction
    temporal_terms = (
        "in ",
        "on ",
        "before",
        "after",
        "during",
        "date",
        "year",
    )

    if any(
        term in a or term in b
        for term in temporal_terms
    ):
        return ContradictionType.TEMPORAL

    return ContradictionType.DIRECT


# ============================================================
# TEXT CONTRADICTION DETECTION
# ============================================================

NEGATION_PAIRS = [
    ("was", "was not"),
    ("is", "is not"),
    ("did", "did not"),
    ("owned", "did not own"),
    ("registered", "was not registered"),
    ("located", "was not located"),
    ("worked", "did not work"),
]


def detect_direct_text_contradiction(
    claim_a: str,
    claim_b: str,
) -> bool:

    a = claim_a.lower().strip()
    b = claim_b.lower().strip()

    for positive, negative in NEGATION_PAIRS:

        if (
            positive in a
            and negative in b
        ):
            return True

        if (
            positive in b
            and negative in a
        ):
            return True

    return False


# ============================================================
# RESOLUTION
# ============================================================

def set_resolution(
    contradiction: Contradiction,
    resolution: ResolutionState,
    *,
    note: Optional[str] = None,
    resolved_by: Optional[str] = None,
) -> None:

    contradiction.resolution = resolution

    contradiction.resolution_note = note

    contradiction.resolved_by = resolved_by

    if resolution == ResolutionState.NOT_ASSESSED:

        contradiction.status = (
            ContradictionStatus.DETECTED
        )

    elif resolution == ResolutionState.HUMAN_REVIEW_REQUIRED:

        contradiction.status = (
            ContradictionStatus.UNRESOLVED
        )

    elif resolution == ResolutionState.INSUFFICIENT_EVIDENCE:

        contradiction.status = (
            ContradictionStatus.UNRESOLVED
        )

    else:

        contradiction.status = (
            ContradictionStatus.RESOLVED
        )

    # Resolution state does not itself establish fact.
    contradiction.fact_established = False
    contradiction.guilt_established = False


# ============================================================
# AUTOMATIC RESOLUTION GUARD
# ============================================================

def can_auto_resolve(
    contradiction: Contradiction,
) -> bool:

    """
    Conservative gate.

    The engine does not auto-resolve contradictions merely
    because one source has a higher nominal quality.
    """

    return False


# ============================================================
# BATCH DETECTION
# ============================================================

def detect_claim_contradictions(
    claims: List[Dict[str, Any]],
) -> List[Contradiction]:

    """
    Conservative pairwise contradiction detector.

    Expected claim dict fields:

        claim_id
        text
        source_ids
        entity_ids

    Only explicit direct textual contradiction is automatically
    detected here.

    Similarity alone is NOT treated as contradiction.
    """

    contradictions = []

    for index, claim_a in enumerate(claims):

        for claim_b in claims[index + 1:]:

            id_a = claim_a.get(
                "claim_id"
            )

            id_b = claim_b.get(
                "claim_id"
            )

            if not id_a or not id_b:
                continue

            text_a = (
                claim_a.get("text")
                or ""
            ).strip()

            text_b = (
                claim_b.get("text")
                or ""
            ).strip()

            if not text_a or not text_b:
                continue

            if not detect_direct_text_contradiction(
                text_a,
                text_b,
            ):
                continue

            side_a = build_side(
                claim_id=id_a,
                claim_text=text_a,
                source_ids=claim_a.get(
                    "source_ids",
                    [],
                ),
                entity_ids=claim_a.get(
                    "entity_ids",
                    [],
                ),
            )

            side_b = build_side(
                claim_id=id_b,
                claim_text=text_b,
                source_ids=claim_b.get(
                    "source_ids",
                    [],
                ),
                entity_ids=claim_b.get(
                    "entity_ids",
                    [],
                ),
            )

            contradiction = build_contradiction(
                side_a,
                side_b,
                classify_contradiction(
                    text_a,
                    text_b,
                ),
                explanation=(
                    "The two claims contain "
                    "explicitly conflicting statements."
                ),
                detected_by=(
                    "direct_text_contradiction"
                ),
            )

            contradictions.append(
                contradiction
            )

    return contradictions


# ============================================================
# REPORT
# ============================================================

def contradiction_summary(
    contradiction: Contradiction,
) -> Dict[str, Any]:

    return {
        "contradiction_id":
            contradiction.contradiction_id,

        "type":
            contradiction.contradiction_type.value,

        "status":
            contradiction.status.value,

        "severity":
            contradiction.severity.value,

        "resolution":
            contradiction.resolution.value,

        "claim_a":
            contradiction.side_a.claim_text,

        "claim_b":
            contradiction.side_b.claim_text,

        "source_ids":
            list(contradiction.source_ids),

        "entity_ids":
            list(contradiction.entity_ids),

        "fact_established":
            False,

        "guilt_established":
            False,

        "automatic_truth_decision":
            False,
    }


# ============================================================
# PUBLIC API
# ============================================================

__all__ = [
    "ContradictionType",
    "ContradictionStatus",
    "ContradictionSeverity",
    "ResolutionState",
    "ContradictionSide",
    "Contradiction",
    "new_id",
    "validate_side",
    "validate_contradiction",
    "build_side",
    "build_contradiction",
    "classify_contradiction",
    "detect_direct_text_contradiction",
    "set_resolution",
    "can_auto_resolve",
    "detect_claim_contradictions",
    "contradiction_summary",
]
