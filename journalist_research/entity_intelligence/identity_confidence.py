
"""
Deep OSINT Agent (DOA)
Identity Confidence Engine

Purpose:
    Evaluate whether multiple independent identity signals are
    sufficient to support an identity-resolution decision.

Critical distinction:

    MATCH SCORE
        = similarity between candidate attributes

    IDENTITY CONFIDENCE
        = strength of independently corroborated evidence that
          the candidate is the same real-world entity

    GUILT / LIABILITY
        = completely separate investigative question

This module NEVER establishes guilt.

Conservative outcomes:

    NOT_ASSESSED
    LOW
    MODERATE
    HIGH
    CONFIRMED
    REJECTED

CONFIRMED identity requires:
    - multiple supporting signals
    - independent corroboration
    - adequate source quality
    - no unresolved critical contradiction
    - no critical identity gap

A name match alone can never produce HIGH or CONFIRMED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ============================================================
# ENUMS
# ============================================================

class IdentityConfidenceLevel(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class EvidenceIndependence(str, Enum):
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"
    PARTIAL = "PARTIAL"
    INDEPENDENT = "INDEPENDENT"
    MULTIPLE_INDEPENDENT = "MULTIPLE_INDEPENDENT"


class SourceQuality(str, Enum):
    UNKNOWN = "UNKNOWN"
    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class IdentitySignalType(str, Enum):
    NAME = "NAME"
    ALIAS = "ALIAS"
    LOCATION = "LOCATION"
    ORGANIZATION = "ORGANIZATION"
    ROLE = "ROLE"
    DATE = "DATE"
    DOMAIN = "DOMAIN"
    OFFICIAL_RECORD = "OFFICIAL_RECORD"
    VERIFIED_PROFILE = "VERIFIED_PROFILE"
    RELATIONSHIP = "RELATIONSHIP"
    OTHER = "OTHER"


# ============================================================
# SIGNAL
# ============================================================

@dataclass
class IdentityEvidenceSignal:
    """
    A single identity-related evidence signal.

    This is evidence about identity attribution only.
    It does not establish wrongdoing.
    """

    signal_id: str

    signal_type: IdentitySignalType

    description: str

    source_id: Optional[str] = None

    source_quality: SourceQuality = (
        SourceQuality.UNKNOWN
    )

    independence: EvidenceIndependence = (
        EvidenceIndependence.UNKNOWN
    )

    supports_identity: bool = True

    contradictory: bool = False

    critical: bool = False

    verified: bool = False

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )


# ============================================================
# RESULT
# ============================================================

@dataclass
class IdentityConfidenceResult:
    """
    Identity-confidence assessment.

    confidence_score is an investigative scoring aid,
    NOT a statistical probability.
    """

    subject: str

    candidate_id: str

    level: IdentityConfidenceLevel

    confidence_score: float

    supporting_signal_count: int

    independent_signal_count: int

    contradictory_signal_count: int

    critical_contradiction_count: int

    critical_gap_count: int

    independence: EvidenceIndependence

    supporting_source_ids: List[str] = field(
        default_factory=list
    )

    contradictory_source_ids: List[str] = field(
        default_factory=list
    )

    unresolved_gaps: List[str] = field(
        default_factory=list
    )

    reasons: List[str] = field(
        default_factory=list
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    identity_established: bool = False

    guilt_established: bool = False


# ============================================================
# VALIDATION
# ============================================================

def validate_signal(
    signal: IdentityEvidenceSignal,
) -> List[str]:

    errors = []

    if not signal.signal_id:
        errors.append(
            "signal_id is required."
        )

    if not signal.description:
        errors.append(
            "description is required."
        )

    return errors


def validate_result(
    result: IdentityConfidenceResult,
) -> List[str]:

    errors = []

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
        <= result.confidence_score
        <= 1.0
    ):
        errors.append(
            "confidence_score must be 0..1."
        )

    if result.guilt_established:
        errors.append(
            "Identity confidence cannot establish guilt."
        )

    if (
        result.level
        == IdentityConfidenceLevel.CONFIRMED
        and not result.identity_established
    ):
        errors.append(
            "CONFIRMED level requires "
            "identity_established=True."
        )

    if (
        result.identity_established
        and result.level
        != IdentityConfidenceLevel.CONFIRMED
    ):
        errors.append(
            "identity_established requires "
            "CONFIRMED level."
        )

    return errors


# ============================================================
# WEIGHTS
# ============================================================

SOURCE_WEIGHTS = {
    SourceQuality.UNKNOWN: 0.00,
    SourceQuality.VERY_LOW: 0.05,
    SourceQuality.LOW: 0.10,
    SourceQuality.MEDIUM: 0.20,
    SourceQuality.HIGH: 0.30,
    SourceQuality.VERY_HIGH: 0.40,
}


SIGNAL_WEIGHTS = {
    IdentitySignalType.NAME: 0.10,
    IdentitySignalType.ALIAS: 0.12,
    IdentitySignalType.LOCATION: 0.10,
    IdentitySignalType.ORGANIZATION: 0.14,
    IdentitySignalType.ROLE: 0.12,
    IdentitySignalType.DATE: 0.08,
    IdentitySignalType.DOMAIN: 0.18,
    IdentitySignalType.OFFICIAL_RECORD: 0.35,
    IdentitySignalType.VERIFIED_PROFILE: 0.25,
    IdentitySignalType.RELATIONSHIP: 0.18,
    IdentitySignalType.OTHER: 0.05,
}


# ============================================================
# INDEPENDENCE
# ============================================================

def calculate_independence(
    signals: List[IdentityEvidenceSignal],
) -> EvidenceIndependence:

    independent_source_ids = {
        signal.source_id
        for signal in signals
        if (
            signal.supports_identity
            and not signal.contradictory
            and signal.source_id
            and signal.independence
            in {
                EvidenceIndependence.INDEPENDENT,
                EvidenceIndependence.MULTIPLE_INDEPENDENT,
            }
        )
    }

    if len(independent_source_ids) >= 2:
        return (
            EvidenceIndependence.MULTIPLE_INDEPENDENT
        )

    if len(independent_source_ids) == 1:
        return (
            EvidenceIndependence.INDEPENDENT
        )

    partial_sources = {
        signal.source_id
        for signal in signals
        if (
            signal.supports_identity
            and not signal.contradictory
            and signal.source_id
            and signal.independence
            == EvidenceIndependence.PARTIAL
        )
    }

    if partial_sources:
        return EvidenceIndependence.PARTIAL

    return EvidenceIndependence.NONE


# ============================================================
# SCORE
# ============================================================

def calculate_identity_score(
    signals: List[IdentityEvidenceSignal],
) -> float:

    score = 0.0

    for signal in signals:

        if (
            not signal.supports_identity
            or signal.contradictory
        ):
            continue

        signal_weight = SIGNAL_WEIGHTS.get(
            signal.signal_type,
            SIGNAL_WEIGHTS[
                IdentitySignalType.OTHER
            ],
        )

        source_weight = SOURCE_WEIGHTS.get(
            signal.source_quality,
            0.0,
        )

        # Verified signals receive a modest multiplier.
        verification_multiplier = (
            1.15
            if signal.verified
            else 1.0
        )

        contribution = (
            signal_weight
            + source_weight
        ) * verification_multiplier

        score += contribution

    # Never exceed 1.
    return min(
        max(score, 0.0),
        1.0,
    )


# ============================================================
# ASSESSMENT
# ============================================================

def assess_identity_confidence(
    subject: str,
    candidate_id: str,
    signals: List[IdentityEvidenceSignal],
    critical_gaps: Optional[List[str]] = None,
) -> IdentityConfidenceResult:

    critical_gaps = (
        list(critical_gaps)
        if critical_gaps
        else []
    )

    supporting = [
        signal
        for signal in signals
        if (
            signal.supports_identity
            and not signal.contradictory
        )
    ]

    contradictory = [
        signal
        for signal in signals
        if signal.contradictory
    ]

    critical_contradictions = [
        signal
        for signal in contradictory
        if signal.critical
    ]

    independent_count = len({
        signal.source_id
        for signal in supporting
        if (
            signal.source_id
            and signal.independence
            in {
                EvidenceIndependence.INDEPENDENT,
                EvidenceIndependence.MULTIPLE_INDEPENDENT,
            }
        )
    })

    independence = calculate_independence(
        signals
    )

    score = calculate_identity_score(
        signals
    )

    reasons = []

    # --------------------------------------------------------
    # REJECTION
    # --------------------------------------------------------

    if critical_contradictions:

        level = (
            IdentityConfidenceLevel.REJECTED
        )

        score = 0.0

        reasons.append(
            "Critical contradictory identity evidence exists."
        )

    # --------------------------------------------------------
    # CRITICAL GAPS
    # --------------------------------------------------------

    elif critical_gaps:

        if score >= 0.65:
            level = (
                IdentityConfidenceLevel.MODERATE
            )
        elif score >= 0.30:
            level = (
                IdentityConfidenceLevel.LOW
            )
        else:
            level = (
                IdentityConfidenceLevel.NOT_ASSESSED
            )

        reasons.append(
            "Critical identity evidence gaps remain unresolved."
        )

    # --------------------------------------------------------
    # NO SUPPORT
    # --------------------------------------------------------

    elif not supporting:

        level = (
            IdentityConfidenceLevel.NOT_ASSESSED
        )

        reasons.append(
            "No supporting identity evidence is available."
        )

    # --------------------------------------------------------
    # NAME-ONLY / WEAK
    # --------------------------------------------------------

    elif (
        len(supporting) == 1
        and supporting[0].signal_type
        == IdentitySignalType.NAME
    ):

        level = (
            IdentityConfidenceLevel.LOW
        )

        reasons.append(
            "Name match alone is insufficient for identity resolution."
        )

    # --------------------------------------------------------
    # CONFIRMED
    #
    # Requirements:
    #   - at least 2 independent sources
    #   - at least 2 supporting signals
    #   - no contradiction
    #   - no critical gap
    #   - score >= 0.75
    # --------------------------------------------------------

    elif (
        independent_count >= 2
        and len(supporting) >= 2
        and score >= 0.75
        and not contradictory
    ):

        level = (
            IdentityConfidenceLevel.CONFIRMED
        )

        reasons.append(
            "Identity is supported by multiple "
            "independent sources without unresolved contradiction."
        )

    # --------------------------------------------------------
    # HIGH
    # --------------------------------------------------------

    elif (
        independent_count >= 1
        and len(supporting) >= 2
        and score >= 0.55
        and not critical_contradictions
    ):

        level = (
            IdentityConfidenceLevel.HIGH
        )

        reasons.append(
            "Multiple identity signals have independent support."
        )

    # --------------------------------------------------------
    # MODERATE
    # --------------------------------------------------------

    elif (
        len(supporting) >= 2
        and score >= 0.30
    ):

        level = (
            IdentityConfidenceLevel.MODERATE
        )

        reasons.append(
            "More than one identity signal exists, "
            "but independent corroboration is incomplete."
        )

    # --------------------------------------------------------
    # LOW
    # --------------------------------------------------------

    elif score > 0:

        level = (
            IdentityConfidenceLevel.LOW
        )

        reasons.append(
            "Identity evidence is weak or insufficiently corroborated."
        )

    else:

        level = (
            IdentityConfidenceLevel.NOT_ASSESSED
        )

        reasons.append(
            "Identity confidence cannot currently be assessed."
        )

    # --------------------------------------------------------
    # RESULT
    # --------------------------------------------------------

    supporting_source_ids = sorted({
        signal.source_id
        for signal in supporting
        if signal.source_id
    })

    contradictory_source_ids = sorted({
        signal.source_id
        for signal in contradictory
        if signal.source_id
    })

    result = IdentityConfidenceResult(
        subject=subject,
        candidate_id=candidate_id,
        level=level,
        confidence_score=score,
        supporting_signal_count=len(
            supporting
        ),
        independent_signal_count=independent_count,
        contradictory_signal_count=len(
            contradictory
        ),
        critical_contradiction_count=len(
            critical_contradictions
        ),
        critical_gap_count=len(
            critical_gaps
        ),
        independence=independence,
        supporting_source_ids=(
            supporting_source_ids
        ),
        contradictory_source_ids=(
            contradictory_source_ids
        ),
        unresolved_gaps=critical_gaps,
        reasons=reasons,
        metadata={
            "score_is_probability": False,
            "score_is_guilt_probability": False,
            "identity_only": True,
            "multiple_independent_sources_required_for_confirmation": True,
            "name_only_can_confirm": False,
        },
        identity_established=(
            level
            == IdentityConfidenceLevel.CONFIRMED
        ),
        guilt_established=False,
    )

    errors = validate_result(
        result
    )

    if errors:
        raise ValueError(
            "; ".join(errors)
        )

    return result


# ============================================================
# PUBLIC API
# ============================================================

__all__ = [
    "IdentityConfidenceLevel",
    "EvidenceIndependence",
    "SourceQuality",
    "IdentitySignalType",
    "IdentityEvidenceSignal",
    "IdentityConfidenceResult",
    "validate_signal",
    "validate_result",
    "calculate_independence",
    "calculate_identity_score",
    "assess_identity_confidence",
]
