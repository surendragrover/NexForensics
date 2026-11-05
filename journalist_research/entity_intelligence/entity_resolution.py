
"""
Deep OSINT Agent (DOA)
Entity Resolution Engine

Purpose:
    Convert extracted subject candidates into structured entity
    candidates without prematurely declaring identity.

Core principle:

    Name Match != Identity Match

Pipeline:

    Candidate
        ↓
    Normalization
        ↓
    Candidate Entity
        ↓
    Attribute Comparison
        ↓
    Supporting Signals
        ↓
    Contradictory Signals
        ↓
    Identity Decision

Valid outcomes:

    UNRESOLVED
    POSSIBLE_MATCH
    PROBABLE_MATCH
    CONFIRMED_MATCH
    REJECTED_MATCH

A match can NEVER become CONFIRMED merely because:
    - the name is identical
    - the location is identical
    - one source mentions the entity
    - search ranking is high

Wrong-person rejection is a first-class outcome.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


# ============================================================
# ENUMS
# ============================================================

class ResolutionStatus(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    POSSIBLE_MATCH = "POSSIBLE_MATCH"
    PROBABLE_MATCH = "PROBABLE_MATCH"
    CONFIRMED_MATCH = "CONFIRMED_MATCH"
    REJECTED_MATCH = "REJECTED_MATCH"


class MatchSignal(str, Enum):
    NAME = "NAME"
    ALIAS = "ALIAS"
    LOCATION = "LOCATION"
    ORGANIZATION = "ORGANIZATION"
    ROLE = "ROLE"
    DATE = "DATE"
    DOMAIN = "DOMAIN"
    SOURCE = "SOURCE"
    OTHER = "OTHER"


# ============================================================
# HELPERS
# ============================================================

def new_entity_id() -> str:
    return f"RESOLVE_{uuid4().hex}"


def normalize_value(
    value: str,
) -> str:

    value = (value or "").strip().lower()

    value = re.sub(
        r"[^a-z0-9\s@._-]",
        " ",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def tokenize(
    value: str,
) -> set[str]:

    normalized = normalize_value(
        value
    )

    if not normalized:
        return set()

    return set(
        normalized.split()
    )


def token_overlap(
    left: str,
    right: str,
) -> float:

    a = tokenize(left)
    b = tokenize(right)

    if not a or not b:
        return 0.0

    return len(a & b) / len(
        a | b
    )


# ============================================================
# CANDIDATE ENTITY
# ============================================================

@dataclass
class EntityCandidate:
    """
    Candidate identity.

    This is NOT yet a resolved identity.
    """

    candidate_id: str

    name: str

    entity_type: str = "UNKNOWN"

    aliases: List[str] = field(
        default_factory=list
    )

    locations: List[str] = field(
        default_factory=list
    )

    organizations: List[str] = field(
        default_factory=list
    )

    roles: List[str] = field(
        default_factory=list
    )

    dates: List[str] = field(
        default_factory=list
    )

    domains: List[str] = field(
        default_factory=list
    )

    source_ids: List[str] = field(
        default_factory=list
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )


# ============================================================
# RESOLUTION SIGNAL
# ============================================================

@dataclass
class ResolutionSignal:
    signal: MatchSignal

    matched: bool

    value_left: str = ""

    value_right: str = ""

    weight: float = 0.0

    source_id: Optional[str] = None

    reason: str = ""

    contradictory: bool = False


# ============================================================
# RESOLUTION RESULT
# ============================================================

@dataclass
class ResolutionResult:
    """
    Result of comparing a subject candidate against a possible
    identity.

    The score is a matching signal score, NOT a probability of
    identity and NOT a confidence that a person committed an act.
    """

    resolution_id: str

    subject: str

    candidate_id: str

    status: ResolutionStatus

    match_score: float

    signals: List[ResolutionSignal] = field(
        default_factory=list
    )

    supporting_source_ids: List[str] = field(
        default_factory=list
    )

    contradictory_source_ids: List[str] = field(
        default_factory=list
    )

    rejection_reasons: List[str] = field(
        default_factory=list
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    identity_established: bool = False


# ============================================================
# VALIDATION
# ============================================================

def validate_candidate(
    candidate: EntityCandidate,
) -> List[str]:

    errors = []

    if not candidate.candidate_id:
        errors.append(
            "candidate_id is required."
        )

    if not candidate.name:
        errors.append(
            "candidate name is required."
        )

    return errors


def validate_resolution(
    result: ResolutionResult,
) -> List[str]:

    errors = []

    if not result.resolution_id:
        errors.append(
            "resolution_id is required."
        )

    if not result.subject:
        errors.append(
            "subject is required."
        )

    if not result.candidate_id:
        errors.append(
            "candidate_id is required."
        )

    if not (
        0.0
        <= result.match_score
        <= 1.0
    ):
        errors.append(
            "match_score must be 0..1."
        )

    if result.identity_established:
        errors.append(
            "Identity cannot be established by raw resolution."
        )

    return errors


# ============================================================
# SIGNAL COMPARISON
# ============================================================

def compare_text_values(
    left_values: List[str],
    right_values: List[str],
    signal: MatchSignal,
    weight: float,
) -> List[ResolutionSignal]:

    signals = []

    for left in left_values:

        for right in right_values:

            overlap = token_overlap(
                left,
                right,
            )

            if overlap == 0:
                continue

            signals.append(
                ResolutionSignal(
                    signal=signal,
                    matched=True,
                    value_left=left,
                    value_right=right,
                    weight=weight * overlap,
                    reason=(
                        f"{signal.value.lower()} "
                        "token overlap detected."
                    ),
                )
            )

    return signals


def compare_candidate(
    subject: str,
    candidate: EntityCandidate,
) -> ResolutionResult:

    signals: List[ResolutionSignal] = []

    # --------------------------------------------------------
    # NAME
    # --------------------------------------------------------

    name_score = token_overlap(
        subject,
        candidate.name,
    )

    if name_score > 0:

        signals.append(
            ResolutionSignal(
                signal=MatchSignal.NAME,
                matched=True,
                value_left=subject,
                value_right=candidate.name,
                weight=0.45 * name_score,
                reason=(
                    "Candidate name overlaps "
                    "with subject candidate."
                ),
            )
        )

    # --------------------------------------------------------
    # ALIAS
    # --------------------------------------------------------

    signals.extend(
        compare_text_values(
            [subject],
            candidate.aliases,
            MatchSignal.ALIAS,
            0.25,
        )
    )

    # --------------------------------------------------------
    # LOCATION
    # --------------------------------------------------------

    signals.extend(
        compare_text_values(
            [subject],
            candidate.locations,
            MatchSignal.LOCATION,
            0.10,
        )
    )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    raw_score = sum(
        signal.weight
        for signal in signals
        if signal.matched
        and not signal.contradictory
    )

    score = min(
        max(raw_score, 0.0),
        1.0,
    )

    # --------------------------------------------------------
    # CRITICAL RULE:
    # Name alone can NEVER establish identity.
    # --------------------------------------------------------

    matched_signal_types = {
        signal.signal
        for signal in signals
        if signal.matched
    }

    if (
        matched_signal_types
        == {MatchSignal.NAME}
    ):
        status = ResolutionStatus.POSSIBLE_MATCH

    elif (
        MatchSignal.NAME in matched_signal_types
        and len(matched_signal_types) >= 2
    ):
        status = ResolutionStatus.PROBABLE_MATCH

    else:
        status = ResolutionStatus.UNRESOLVED

    result = ResolutionResult(
        resolution_id=new_entity_id(),
        subject=subject,
        candidate_id=candidate.candidate_id,
        status=status,
        match_score=score,
        signals=signals,
        supporting_source_ids=list(
            candidate.source_ids
        ),
        contradictory_source_ids=[],
        rejection_reasons=[],
        metadata={
            "matched_signal_types": [
                signal.value
                for signal in matched_signal_types
            ],
            "name_only_match":
                matched_signal_types
                == {MatchSignal.NAME},
            "identity_rule":
                "name_match_alone_is_not_identity",
        },
        identity_established=False,
    )

    errors = validate_resolution(
        result
    )

    if errors:
        raise ValueError(
            "; ".join(errors)
        )

    return result


# ============================================================
# CONTRADICTION / WRONG-PERSON REJECTION
# ============================================================

def reject_candidate(
    result: ResolutionResult,
    reason: str,
    source_id: Optional[str] = None,
) -> ResolutionResult:

    result.status = (
        ResolutionStatus.REJECTED_MATCH
    )

    result.rejection_reasons.append(
        reason
    )

    if source_id:
        result.contradictory_source_ids.append(
            source_id
        )

    for signal in result.signals:
        if signal.matched:
            signal.contradictory = True

    result.identity_established = False

    return result


# ============================================================
# BATCH RESOLUTION
# ============================================================

def resolve_subject(
    subject: str,
    candidates: List[EntityCandidate],
) -> List[ResolutionResult]:

    results = []

    for candidate in candidates:

        result = compare_candidate(
            subject,
            candidate,
        )

        results.append(
            result
        )

    return results


def rank_resolution_results(
    results: List[ResolutionResult],
) -> List[ResolutionResult]:

    priority = {
        ResolutionStatus.CONFIRMED_MATCH: 0,
        ResolutionStatus.PROBABLE_MATCH: 1,
        ResolutionStatus.POSSIBLE_MATCH: 2,
        ResolutionStatus.UNRESOLVED: 3,
        ResolutionStatus.REJECTED_MATCH: 4,
    }

    return sorted(
        results,
        key=lambda result: (
            priority.get(
                result.status,
                99,
            ),
            -result.match_score,
        ),
    )


# ============================================================
# PUBLIC API
# ============================================================

__all__ = [
    "ResolutionStatus",
    "MatchSignal",
    "EntityCandidate",
    "ResolutionSignal",
    "ResolutionResult",
    "normalize_value",
    "token_overlap",
    "compare_candidate",
    "resolve_subject",
    "rank_resolution_results",
    "reject_candidate",
    "validate_candidate",
    "validate_resolution",
]
