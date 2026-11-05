"""
Deep OSINT Agent (DOA)
Confidence Engine

Purpose
-------
Evaluate investigative confidence from evidence quality, independent
corroboration, contradiction, and evidence gaps.

Core principle
--------------
CONFIDENCE != TRUTH
CONFIDENCE != IDENTITY
CONFIDENCE != GUILT

The engine evaluates the strength of the available investigative
record. It does not automatically establish facts, identity, guilt,
liability, or non-existence.

Safety invariants
-----------------
1. Confidence never establishes a fact automatically.
2. Confidence never establishes guilt.
3. Confidence never establishes identity.
4. Confidence is not a probability of truth.
5. Independent corroboration is distinguished from repeated copies.
6. Contradictions reduce confidence and remain visible.
7. Critical evidence gaps block HIGH / CONFIRMED confidence.
8. Negative findings do not become positive evidence of non-existence.
9. Human review remains required for final investigative conclusions.
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

class ConfidenceLevel(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CONFIRMED = "CONFIRMED"


class EvidenceStrength(str, Enum):
    NONE = "NONE"
    WEAK = "WEAK"
    MODERATE = "MODERATE"
    STRONG = "STRONG"
    VERY_STRONG = "VERY_STRONG"


class IndependenceLevel(str, Enum):
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"
    PARTIAL = "PARTIAL"
    INDEPENDENT = "INDEPENDENT"
    MULTIPLE_INDEPENDENT = "MULTIPLE_INDEPENDENT"


class ContradictionLevel(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MATERIAL = "MATERIAL"
    CRITICAL = "CRITICAL"


class EvidenceGapSeverity(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ======================================================================
# HELPERS
# ======================================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str = "CONF") -> str:
    return f"{prefix}_{utc_now().strftime('%Y%m%d%H%M%S%f')}"


def clamp(
    value: float,
    minimum: float = 0.0,
    maximum: float = 1.0,
) -> float:
    return max(minimum, min(maximum, float(value)))


# ======================================================================
# DATACLASSES
# ======================================================================

@dataclass
class ConfidenceEvidence:
    evidence_id: str
    source_id: Optional[str] = None
    evidence_strength: EvidenceStrength = EvidenceStrength.NONE
    source_quality: float = 0.0
    independent: bool = False
    supports_claim: bool = True
    notes: Optional[str] = None
    provenance: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConfidenceAssessment:
    assessment_id: str = field(
        default_factory=lambda: new_id("CONF")
    )
    claim_id: Optional[str] = None

    score: Optional[float] = None
    level: ConfidenceLevel = ConfidenceLevel.NOT_ASSESSED

    evidence_count: int = 0
    supporting_evidence_count: int = 0
    independent_source_count: int = 0

    evidence_strength: EvidenceStrength = EvidenceStrength.NONE
    independence: IndependenceLevel = IndependenceLevel.NONE

    contradiction_level: ContradictionLevel = ContradictionLevel.NONE
    contradiction_count: int = 0

    evidence_gap_severity: EvidenceGapSeverity = (
        EvidenceGapSeverity.NONE
    )
    evidence_gaps: List[str] = field(default_factory=list)

    negative_finding_count: int = 0
    negative_finding_is_nonexistence: bool = False

    rationale: List[str] = field(default_factory=list)

    assessed_at: datetime = field(default_factory=utc_now)

    # Safety state
    truth_established: bool = False
    fact_established: bool = False
    identity_established: bool = False
    guilt_established: bool = False
    non_existence_established: bool = False
    human_review_required: bool = True

    metadata: Dict[str, Any] = field(default_factory=dict)


# ======================================================================
# VALIDATION
# ======================================================================

def validate_confidence_evidence(
    evidence: ConfidenceEvidence,
) -> bool:

    if not evidence.evidence_id:
        raise ValueError("evidence_id is required")

    if not 0.0 <= evidence.source_quality <= 1.0:
        raise ValueError(
            "source_quality must be between 0 and 1"
        )

    if not isinstance(evidence.provenance, dict):
        raise ValueError("provenance must be a dictionary")

    return True


def validate_confidence_assessment(
    assessment: ConfidenceAssessment,
) -> bool:

    if assessment.score is not None:
        if not 0.0 <= assessment.score <= 1.0:
            raise ValueError(
                "confidence score must be between 0 and 1"
            )

    if assessment.evidence_count < 0:
        raise ValueError("evidence_count cannot be negative")

    if assessment.supporting_evidence_count < 0:
        raise ValueError(
            "supporting_evidence_count cannot be negative"
        )

    if assessment.independent_source_count < 0:
        raise ValueError(
            "independent_source_count cannot be negative"
        )

    if assessment.contradiction_count < 0:
        raise ValueError(
            "contradiction_count cannot be negative"
        )

    if assessment.negative_finding_count < 0:
        raise ValueError(
            "negative_finding_count cannot be negative"
        )

    if assessment.truth_established:
        raise ValueError(
            "Confidence engine cannot establish truth"
        )

    if assessment.fact_established:
        raise ValueError(
            "Confidence engine cannot establish facts"
        )

    if assessment.identity_established:
        raise ValueError(
            "Confidence engine cannot establish identity"
        )

    if assessment.guilt_established:
        raise ValueError(
            "Confidence engine cannot establish guilt"
        )

    if assessment.non_existence_established:
        raise ValueError(
            "Confidence engine cannot establish non-existence"
        )

    if not assessment.human_review_required:
        raise ValueError(
            "Human review is required for confidence conclusions"
        )

    if (
        assessment.evidence_gap_severity
        == EvidenceGapSeverity.CRITICAL
        and assessment.level
        in {
            ConfidenceLevel.HIGH,
            ConfidenceLevel.CONFIRMED,
        }
    ):
        raise ValueError(
            "Critical evidence gap blocks HIGH/CONFIRMED confidence"
        )

    if (
        assessment.contradiction_level
        == ContradictionLevel.CRITICAL
        and assessment.level
        == ConfidenceLevel.CONFIRMED
    ):
        raise ValueError(
            "Critical contradiction blocks CONFIRMED confidence"
        )

    return True


# ======================================================================
# EVIDENCE AGGREGATION
# ======================================================================

def aggregate_evidence_strength(
    evidence: List[ConfidenceEvidence],
) -> EvidenceStrength:

    if not evidence:
        return EvidenceStrength.NONE

    supporting = [
        item for item in evidence
        if item.supports_claim
    ]

    if not supporting:
        return EvidenceStrength.NONE

    strength_values = {
        EvidenceStrength.NONE: 0,
        EvidenceStrength.WEAK: 1,
        EvidenceStrength.MODERATE: 2,
        EvidenceStrength.STRONG: 3,
        EvidenceStrength.VERY_STRONG: 4,
    }

    strongest = max(
        (
            strength_values[item.evidence_strength]
            for item in supporting
        ),
        default=0,
    )

    if strongest >= 4:
        return EvidenceStrength.VERY_STRONG

    if strongest >= 3:
        return EvidenceStrength.STRONG

    if strongest >= 2:
        return EvidenceStrength.MODERATE

    if strongest >= 1:
        return EvidenceStrength.WEAK

    return EvidenceStrength.NONE


def calculate_independence(
    evidence: List[ConfidenceEvidence],
) -> IndependenceLevel:

    supporting = [
        item for item in evidence
        if item.supports_claim
    ]

    independent_sources = {
        item.source_id
        for item in supporting
        if item.independent and item.source_id
    }

    if len(independent_sources) >= 3:
        return IndependenceLevel.MULTIPLE_INDEPENDENT

    if len(independent_sources) >= 2:
        return IndependenceLevel.INDEPENDENT

    if len(supporting) >= 2:
        return IndependenceLevel.PARTIAL

    if supporting:
        return IndependenceLevel.UNKNOWN

    return IndependenceLevel.NONE


def calculate_contradiction_level(
    contradiction_count: int,
    material: bool = False,
    critical: bool = False,
) -> ContradictionLevel:

    if critical:
        return ContradictionLevel.CRITICAL

    if material:
        return ContradictionLevel.MATERIAL

    if contradiction_count > 0:
        return ContradictionLevel.MINOR

    return ContradictionLevel.NONE


def determine_gap_severity(
    evidence_gaps: List[str],
    critical_gap: bool = False,
) -> EvidenceGapSeverity:

    if critical_gap:
        return EvidenceGapSeverity.CRITICAL

    count = len(evidence_gaps)

    if count >= 4:
        return EvidenceGapSeverity.HIGH

    if count >= 2:
        return EvidenceGapSeverity.MODERATE

    if count == 1:
        return EvidenceGapSeverity.LOW

    return EvidenceGapSeverity.NONE


# ======================================================================
# SCORE ENGINE
# ======================================================================

def calculate_confidence_score(
    evidence: List[ConfidenceEvidence],
    *,
    contradiction_count: int = 0,
    material_contradiction: bool = False,
    critical_contradiction: bool = False,
    evidence_gaps: Optional[List[str]] = None,
    critical_gap: bool = False,
    negative_finding_count: int = 0,
) -> float:

    evidence_gaps = list(evidence_gaps or [])

    supporting = [
        item for item in evidence
        if item.supports_claim
    ]

    if not supporting:
        return 0.0

    strength_values = {
        EvidenceStrength.NONE: 0.0,
        EvidenceStrength.WEAK: 0.20,
        EvidenceStrength.MODERATE: 0.45,
        EvidenceStrength.STRONG: 0.70,
        EvidenceStrength.VERY_STRONG: 0.90,
    }

    quality_values = [
        strength_values[item.evidence_strength]
        * item.source_quality
        for item in supporting
    ]

    quality_score = (
        sum(quality_values) / len(quality_values)
        if quality_values
        else 0.0
    )

    independent_sources = {
        item.source_id
        for item in supporting
        if item.independent and item.source_id
    }

    if len(independent_sources) >= 3:
        independence_bonus = 0.15
    elif len(independent_sources) >= 2:
        independence_bonus = 0.10
    elif len(supporting) >= 2:
        independence_bonus = 0.04
    else:
        independence_bonus = 0.0

    score = quality_score + independence_bonus

    if critical_contradiction:
        score -= 0.45
    elif material_contradiction:
        score -= 0.25
    elif contradiction_count > 0:
        score -= min(0.10 * contradiction_count, 0.20)

    if critical_gap:
        score -= 0.35
    elif len(evidence_gaps) >= 4:
        score -= 0.20
    elif len(evidence_gaps) >= 2:
        score -= 0.12
    elif len(evidence_gaps) == 1:
        score -= 0.05

    # Negative findings are research limitations, not proof.
    if negative_finding_count > 0:
        score -= min(
            0.02 * negative_finding_count,
            0.10,
        )

    return clamp(score)


# ======================================================================
# LEVEL ENGINE
# ======================================================================

def determine_confidence_level(
    score: float,
    *,
    evidence: List[ConfidenceEvidence],
    independence: IndependenceLevel,
    contradiction_level: ContradictionLevel,
    gap_severity: EvidenceGapSeverity,
) -> ConfidenceLevel:

    supporting_count = sum(
        1
        for item in evidence
        if item.supports_claim
    )

    if supporting_count == 0:
        return ConfidenceLevel.NOT_ASSESSED

    if contradiction_level == ContradictionLevel.CRITICAL:
        return ConfidenceLevel.LOW

    if gap_severity == EvidenceGapSeverity.CRITICAL:
        if score >= 0.45:
            return ConfidenceLevel.MODERATE
        return ConfidenceLevel.LOW

    if score < 0.20:
        return ConfidenceLevel.VERY_LOW

    if score < 0.40:
        return ConfidenceLevel.LOW

    if score < 0.65:
        return ConfidenceLevel.MODERATE

    if score < 0.82:
        return ConfidenceLevel.HIGH

    if (
        score >= 0.82
        and supporting_count >= 2
        and independence
        == IndependenceLevel.MULTIPLE_INDEPENDENT
        and contradiction_level
        == ContradictionLevel.NONE
        and gap_severity
        in {
            EvidenceGapSeverity.NONE,
            EvidenceGapSeverity.LOW,
        }
    ):
        return ConfidenceLevel.CONFIRMED

    return ConfidenceLevel.HIGH


# ======================================================================
# MAIN ASSESSMENT
# ======================================================================

def assess_confidence(
    claim_id: str,
    evidence: List[ConfidenceEvidence],
    *,
    contradiction_count: int = 0,
    material_contradiction: bool = False,
    critical_contradiction: bool = False,
    evidence_gaps: Optional[List[str]] = None,
    critical_gap: bool = False,
    negative_finding_count: int = 0,
    negative_finding_is_nonexistence: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
) -> ConfidenceAssessment:

    evidence_gaps = list(evidence_gaps or [])

    for item in evidence:
        validate_confidence_evidence(item)

    independence = calculate_independence(evidence)

    contradiction_level = calculate_contradiction_level(
        contradiction_count,
        material=material_contradiction,
        critical=critical_contradiction,
    )

    gap_severity = determine_gap_severity(
        evidence_gaps,
        critical_gap=critical_gap,
    )

    score = calculate_confidence_score(
        evidence,
        contradiction_count=contradiction_count,
        material_contradiction=material_contradiction,
        critical_contradiction=critical_contradiction,
        evidence_gaps=evidence_gaps,
        critical_gap=critical_gap,
        negative_finding_count=negative_finding_count,
    )

    level = determine_confidence_level(
        score,
        evidence=evidence,
        independence=independence,
        contradiction_level=contradiction_level,
        gap_severity=gap_severity,
    )

    supporting_count = sum(
        1
        for item in evidence
        if item.supports_claim
    )

    independent_count = len({
        item.source_id
        for item in evidence
        if item.supports_claim
        and item.independent
        and item.source_id
    })

    rationale = []

    if supporting_count:
        rationale.append(
            f"{supporting_count} supporting evidence item(s) evaluated."
        )

    if independent_count:
        rationale.append(
            f"{independent_count} independent source(s) identified."
        )

    if contradiction_count:
        rationale.append(
            f"{contradiction_count} contradiction(s) remain in the record."
        )

    if evidence_gaps:
        rationale.append(
            f"{len(evidence_gaps)} evidence gap(s) remain unresolved."
        )

    if negative_finding_count:
        rationale.append(
            "Negative findings were treated as research limitations, "
            "not proof of non-existence."
        )

    rationale.append(
        "Confidence is an assessment of the investigative record, "
        "not a determination of truth."
    )

    assessment = ConfidenceAssessment(
        claim_id=claim_id,
        score=round(score, 6),
        level=level,
        evidence_count=len(evidence),
        supporting_evidence_count=supporting_count,
        independent_source_count=independent_count,
        evidence_strength=aggregate_evidence_strength(evidence),
        independence=independence,
        contradiction_level=contradiction_level,
        contradiction_count=contradiction_count,
        evidence_gap_severity=gap_severity,
        evidence_gaps=evidence_gaps,
        negative_finding_count=negative_finding_count,
        negative_finding_is_nonexistence=False,
        rationale=rationale,
        metadata=dict(metadata or {}),
    )

    if negative_finding_is_nonexistence:
        assessment.negative_finding_is_nonexistence = False
        assessment.rationale.append(
            "Input flag asserting non-existence from negative findings "
            "was rejected by the safety boundary."
        )

    validate_confidence_assessment(assessment)

    return assessment


# ======================================================================
# SERIALIZATION
# ======================================================================

def serialize(value: Any) -> Any:

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, list):
        return [serialize(item) for item in value]

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


def serialize_assessment(
    assessment: ConfidenceAssessment,
) -> Dict[str, Any]:
    return serialize(assessment)


# ======================================================================
# CONTRACT TEST
# ======================================================================

def contract_test() -> None:

    print("=" * 70)
    print("DOA CONFIDENCE ENGINE CONTRACT TEST")
    print("=" * 70)

    # --------------------------------------------------------------
    # 1
    # --------------------------------------------------------------
    print("\n[1] ENUMS AND MODULE CONTRACT")

    assert ConfidenceLevel.NOT_ASSESSED.value == "NOT_ASSESSED"
    assert EvidenceStrength.VERY_STRONG.value == "VERY_STRONG"
    assert (
        IndependenceLevel.MULTIPLE_INDEPENDENT.value
        == "MULTIPLE_INDEPENDENT"
    )
    assert ContradictionLevel.CRITICAL.value == "CRITICAL"
    assert EvidenceGapSeverity.CRITICAL.value == "CRITICAL"

    print("  Confidence enum             : PASS")
    print("  Evidence strength enum      : PASS")
    print("  Independence enum           : PASS")
    print("  Contradiction enum          : PASS")
    print("  Evidence gap enum           : PASS")
    print("  RESULT                      : PASS")

    # --------------------------------------------------------------
    # 2
    # --------------------------------------------------------------
    print("\n[2] NO-EVIDENCE TEST")

    empty = assess_confidence(
        "CLAIM_EMPTY",
        [],
    )

    assert empty.level == ConfidenceLevel.NOT_ASSESSED
    assert empty.score == 0.0
    assert empty.truth_established is False
    assert empty.fact_established is False

    print("  Level                       : NOT_ASSESSED")
    print("  Score                       : 0.0")
    print("  Truth established           : FALSE")
    print("  Fact established            : FALSE")
    print("  RESULT                      : PASS")

    # --------------------------------------------------------------
    # 3
    # --------------------------------------------------------------
    print("\n[3] SINGLE WEAK SOURCE")

    weak = ConfidenceEvidence(
        evidence_id="E_WEAK_001",
        source_id="SRC_WEAK_001",
        evidence_strength=EvidenceStrength.WEAK,
        source_quality=0.40,
        independent=False,
        supports_claim=True,
    )

    weak_result = assess_confidence(
        "CLAIM_WEAK",
        [weak],
    )

    assert weak_result.level in {
        ConfidenceLevel.VERY_LOW,
        ConfidenceLevel.LOW,
    }
    assert weak_result.independent_source_count == 0
    assert weak_result.identity_established is False
    assert weak_result.guilt_established is False

    print("  Level                       :", weak_result.level.value)
    print("  Independent sources         : 0")
    print("  Identity established        : FALSE")
    print("  Guilt established           : FALSE")
    print("  RESULT                      : PASS")

    # --------------------------------------------------------------
    # 4
    # --------------------------------------------------------------
    print("\n[4] MULTIPLE INDEPENDENT SOURCES")

    e1 = ConfidenceEvidence(
        evidence_id="E_STRONG_001",
        source_id="SRC_GOV_001",
        evidence_strength=EvidenceStrength.STRONG,
        source_quality=0.95,
        independent=True,
        supports_claim=True,
    )

    e2 = ConfidenceEvidence(
        evidence_id="E_STRONG_002",
        source_id="SRC_NEWS_001",
        evidence_strength=EvidenceStrength.STRONG,
        source_quality=0.85,
        independent=True,
        supports_claim=True,
    )

    e3 = ConfidenceEvidence(
        evidence_id="E_STRONG_003",
        source_id="SRC_CORP_001",
        evidence_strength=EvidenceStrength.VERY_STRONG,
        source_quality=0.95,
        independent=True,
        supports_claim=True,
    )

    corroborated = assess_confidence(
        "CLAIM_CORROBORATED",
        [e1, e2, e3],
    )

    assert corroborated.independent_source_count == 3
    assert (
        corroborated.independence
        == IndependenceLevel.MULTIPLE_INDEPENDENT
    )
    assert corroborated.level == ConfidenceLevel.CONFIRMED
    assert corroborated.fact_established is False
    assert corroborated.truth_established is False

    print("  Independent sources         : 3")
    print("  Independence                : MULTIPLE_INDEPENDENT")
    print("  Level                       : CONFIRMED")
    print("  Truth established           : FALSE")
    print("  Fact established            : FALSE")
    print("  RESULT                      : PASS")

    # --------------------------------------------------------------
    # 5
    # --------------------------------------------------------------
    print("\n[5] DUPLICATED SOURCE TEST")

    d1 = ConfidenceEvidence(
        evidence_id="E_DUP_001",
        source_id="SRC_SAME_001",
        evidence_strength=EvidenceStrength.STRONG,
        source_quality=0.90,
        independent=False,
        supports_claim=True,
    )

    d2 = ConfidenceEvidence(
        evidence_id="E_DUP_002",
        source_id="SRC_SAME_001",
        evidence_strength=EvidenceStrength.STRONG,
        source_quality=0.90,
        independent=False,
        supports_claim=True,
    )

    duplicated = assess_confidence(
        "CLAIM_DUPLICATED",
        [d1, d2],
    )

    assert duplicated.independent_source_count == 0
    assert (
        duplicated.independence
        == IndependenceLevel.PARTIAL
    )
    assert duplicated.level != ConfidenceLevel.CONFIRMED

    print("  Same source count            : 2")
    print("  Independent sources          : 0")
    print("  Confirmation blocked         : PASS")
    print("  RESULT                      : PASS")

    # --------------------------------------------------------------
    # 6
    # --------------------------------------------------------------
    print("\n[6] MATERIAL CONTRADICTION")

    material = assess_confidence(
        "CLAIM_MATERIAL_CONTRADICTION",
        [e1, e2, e3],
        contradiction_count=1,
        material_contradiction=True,
    )

    assert (
        material.contradiction_level
        == ContradictionLevel.MATERIAL
    )
    assert material.level != ConfidenceLevel.CONFIRMED
    assert material.fact_established is False

    print("  Contradiction level          : MATERIAL")
    print("  Confirmation blocked         : PASS")
    print("  Fact established             : FALSE")
    print("  RESULT                      : PASS")

    # --------------------------------------------------------------
    # 7
    # --------------------------------------------------------------
    print("\n[7] CRITICAL CONTRADICTION")

    critical = assess_confidence(
        "CLAIM_CRITICAL_CONTRADICTION",
        [e1, e2, e3],
        contradiction_count=1,
        critical_contradiction=True,
    )

    assert (
        critical.contradiction_level
        == ContradictionLevel.CRITICAL
    )
    assert critical.level == ConfidenceLevel.LOW
    assert critical.level != ConfidenceLevel.CONFIRMED

    print("  Contradiction level          : CRITICAL")
    print("  Level                       :", critical.level.value)
    print("  Confirmation blocked         : PASS")
    print("  RESULT                      : PASS")

    # --------------------------------------------------------------
    # 8
    # --------------------------------------------------------------
    print("\n[8] CRITICAL EVIDENCE GAP")

    gap = assess_confidence(
        "CLAIM_CRITICAL_GAP",
        [e1, e2, e3],
        evidence_gaps=[
            "Original underlying document unavailable",
        ],
        critical_gap=True,
    )

    assert (
        gap.evidence_gap_severity
        == EvidenceGapSeverity.CRITICAL
    )
    assert gap.level != ConfidenceLevel.CONFIRMED
    assert gap.fact_established is False

    print("  Gap severity                : CRITICAL")
    print("  Confirmation blocked         : PASS")
    print("  Fact established             : FALSE")
    print("  RESULT                      : PASS")

    # --------------------------------------------------------------
    # 9
    # --------------------------------------------------------------
    print("\n[9] NEGATIVE FINDING GUARD")

    negative = assess_confidence(
        "CLAIM_NEGATIVE",
        [e1, e2],
        negative_finding_count=3,
        negative_finding_is_nonexistence=True,
    )

    assert negative.negative_finding_count == 3
    assert negative.negative_finding_is_nonexistence is False
    assert negative.non_existence_established is False
    assert negative.fact_established is False

    print("  Negative findings counted    : 3")
    print("  Non-existence established    : FALSE")
    print("  Negative finding as proof    : BLOCKED")
    print("  RESULT                      : PASS")

    # --------------------------------------------------------------
    # 10
    # --------------------------------------------------------------
    print("\n[10] NON-SUPPORTING EVIDENCE")

    counter = ConfidenceEvidence(
        evidence_id="E_COUNTER_001",
        source_id="SRC_COUNTER_001",
        evidence_strength=EvidenceStrength.VERY_STRONG,
        source_quality=0.95,
        independent=True,
        supports_claim=False,
    )

    mixed = assess_confidence(
        "CLAIM_MIXED",
        [e1, counter],
    )

    assert mixed.supporting_evidence_count == 1
    assert mixed.independent_source_count == 1
    assert mixed.fact_established is False

    print("  Supporting evidence          : 1")
    print("  Counter-evidence preserved   : PASS")
    print("  Fact established             : FALSE")
    print("  RESULT                      : PASS")

    # --------------------------------------------------------------
    # 11
    # --------------------------------------------------------------
    print("\n[11] IDENTITY / GUILT SEPARATION")

    assert corroborated.identity_established is False
    assert corroborated.guilt_established is False
    assert corroborated.fact_established is False

    print("  Identity established         : FALSE")
    print("  Guilt established            : FALSE")
    print("  Fact established             : FALSE")
    print("  RESULT                      : PASS")

    # --------------------------------------------------------------
    # 12
    # --------------------------------------------------------------
    print("\n[12] SCORE RANGE")

    all_results = [
        empty,
        weak_result,
        corroborated,
        duplicated,
        material,
        critical,
        gap,
        negative,
        mixed,
    ]

    for item in all_results:
        assert item.score is not None
        assert 0.0 <= item.score <= 1.0

    print("  All scores within [0,1]      : PASS")
    print("  RESULT                      : PASS")

    # --------------------------------------------------------------
    # 13
    # --------------------------------------------------------------
    print("\n[13] SERIALIZATION")

    serialized = serialize_assessment(corroborated)

    assert isinstance(serialized, dict)
    assert (
        serialized["assessment_id"]
        == corroborated.assessment_id
    )
    assert serialized["claim_id"] == "CLAIM_CORROBORATED"
    assert serialized["level"] == "CONFIRMED"
    assert serialized["truth_established"] is False
    assert serialized["guilt_established"] is False

    encoded = json.dumps(
        serialized,
        ensure_ascii=False,
    )

    assert isinstance(encoded, str)
    assert len(encoded) > 0

    print("  Assessment ID preserved      : PASS")
    print("  Claim ID preserved           : PASS")
    print("  Confidence level serialized  : PASS")
    print("  Safety state serialized      : PASS")
    print("  JSON serialization           : PASS")
    print("  RESULT                       : PASS")

    # --------------------------------------------------------------
    # 14
    # --------------------------------------------------------------
    print("\n[14] UNSAFE STATE VALIDATION")

    unsafe = assess_confidence(
        "CLAIM_UNSAFE",
        [e1],
    )

    unsafe.fact_established = True

    try:
        validate_confidence_assessment(unsafe)
        raise AssertionError(
            "Unsafe fact-established state was accepted"
        )
    except ValueError:
        unsafe.fact_established = False

    unsafe.guilt_established = True

    try:
        validate_confidence_assessment(unsafe)
        raise AssertionError(
            "Unsafe guilt-established state was accepted"
        )
    except ValueError:
        unsafe.guilt_established = False

    unsafe.identity_established = True

    try:
        validate_confidence_assessment(unsafe)
        raise AssertionError(
            "Unsafe identity-established state was accepted"
        )
    except ValueError:
        unsafe.identity_established = False

    print("  Fact establishment blocked   : PASS")
    print("  Guilt establishment blocked  : PASS")
    print("  Identity establishment block : PASS")
    print("  RESULT                       : PASS")

    # --------------------------------------------------------------
    # 15
    # --------------------------------------------------------------
    print("\n[15] CRITICAL GAP VALIDATION")

    unsafe_gap = assess_confidence(
        "CLAIM_UNSAFE_GAP",
        [e1, e2, e3],
        evidence_gaps=["Original record missing"],
        critical_gap=True,
    )

    assert unsafe_gap.level != ConfidenceLevel.CONFIRMED

    print("  Critical gap blocks confirm  : PASS")
    print("  RESULT                       : PASS")

    # --------------------------------------------------------------
    # 16
    # --------------------------------------------------------------
    print("\n[16] FINAL SAFETY INVARIANTS")

    all_results.append(unsafe_gap)

    assert all(
        item.truth_established is False
        for item in all_results
    )

    assert all(
        item.fact_established is False
        for item in all_results
    )

    assert all(
        item.identity_established is False
        for item in all_results
    )

    assert all(
        item.guilt_established is False
        for item in all_results
    )

    assert all(
        item.non_existence_established is False
        for item in all_results
    )

    assert all(
        item.human_review_required is True
        for item in all_results
    )

    print("  Confidence != truth           : TRUE")
    print("  Confidence != identity        : TRUE")
    print("  Confidence != guilt           : TRUE")
    print("  Confidence != non-existence   : TRUE")
    print("  Contradictions preserved      : TRUE")
    print("  Evidence gaps preserved       : TRUE")
    print("  Human review required         : TRUE")
    print("  RESULT                       : PASS")

    # --------------------------------------------------------------
    # 17
    # --------------------------------------------------------------
    print("\n[17] FINAL VALIDATION")

    for item in all_results:
        assert validate_confidence_assessment(item)

    print("  Assessment validation         : PASS")

    print("\n" + "=" * 70)
    print("CONFIDENCE ENGINE : PASS")
    print("=" * 70)
    print("MODULE IMPORT                  : PASS")
    print("NO-EVIDENCE HANDLING           : PASS")
    print("WEAK EVIDENCE                  : PASS")
    print("INDEPENDENT CORROBORATION      : PASS")
    print("DUPLICATE SOURCE GUARD         : PASS")
    print("MATERIAL CONTRADICTION         : PASS")
    print("CRITICAL CONTRADICTION         : PASS")
    print("CRITICAL EVIDENCE GAP          : PASS")
    print("NEGATIVE FINDING GUARD         : PASS")
    print("COUNTER-EVIDENCE               : PASS")
    print("IDENTITY SEPARATION            : PASS")
    print("GUILT SEPARATION               : PASS")
    print("SCORE RANGE                    : PASS")
    print("SERIALIZATION                  : PASS")
    print("UNSAFE STATE VALIDATION        : PASS")
    print("CRITICAL GAP VALIDATION        : PASS")
    print("SAFETY INVARIANTS              : PASS")
    print("VALIDATION                     : PASS")
    print("TRUTH ESTABLISHMENT            : FALSE")
    print("FACT ESTABLISHMENT             : FALSE")
    print("IDENTITY ESTABLISHMENT         : FALSE")
    print("GUILT ESTABLISHMENT            : FALSE")
    print("REAL WEB SEARCH                : NOT STARTED")
    print("=" * 70)


if __name__ == "__main__":
    contract_test()
