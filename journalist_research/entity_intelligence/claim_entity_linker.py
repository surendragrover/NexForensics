
"""
Deep OSINT Agent (DOA)
Claim ↔ Entity Linker

Purpose
-------
Link an extracted investigative claim to one or more resolved
entity candidates without silently converting a linkage into
identity establishment or factual verification.

Core rule:

    CLAIM LINKAGE != IDENTITY ESTABLISHMENT != GUILT

Pipeline:

    Extracted Claim
          ↓
    Subject Candidate
          ↓
    Entity Resolution
          ↓
    Identity Confidence
          ↓
    Claim ↔ Entity Link
          ↓
    Corroboration / Contradiction
          ↓
    Timeline / Relationship Graph

Safety rules
------------
1. A claim must never be attached to a REJECTED entity.
2. A POSSIBLE entity may receive only a tentative linkage.
3. A PROBABLE entity may receive a conditional linkage.
4. A CONFIRMED entity may receive a confirmed identity linkage,
   but the claim itself remains independently unverified until
   corroborated.
5. Entity linkage never establishes guilt.
6. Entity linkage never changes Claim.status.
7. Entity linkage never invents evidence.
8. An unresolved subject remains unresolved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ============================================================
# ENUMS
# ============================================================

class ClaimEntityLinkStatus(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    TENTATIVE = "TENTATIVE"
    CONDITIONAL = "CONDITIONAL"
    CONFIRMED_IDENTITY = "CONFIRMED_IDENTITY"
    REJECTED = "REJECTED"


class LinkBasis(str, Enum):
    SUBJECT_CANDIDATE = "SUBJECT_CANDIDATE"
    NAME_MATCH = "NAME_MATCH"
    ALIAS_MATCH = "ALIAS_MATCH"
    ENTITY_RESOLUTION = "ENTITY_RESOLUTION"
    IDENTITY_CONFIDENCE = "IDENTITY_CONFIDENCE"
    EXPLICIT_SOURCE_REFERENCE = "EXPLICIT_SOURCE_REFERENCE"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class ClaimTruthState(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    CORROBORATED = "CORROBORATED"
    CONTRADICTED = "CONTRADICTED"
    ESTABLISHED = "ESTABLISHED"
    UNKNOWN = "UNKNOWN"


# ============================================================
# LINK RECORD
# ============================================================

@dataclass
class ClaimEntityLink:
    """
    Relationship between a claim and an entity.

    This record describes attribution/linkage only.
    It does NOT establish that the claim is true.
    """

    link_id: str

    claim_id: str

    entity_id: str

    status: ClaimEntityLinkStatus

    basis: List[LinkBasis] = field(
        default_factory=list
    )

    linkage_score: float = 0.0

    identity_confidence_level: str = (
        "NOT_ASSESSED"
    )

    supporting_source_ids: List[str] = field(
        default_factory=list
    )

    contradiction_source_ids: List[str] = field(
        default_factory=list
    )

    reasons: List[str] = field(
        default_factory=list
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    claim_truth_state: ClaimTruthState = (
        ClaimTruthState.UNVERIFIED
    )

    fact_established: bool = False

    guilt_established: bool = False


# ============================================================
# VALIDATION
# ============================================================

def validate_link(
    link: ClaimEntityLink,
) -> List[str]:

    errors = []

    if not link.link_id:
        errors.append(
            "link_id is required."
        )

    if not link.claim_id:
        errors.append(
            "claim_id is required."
        )

    if not link.entity_id:
        errors.append(
            "entity_id is required."
        )

    if not (
        0.0
        <= link.linkage_score
        <= 1.0
    ):
        errors.append(
            "linkage_score must be between 0 and 1."
        )

    if link.fact_established:
        errors.append(
            "Claim/entity linkage cannot establish facts."
        )

    if link.guilt_established:
        errors.append(
            "Claim/entity linkage cannot establish guilt."
        )

    if (
        link.status
        == ClaimEntityLinkStatus.REJECTED
        and link.fact_established
    ):
        errors.append(
            "Rejected linkage cannot establish facts."
        )

    return errors


# ============================================================
# ID GENERATOR
# ============================================================

def new_link_id() -> str:
    from uuid import uuid4

    return (
        "LINK_"
        + uuid4().hex
    )


# ============================================================
# RESOLUTION EXTRACTION
# ============================================================

def _resolution_level(
    resolution: Any,
) -> str:

    if resolution is None:
        return "NOT_ASSESSED"

    level = getattr(
        resolution,
        "level",
        None,
    )

    if level is None:
        return "NOT_ASSESSED"

    value = getattr(
        level,
        "value",
        level,
    )

    return str(
        value
    )


def _resolution_status(
    resolution: Any,
) -> str:

    if resolution is None:
        return "UNRESOLVED"

    status = getattr(
        resolution,
        "status",
        None,
    )

    if status is None:
        return "UNRESOLVED"

    return str(
        getattr(
            status,
            "value",
            status,
        )
    )


# ============================================================
# LINK DECISION
# ============================================================

def build_claim_entity_link(
    claim_id: str,
    entity_id: str,
    resolution: Any = None,
    identity_confidence: Any = None,
    explicit_source_reference: bool = False,
    manual_review: bool = False,
) -> ClaimEntityLink:
    """
    Build a claim/entity link from existing identity-resolution
    outputs.

    The function intentionally does NOT receive a truth value
    for the claim. Claim truth remains independent.
    """

    basis: List[LinkBasis] = []

    reasons: List[str] = []

    resolution_status = _resolution_status(
        resolution
    )

    confidence_level = _resolution_level(
        identity_confidence
    )

    if resolution_status in {
        "POSSIBLE_MATCH",
        "PROBABLE_MATCH",
        "CONFIRMED_MATCH",
    }:
        basis.append(
            LinkBasis.ENTITY_RESOLUTION
        )

    if resolution_status == "POSSIBLE_MATCH":
        basis.append(
            LinkBasis.NAME_MATCH
        )

    if explicit_source_reference:
        basis.append(
            LinkBasis.EXPLICIT_SOURCE_REFERENCE
        )

    if manual_review:
        basis.append(
            LinkBasis.MANUAL_REVIEW
        )

    # --------------------------------------------------------
    # REJECTED ENTITY
    # --------------------------------------------------------

    if (
        resolution_status
        == "REJECTED_MATCH"
    ):

        status = (
            ClaimEntityLinkStatus.REJECTED
        )

        score = 0.0

        reasons.append(
            "Entity resolution rejected this candidate."
        )

    # --------------------------------------------------------
    # CONFIRMED IDENTITY
    # --------------------------------------------------------

    elif (
        resolution_status
        == "CONFIRMED_MATCH"
        and confidence_level
        == "CONFIRMED"
    ):

        status = (
            ClaimEntityLinkStatus.CONFIRMED_IDENTITY
        )

        score = 1.0

        reasons.append(
            "Claim may be attributed to the confirmed "
            "identity, while claim truth remains independent."
        )

    # --------------------------------------------------------
    # PROBABLE
    # --------------------------------------------------------

    elif (
        resolution_status
        == "PROBABLE_MATCH"
        or confidence_level
        in {
            "HIGH",
            "MODERATE",
        }
    ):

        status = (
            ClaimEntityLinkStatus.CONDITIONAL
        )

        score = 0.70

        reasons.append(
            "Entity attribution is conditionally supported; "
            "identity is not treated as fully confirmed."
        )

    # --------------------------------------------------------
    # POSSIBLE
    # --------------------------------------------------------

    elif (
        resolution_status
        == "POSSIBLE_MATCH"
        or confidence_level
        == "LOW"
    ):

        status = (
            ClaimEntityLinkStatus.TENTATIVE
        )

        score = 0.40

        reasons.append(
            "Entity attribution is tentative and requires "
            "additional identity corroboration."
        )

    # --------------------------------------------------------
    # UNRESOLVED
    # --------------------------------------------------------

    else:

        status = (
            ClaimEntityLinkStatus.UNRESOLVED
        )

        score = 0.0

        reasons.append(
            "No sufficiently resolved entity is available."
        )

    link = ClaimEntityLink(
        link_id=new_link_id(),
        claim_id=claim_id,
        entity_id=entity_id,
        status=status,
        basis=basis,
        linkage_score=score,
        identity_confidence_level=(
            confidence_level
        ),
        supporting_source_ids=[],
        contradiction_source_ids=[],
        reasons=reasons,
        metadata={
            "claim_truth_is_independent": True,
            "identity_resolution_status":
                resolution_status,
            "fact_established": False,
            "human_verified": False,
        },
        claim_truth_state=(
            ClaimTruthState.UNVERIFIED
        ),
        fact_established=False,
        guilt_established=False,
    )

    errors = validate_link(
        link
    )

    if errors:
        raise ValueError(
            "; ".join(errors)
        )

    return link


# ============================================================
# SOURCE ATTACHMENT
# ============================================================

def attach_supporting_source(
    link: ClaimEntityLink,
    source_id: str,
) -> ClaimEntityLink:

    if (
        source_id
        and source_id
        not in link.supporting_source_ids
    ):
        link.supporting_source_ids.append(
            source_id
        )

    return link


def attach_contradictory_source(
    link: ClaimEntityLink,
    source_id: str,
) -> ClaimEntityLink:

    if (
        source_id
        and source_id
        not in link.contradiction_source_ids
    ):
        link.contradiction_source_ids.append(
            source_id
        )

    return link


# ============================================================
# CLAIM TRUTH STATE
# ============================================================

def set_claim_truth_state(
    link: ClaimEntityLink,
    state: ClaimTruthState,
) -> ClaimEntityLink:
    """
    Explicitly records the current claim truth state.

    This must be supplied by a separate evidence/corroboration
    layer. The linker itself does not infer truth.
    """

    link.claim_truth_state = state

    # Truth state is intentionally NOT copied into
    # fact_established automatically.
    link.fact_established = False

    return link


# ============================================================
# SAFETY FILTER
# ============================================================

def reject_if_wrong_entity(
    link: ClaimEntityLink,
    reason: str,
    source_id: Optional[str] = None,
) -> ClaimEntityLink:

    link.status = (
        ClaimEntityLinkStatus.REJECTED
    )

    link.linkage_score = 0.0

    link.reasons.append(
        reason
    )

    if source_id:
        attach_contradictory_source(
            link,
            source_id,
        )

    link.fact_established = False
    link.guilt_established = False

    return link


# ============================================================
# BATCH LINKING
# ============================================================

def link_claim_to_entities(
    claim_id: str,
    entity_resolutions: List[Any],
    identity_confidence_by_candidate: Optional[
        Dict[str, Any]
    ] = None,
) -> List[ClaimEntityLink]:

    identity_confidence_by_candidate = (
        identity_confidence_by_candidate
        or {}
    )

    links = []

    for resolution in entity_resolutions:

        candidate_id = getattr(
            resolution,
            "candidate_id",
            None,
        )

        if not candidate_id:
            continue

        confidence = (
            identity_confidence_by_candidate.get(
                candidate_id
            )
        )

        link = build_claim_entity_link(
            claim_id=claim_id,
            entity_id=candidate_id,
            resolution=resolution,
            identity_confidence=confidence,
        )

        links.append(
            link
        )

    return links


# ============================================================
# PUBLIC API
# ============================================================

__all__ = [
    "ClaimEntityLinkStatus",
    "LinkBasis",
    "ClaimTruthState",
    "ClaimEntityLink",
    "validate_link",
    "new_link_id",
    "build_claim_entity_link",
    "attach_supporting_source",
    "attach_contradictory_source",
    "set_claim_truth_state",
    "reject_if_wrong_entity",
    "link_claim_to_entities",
]
