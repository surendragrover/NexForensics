"""
Deep OSINT Agent (DOA)
Evidence Synthesis / Investigation Decision Layer

Purpose
-------
Aggregate outputs from the evidence engines into a controlled
investigative assessment.

This layer does NOT establish:
    - truth
    - facts
    - identity
    - guilt
    - liability
    - non-existence

It determines only the current state of the investigative record.

Core principle
--------------
EVIDENCE SYNTHESIS != TRUTH
EVIDENCE SYNTHESIS != GUILT
EVIDENCE SYNTHESIS != IDENTITY

The layer preserves:
    - corroboration
    - contradictions
    - evidence gaps
    - negative findings
    - confidence assessments
    - human-review requirements
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

class InvestigationState(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    DEVELOPING = "DEVELOPING"
    CORROBORATED = "CORROBORATED"
    CONTESTED = "CONTESTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class EvidenceBalance(str, Enum):
    NONE = "NONE"
    WEAK = "WEAK"
    MIXED = "MIXED"
    SUPPORTING = "SUPPORTING"
    STRONG_SUPPORT = "STRONG_SUPPORT"
    CONTESTED = "CONTESTED"


class ReviewPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ======================================================================
# HELPERS
# ======================================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str = "SYN") -> str:
    return f"{prefix}_{utc_now().strftime('%Y%m%d%H%M%S%f')}"


# ======================================================================
# INPUT RECORDS
# ======================================================================

@dataclass
class SynthesisClaim:
    claim_id: str
    confidence_score: Optional[float] = None
    confidence_level: str = "NOT_ASSESSED"

    supporting_source_count: int = 0
    independent_source_count: int = 0

    contradiction_count: int = 0
    critical_contradiction: bool = False

    evidence_gap_count: int = 0
    critical_evidence_gap: bool = False

    negative_finding_count: int = 0

    truth_established: bool = False
    identity_established: bool = False
    guilt_established: bool = False
    non_existence_established: bool = False

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SynthesisInput:
    investigation_id: str

    claims: List[SynthesisClaim] = field(default_factory=list)

    unresolved_questions: List[str] = field(default_factory=list)
    evidence_gaps: List[str] = field(default_factory=list)

    contradiction_count: int = 0
    critical_contradiction_count: int = 0

    negative_finding_count: int = 0
    access_limitation_count: int = 0

    identity_confirmed: bool = False

    metadata: Dict[str, Any] = field(default_factory=dict)


# ======================================================================
# OUTPUT
# ======================================================================

@dataclass
class EvidenceSynthesis:
    synthesis_id: str = field(
        default_factory=lambda: new_id("SYN")
    )

    investigation_id: Optional[str] = None

    state: InvestigationState = (
        InvestigationState.NOT_ASSESSED
    )

    evidence_balance: EvidenceBalance = (
        EvidenceBalance.NONE
    )

    review_priority: ReviewPriority = (
        ReviewPriority.MEDIUM
    )

    claim_count: int = 0
    assessed_claim_count: int = 0
    corroborated_claim_count: int = 0
    contested_claim_count: int = 0

    total_supporting_sources: int = 0
    total_independent_sources: int = 0

    contradiction_count: int = 0
    critical_contradiction_count: int = 0

    evidence_gap_count: int = 0
    critical_evidence_gap_count: int = 0

    negative_finding_count: int = 0
    access_limitation_count: int = 0

    unresolved_questions: List[str] = field(default_factory=list)
    evidence_gaps: List[str] = field(default_factory=list)
    contradictions: List[str] = field(default_factory=list)
    next_investigative_steps: List[str] = field(default_factory=list)

    identity_confirmed: bool = False

    # Safety invariants
    truth_established: bool = False
    fact_established: bool = False
    identity_established: bool = False
    guilt_established: bool = False
    non_existence_established: bool = False
    automatic_conclusion: bool = False
    human_review_required: bool = True

    rationale: List[str] = field(default_factory=list)

    generated_at: datetime = field(
        default_factory=utc_now
    )

    metadata: Dict[str, Any] = field(default_factory=dict)


# ======================================================================
# VALIDATION
# ======================================================================

def validate_claim(claim: SynthesisClaim) -> bool:

    if not claim.claim_id:
        raise ValueError("claim_id is required")

    if claim.confidence_score is not None:
        if not 0.0 <= claim.confidence_score <= 1.0:
            raise ValueError(
                "confidence_score must be between 0 and 1"
            )

    if claim.supporting_source_count < 0:
        raise ValueError(
            "supporting_source_count cannot be negative"
        )

    if claim.independent_source_count < 0:
        raise ValueError(
            "independent_source_count cannot be negative"
        )

    if claim.contradiction_count < 0:
        raise ValueError(
            "contradiction_count cannot be negative"
        )

    if claim.evidence_gap_count < 0:
        raise ValueError(
            "evidence_gap_count cannot be negative"
        )

    if claim.truth_established:
        raise ValueError(
            "Synthesis cannot receive truth_established=True"
        )

    if claim.identity_established:
        raise ValueError(
            "Synthesis cannot receive identity_established=True"
        )

    if claim.guilt_established:
        raise ValueError(
            "Synthesis cannot receive guilt_established=True"
        )

    if claim.non_existence_established:
        raise ValueError(
            "Synthesis cannot receive non_existence_established=True"
        )

    return True


def validate_synthesis(
    synthesis: EvidenceSynthesis,
) -> bool:

    if not synthesis.investigation_id:
        raise ValueError(
            "investigation_id is required"
        )

    if synthesis.claim_count < 0:
        raise ValueError("claim_count cannot be negative")

    if synthesis.assessed_claim_count < 0:
        raise ValueError(
            "assessed_claim_count cannot be negative"
        )

    if synthesis.corroborated_claim_count < 0:
        raise ValueError(
            "corroborated_claim_count cannot be negative"
        )

    if synthesis.contested_claim_count < 0:
        raise ValueError(
            "contested_claim_count cannot be negative"
        )

    if synthesis.contradiction_count < 0:
        raise ValueError(
            "contradiction_count cannot be negative"
        )

    if synthesis.critical_contradiction_count < 0:
        raise ValueError(
            "critical_contradiction_count cannot be negative"
        )

    if synthesis.evidence_gap_count < 0:
        raise ValueError(
            "evidence_gap_count cannot be negative"
        )

    if synthesis.critical_evidence_gap_count < 0:
        raise ValueError(
            "critical_evidence_gap_count cannot be negative"
        )

    if synthesis.truth_established:
        raise ValueError(
            "Synthesis cannot establish truth"
        )

    if synthesis.fact_established:
        raise ValueError(
            "Synthesis cannot establish facts"
        )

    if synthesis.identity_established:
        raise ValueError(
            "Synthesis cannot establish identity"
        )

    if synthesis.guilt_established:
        raise ValueError(
            "Synthesis cannot establish guilt"
        )

    if synthesis.non_existence_established:
        raise ValueError(
            "Synthesis cannot establish non-existence"
        )

    if synthesis.automatic_conclusion:
        raise ValueError(
            "Automatic investigative conclusion is forbidden"
        )

    if not synthesis.human_review_required:
        raise ValueError(
            "Human review must remain required"
        )

    if (
        synthesis.critical_contradiction_count > 0
        and synthesis.state
        == InvestigationState.CORROBORATED
    ):
        raise ValueError(
            "Critical contradiction blocks CORROBORATED state"
        )

    if (
        synthesis.critical_evidence_gap_count > 0
        and synthesis.state
        == InvestigationState.CORROBORATED
    ):
        raise ValueError(
            "Critical evidence gap blocks CORROBORATED state"
        )

    return True


# ======================================================================
# CLAIM CLASSIFICATION
# ======================================================================

def _claim_is_assessed(
    claim: SynthesisClaim,
) -> bool:

    return (
        claim.confidence_score is not None
        and claim.confidence_level != "NOT_ASSESSED"
    )


def _claim_is_corroborated(
    claim: SynthesisClaim,
) -> bool:

    return (
        claim.confidence_score is not None
        and claim.confidence_score >= 0.65
        and claim.independent_source_count >= 2
        and claim.contradiction_count == 0
        and not claim.critical_evidence_gap
        and not claim.critical_contradiction
    )


def _claim_is_contested(
    claim: SynthesisClaim,
) -> bool:

    return (
        claim.contradiction_count > 0
        or claim.critical_contradiction
    )


# ======================================================================
# BALANCE ENGINE
# ======================================================================

def determine_evidence_balance(
    claims: List[SynthesisClaim],
) -> EvidenceBalance:

    if not claims:
        return EvidenceBalance.NONE

    corroborated = sum(
        1 for claim in claims
        if _claim_is_corroborated(claim)
    )

    contested = sum(
        1 for claim in claims
        if _claim_is_contested(claim)
    )

    assessed = sum(
        1 for claim in claims
        if _claim_is_assessed(claim)
    )

    if contested > 0 and contested >= corroborated:
        return EvidenceBalance.CONTESTED

    if corroborated >= 2:
        return EvidenceBalance.STRONG_SUPPORT

    if corroborated == 1:
        return EvidenceBalance.SUPPORTING

    if assessed > 0:
        return EvidenceBalance.MIXED

    return EvidenceBalance.WEAK


# ======================================================================
# STATE ENGINE
# ======================================================================

def determine_investigation_state(
    claims: List[SynthesisClaim],
    *,
    unresolved_questions: List[str],
    critical_contradiction_count: int,
    critical_evidence_gap_count: int,
) -> InvestigationState:

    if not claims:
        return InvestigationState.NOT_ASSESSED

    if (
        critical_contradiction_count > 0
        or critical_evidence_gap_count > 0
    ):
        return InvestigationState.REVIEW_REQUIRED

    if any(
        _claim_is_contested(claim)
        for claim in claims
    ):
        return InvestigationState.CONTESTED

    corroborated = sum(
        1
        for claim in claims
        if _claim_is_corroborated(claim)
    )

    assessed = sum(
        1
        for claim in claims
        if _claim_is_assessed(claim)
    )

    if corroborated >= 2:
        return InvestigationState.CORROBORATED

    if assessed > 0:
        return InvestigationState.DEVELOPING

    if unresolved_questions:
        return InvestigationState.INSUFFICIENT_EVIDENCE

    return InvestigationState.NOT_ASSESSED


# ======================================================================
# REVIEW PRIORITY
# ======================================================================

def determine_review_priority(
    *,
    critical_contradiction_count: int,
    critical_evidence_gap_count: int,
    access_limitation_count: int,
    unresolved_question_count: int,
) -> ReviewPriority:

    if (
        critical_contradiction_count > 0
        or critical_evidence_gap_count > 0
    ):
        return ReviewPriority.CRITICAL

    if (
        access_limitation_count > 0
        or unresolved_question_count >= 3
    ):
        return ReviewPriority.HIGH

    if unresolved_question_count > 0:
        return ReviewPriority.MEDIUM

    return ReviewPriority.LOW


# ======================================================================
# NEXT INVESTIGATIVE STEPS
# ======================================================================

def build_next_steps(
    claims: List[SynthesisClaim],
    unresolved_questions: List[str],
    evidence_gaps: List[str],
    critical_contradictions: int,
    access_limitations: int,
) -> List[str]:

    steps: List[str] = []

    if critical_contradictions:
        steps.append(
            "Resolve critical contradictions through independent "
            "primary-source review."
        )

    if access_limitations:
        steps.append(
            "Seek lawful alternative sources for inaccessible records."
        )

    if evidence_gaps:
        steps.append(
            "Close documented evidence gaps before increasing "
            "investigative confidence."
        )

    if unresolved_questions:
        steps.append(
            "Prioritize unresolved investigative questions."
        )

    if any(
        claim.independent_source_count < 2
        for claim in claims
        if _claim_is_assessed(claim)
    ):
        steps.append(
            "Seek independent corroboration rather than duplicate "
            "copies of existing reporting."
        )

    if not steps:
        steps.append(
            "Conduct human review of the current evidence record."
        )

    return steps


# ======================================================================
# MAIN SYNTHESIS
# ======================================================================

def synthesize_investigation(
    data: SynthesisInput,
) -> EvidenceSynthesis:

    for claim in data.claims:
        validate_claim(claim)

    critical_gap_count = sum(
        1
        for claim in data.claims
        if claim.critical_evidence_gap
    )

    critical_gap_count += (
        1 if any(
            "critical" in gap.lower()
            for gap in data.evidence_gaps
        ) else 0
    )

    critical_contradiction_count = (
        data.critical_contradiction_count
        + sum(
            1
            for claim in data.claims
            if claim.critical_contradiction
        )
    )

    assessed_claims = [
        claim
        for claim in data.claims
        if _claim_is_assessed(claim)
    ]

    corroborated_claims = [
        claim
        for claim in data.claims
        if _claim_is_corroborated(claim)
    ]

    contested_claims = [
        claim
        for claim in data.claims
        if _claim_is_contested(claim)
    ]

    state = determine_investigation_state(
        data.claims,
        unresolved_questions=data.unresolved_questions,
        critical_contradiction_count=critical_contradiction_count,
        critical_evidence_gap_count=critical_gap_count,
    )

    balance = determine_evidence_balance(data.claims)

    priority = determine_review_priority(
        critical_contradiction_count=critical_contradiction_count,
        critical_evidence_gap_count=critical_gap_count,
        access_limitation_count=data.access_limitation_count,
        unresolved_question_count=len(
            data.unresolved_questions
        ),
    )

    rationale: List[str] = []

    if assessed_claims:
        rationale.append(
            f"{len(assessed_claims)} claim(s) have an assessed "
            "investigative confidence."
        )

    if corroborated_claims:
        rationale.append(
            f"{len(corroborated_claims)} claim(s) meet the "
            "corroboration threshold."
        )

    if contested_claims:
        rationale.append(
            f"{len(contested_claims)} claim(s) contain "
            "contradictory evidence."
        )

    if critical_gap_count:
        rationale.append(
            "Critical evidence gaps remain and block a "
            "corroborated investigative state."
        )

    if data.negative_finding_count:
        rationale.append(
            "Negative findings are treated as search results "
            "and limitations, never as proof of non-existence."
        )

    rationale.append(
        "Synthesis describes the current evidence record and "
        "does not determine truth, identity, or guilt."
    )

    synthesis = EvidenceSynthesis(
        investigation_id=data.investigation_id,
        state=state,
        evidence_balance=balance,
        review_priority=priority,

        claim_count=len(data.claims),
        assessed_claim_count=len(assessed_claims),
        corroborated_claim_count=len(corroborated_claims),
        contested_claim_count=len(contested_claims),

        total_supporting_sources=sum(
            claim.supporting_source_count
            for claim in data.claims
        ),

        total_independent_sources=sum(
            claim.independent_source_count
            for claim in data.claims
        ),

        contradiction_count=(
            data.contradiction_count
            + sum(
                claim.contradiction_count
                for claim in data.claims
            )
        ),

        critical_contradiction_count=(
            critical_contradiction_count
        ),

        evidence_gap_count=(
            len(data.evidence_gaps)
            + sum(
                claim.evidence_gap_count
                for claim in data.claims
            )
        ),

        critical_evidence_gap_count=critical_gap_count,

        negative_finding_count=(
            data.negative_finding_count
            + sum(
                claim.negative_finding_count
                for claim in data.claims
            )
        ),

        access_limitation_count=data.access_limitation_count,

        unresolved_questions=list(
            data.unresolved_questions
        ),

        evidence_gaps=list(data.evidence_gaps),

        contradictions=[
            f"Claim {claim.claim_id}: "
            f"{claim.contradiction_count} contradiction(s)"
            for claim in data.claims
            if claim.contradiction_count > 0
        ],

        next_investigative_steps=build_next_steps(
            data.claims,
            data.unresolved_questions,
            data.evidence_gaps,
            critical_contradictions=critical_contradiction_count,
            access_limitations=data.access_limitation_count,
        ),

        identity_confirmed=data.identity_confirmed,

        # ----------------------------------------------------------
        # HARD SAFETY BOUNDARY
        # ----------------------------------------------------------
        truth_established=False,
        fact_established=False,
        identity_established=False,
        guilt_established=False,
        non_existence_established=False,
        automatic_conclusion=False,
        human_review_required=True,

        rationale=rationale,
        metadata=dict(data.metadata),
    )

    validate_synthesis(synthesis)

    return synthesis


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


def serialize_synthesis(
    synthesis: EvidenceSynthesis,
) -> Dict[str, Any]:

    return serialize(synthesis)


# ======================================================================
# CONTRACT TEST
# ======================================================================

def contract_test() -> None:

    print("=" * 70)
    print("DOA EVIDENCE SYNTHESIS CONTRACT TEST")
    print("=" * 70)

    # --------------------------------------------------------------
    # 1
    # --------------------------------------------------------------
    print("\n[1] ENUMS AND MODULE CONTRACT")

    assert InvestigationState.REVIEW_REQUIRED.value == "REVIEW_REQUIRED"
    assert EvidenceBalance.STRONG_SUPPORT.value == "STRONG_SUPPORT"
    assert ReviewPriority.CRITICAL.value == "CRITICAL"

    print("  Investigation state enum      : PASS")
    print("  Evidence balance enum         : PASS")
    print("  Review priority enum          : PASS")
    print("  RESULT                        : PASS")

    # --------------------------------------------------------------
    # 2
    # --------------------------------------------------------------
    print("\n[2] EMPTY INVESTIGATION")

    empty = synthesize_investigation(
        SynthesisInput(
            investigation_id="INV_EMPTY"
        )
    )

    assert (
        empty.state
        == InvestigationState.NOT_ASSESSED
    )
    assert (
        empty.evidence_balance
        == EvidenceBalance.NONE
    )
    assert empty.claim_count == 0
    assert empty.fact_established is False
    assert empty.guilt_established is False

    print("  State                         : NOT_ASSESSED")
    print("  Evidence balance              : NONE")
    print("  Fact established              : FALSE")
    print("  Guilt established             : FALSE")
    print("  RESULT                        : PASS")

    # --------------------------------------------------------------
    # 3
    # --------------------------------------------------------------
    print("\n[3] DEVELOPING INVESTIGATION")

    developing_claim = SynthesisClaim(
        claim_id="CLAIM_DEV_001",
        confidence_score=0.52,
        confidence_level="MODERATE",
        supporting_source_count=1,
        independent_source_count=1,
    )

    developing = synthesize_investigation(
        SynthesisInput(
            investigation_id="INV_DEV",
            claims=[developing_claim],
            unresolved_questions=[
                "Who is the actual source of the claim?"
            ],
        )
    )

    assert (
        developing.state
        == InvestigationState.DEVELOPING
    )
    assert developing.assessed_claim_count == 1
    assert developing.corroborated_claim_count == 0
    assert developing.fact_established is False

    print("  State                         : DEVELOPING")
    print("  Assessed claims               : 1")
    print("  Corroborated claims           : 0")
    print("  Fact established              : FALSE")
    print("  RESULT                        : PASS")

    # --------------------------------------------------------------
    # 4
    # --------------------------------------------------------------
    print("\n[4] CORROBORATED RECORD")

    c1 = SynthesisClaim(
        claim_id="CLAIM_CORR_001",
        confidence_score=0.88,
        confidence_level="HIGH",
        supporting_source_count=2,
        independent_source_count=2,
    )

    c2 = SynthesisClaim(
        claim_id="CLAIM_CORR_002",
        confidence_score=0.91,
        confidence_level="HIGH",
        supporting_source_count=3,
        independent_source_count=3,
    )

    corroborated = synthesize_investigation(
        SynthesisInput(
            investigation_id="INV_CORR",
            claims=[c1, c2],
        )
    )

    assert (
        corroborated.state
        == InvestigationState.CORROBORATED
    )
    assert (
        corroborated.evidence_balance
        == EvidenceBalance.STRONG_SUPPORT
    )
    assert corroborated.corroborated_claim_count == 2
    assert corroborated.fact_established is False
    assert corroborated.truth_established is False

    print("  State                         : CORROBORATED")
    print("  Evidence balance              : STRONG_SUPPORT")
    print("  Corroborated claims           : 2")
    print("  Truth established              : FALSE")
    print("  Fact established               : FALSE")
    print("  RESULT                        : PASS")

    # --------------------------------------------------------------
    # 5
    # --------------------------------------------------------------
    print("\n[5] CONTRADICTED RECORD")

    contradicted_claim = SynthesisClaim(
        claim_id="CLAIM_CONTRA_001",
        confidence_score=0.72,
        confidence_level="HIGH",
        supporting_source_count=2,
        independent_source_count=2,
        contradiction_count=2,
    )

    contradicted = synthesize_investigation(
        SynthesisInput(
            investigation_id="INV_CONTRA",
            claims=[contradicted_claim],
            contradiction_count=2,
        )
    )

    assert (
        contradicted.state
        == InvestigationState.CONTESTED
    )
    assert (
        contradicted.evidence_balance
        == EvidenceBalance.CONTESTED
    )
    assert contradicted.contested_claim_count == 1
    assert contradicted.fact_established is False

    print("  State                         : CONTESTED")
    print("  Evidence balance              : CONTESTED")
    print("  Contradictions retained       : PASS")
    print("  Fact established              : FALSE")
    print("  RESULT                        : PASS")

    # --------------------------------------------------------------
    # 6
    # --------------------------------------------------------------
    print("\n[6] CRITICAL CONTRADICTION")

    critical_contra = SynthesisClaim(
        claim_id="CLAIM_CRITICAL_001",
        confidence_score=0.90,
        confidence_level="HIGH",
        supporting_source_count=3,
        independent_source_count=3,
        contradiction_count=1,
        critical_contradiction=True,
    )

    critical_result = synthesize_investigation(
        SynthesisInput(
            investigation_id="INV_CRITICAL",
            claims=[critical_contra],
        )
    )

    assert (
        critical_result.state
        == InvestigationState.REVIEW_REQUIRED
    )
    assert (
        critical_result.review_priority
        == ReviewPriority.CRITICAL
    )
    assert critical_result.fact_established is False

    print("  State                         : REVIEW_REQUIRED")
    print("  Review priority               : CRITICAL")
    print("  Automatic conclusion          : FALSE")
    print("  RESULT                        : PASS")

    # --------------------------------------------------------------
    # 7
    # --------------------------------------------------------------
    print("\n[7] CRITICAL EVIDENCE GAP")

    critical_gap = SynthesisClaim(
        claim_id="CLAIM_GAP_001",
        confidence_score=0.89,
        confidence_level="HIGH",
        supporting_source_count=3,
        independent_source_count=3,
        critical_evidence_gap=True,
        evidence_gap_count=1,
    )

    gap_result = synthesize_investigation(
        SynthesisInput(
            investigation_id="INV_GAP",
            claims=[critical_gap],
            evidence_gaps=[
                "Original source document unavailable"
            ],
        )
    )

    assert (
        gap_result.state
        == InvestigationState.REVIEW_REQUIRED
    )
    assert (
        gap_result.critical_evidence_gap_count > 0
    )
    assert gap_result.fact_established is False

    print("  State                         : REVIEW_REQUIRED")
    print("  Critical gap preserved        : PASS")
    print("  Fact established              : FALSE")
    print("  RESULT                        : PASS")

    # --------------------------------------------------------------
    # 8
    # --------------------------------------------------------------
    print("\n[8] NEGATIVE FINDING SEPARATION")

    negative_result = synthesize_investigation(
        SynthesisInput(
            investigation_id="INV_NEGATIVE",
            claims=[developing_claim],
            negative_finding_count=4,
            access_limitation_count=2,
        )
    )

    assert (
        negative_result.negative_finding_count >= 4
    )
    assert (
        negative_result.non_existence_established
        is False
    )
    assert negative_result.fact_established is False

    print("  Negative findings retained    : PASS")
    print("  Non-existence established     : FALSE")
    print("  Fact established              : FALSE")
    print("  RESULT                        : PASS")

    # --------------------------------------------------------------
    # 9
    # --------------------------------------------------------------
    print("\n[9] IDENTITY SEPARATION")

    identity_result = synthesize_investigation(
        SynthesisInput(
            investigation_id="INV_IDENTITY",
            claims=[c1, c2],
            identity_confirmed=True,
        )
    )

    assert identity_result.identity_confirmed is True
    assert identity_result.identity_established is False
    assert identity_result.guilt_established is False

    print("  Identity input preserved      : TRUE")
    print("  Identity established          : FALSE")
    print("  Guilt established             : FALSE")
    print("  RESULT                        : PASS")

    # --------------------------------------------------------------
    # 10
    # --------------------------------------------------------------
    print("\n[10] NEXT INVESTIGATIVE STEPS")

    assert len(
        critical_result.next_investigative_steps
    ) > 0

    assert len(
        gap_result.next_investigative_steps
    ) > 0

    print("  Critical contradiction step  : PASS")
    print("  Evidence gap step            : PASS")
    print("  RESULT                        : PASS")

    # --------------------------------------------------------------
    # 11
    # --------------------------------------------------------------
    print("\n[11] SERIALIZATION")

    serialized = serialize_synthesis(
        corroborated
    )

    assert isinstance(serialized, dict)
    assert (
        serialized["synthesis_id"]
        == corroborated.synthesis_id
    )
    assert (
        serialized["investigation_id"]
        == "INV_CORR"
    )
    assert (
        serialized["state"]
        == "CORROBORATED"
    )
    assert serialized["fact_established"] is False
    assert serialized["guilt_established"] is False

    encoded = json.dumps(
        serialized,
        ensure_ascii=False,
    )

    assert isinstance(encoded, str)
    assert len(encoded) > 0

    print("  Synthesis ID preserved        : PASS")
    print("  Investigation ID preserved    : PASS")
    print("  State serialized              : PASS")
    print("  Safety state serialized       : PASS")
    print("  JSON serialization            : PASS")
    print("  RESULT                        : PASS")

    # --------------------------------------------------------------
    # 12
    # --------------------------------------------------------------
    print("\n[12] UNSAFE STATE VALIDATION")

    unsafe = synthesize_investigation(
        SynthesisInput(
            investigation_id="INV_UNSAFE",
            claims=[c1],
        )
    )

    unsafe.fact_established = True

    try:
        validate_synthesis(unsafe)
        raise AssertionError(
            "Unsafe fact-established state accepted"
        )
    except ValueError:
        unsafe.fact_established = False

    unsafe.guilt_established = True

    try:
        validate_synthesis(unsafe)
        raise AssertionError(
            "Unsafe guilt-established state accepted"
        )
    except ValueError:
        unsafe.guilt_established = False

    unsafe.identity_established = True

    try:
        validate_synthesis(unsafe)
        raise AssertionError(
            "Unsafe identity-established state accepted"
        )
    except ValueError:
        unsafe.identity_established = False

    unsafe.automatic_conclusion = True

    try:
        validate_synthesis(unsafe)
        raise AssertionError(
            "Automatic conclusion state accepted"
        )
    except ValueError:
        unsafe.automatic_conclusion = False

    print("  Fact establishment blocked    : PASS")
    print("  Guilt establishment blocked   : PASS")
    print("  Identity establishment block  : PASS")
    print("  Automatic conclusion blocked  : PASS")
    print("  RESULT                        : PASS")

    # --------------------------------------------------------------
    # 13
    # --------------------------------------------------------------
    print("\n[13] HUMAN REVIEW GATE")

    for item in [
        empty,
        developing,
        corroborated,
        contradicted,
        critical_result,
        gap_result,
        negative_result,
        identity_result,
    ]:
        assert item.human_review_required is True
        assert item.automatic_conclusion is False

    print("  Human review required         : TRUE")
    print("  Automatic conclusion          : FALSE")
    print("  RESULT                        : PASS")

    # --------------------------------------------------------------
    # 14
    # --------------------------------------------------------------
    print("\n[14] FINAL SAFETY INVARIANTS")

    results = [
        empty,
        developing,
        corroborated,
        contradicted,
        critical_result,
        gap_result,
        negative_result,
        identity_result,
    ]

    assert all(
        item.truth_established is False
        for item in results
    )

    assert all(
        item.fact_established is False
        for item in results
    )

    assert all(
        item.identity_established is False
        for item in results
    )

    assert all(
        item.guilt_established is False
        for item in results
    )

    assert all(
        item.non_existence_established is False
        for item in results
    )

    assert all(
        item.automatic_conclusion is False
        for item in results
    )

    assert all(
        item.human_review_required is True
        for item in results
    )

    print("  Truth establishment           : FALSE")
    print("  Fact establishment             : FALSE")
    print("  Identity establishment         : FALSE")
    print("  Guilt establishment            : FALSE")
    print("  Non-existence establishment    : FALSE")
    print("  Automatic conclusion           : FALSE")
    print("  Human review required          : TRUE")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # 15
    # --------------------------------------------------------------
    print("\n[15] FINAL VALIDATION")

    for item in results:
        assert validate_synthesis(item)

    print("  Synthesis validation           : PASS")

    print("\n" + "=" * 70)
    print("EVIDENCE SYNTHESIS ENGINE : PASS")
    print("=" * 70)
    print("MODULE IMPORT                  : PASS")
    print("EMPTY INVESTIGATION            : PASS")
    print("DEVELOPING STATE               : PASS")
    print("CORROBORATED STATE             : PASS")
    print("CONTESTED STATE                : PASS")
    print("CRITICAL CONTRADICTION         : PASS")
    print("CRITICAL EVIDENCE GAP          : PASS")
    print("NEGATIVE FINDING SEPARATION    : PASS")
    print("IDENTITY SEPARATION            : PASS")
    print("NEXT INVESTIGATIVE STEPS       : PASS")
    print("SERIALIZATION                  : PASS")
    print("UNSAFE STATE VALIDATION        : PASS")
    print("HUMAN REVIEW GATE              : PASS")
    print("SAFETY INVARIANTS              : PASS")
    print("VALIDATION                     : PASS")
    print("TRUTH ESTABLISHMENT            : FALSE")
    print("FACT ESTABLISHMENT             : FALSE")
    print("IDENTITY ESTABLISHMENT         : FALSE")
    print("GUILT ESTABLISHMENT            : FALSE")
    print("NON-EXISTENCE ESTABLISHMENT    : FALSE")
    print("REAL WEB SEARCH                : NOT STARTED")
    print("=" * 70)


if __name__ == "__main__":
    contract_test()
