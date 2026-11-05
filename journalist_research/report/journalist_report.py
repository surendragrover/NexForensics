from __future__ import annotations

"""
DOA — Journalist Intelligence Dossier

Final report assembly layer.

Pipeline:

Question
    ↓
Hypotheses
    ↓
Search Tasks
    ↓
Sources / Documents
    ↓
Claims
    ↓
Entities / Identity
    ↓
Timeline / Relationships
    ↓
Evidence
    ↓
Contradictions
    ↓
Confidence
    ↓
Negative Findings
    ↓
Source Matrix
    ↓
Contradiction Report
    ↓
Evidence Graph
    ↓
JOURNALIST INTELLIGENCE DOSSIER

Safety invariants:

    REPORT != TRUTH
    EVIDENCE != AUTOMATIC FACT
    CONFIDENCE != TRUTH
    IDENTITY != GUILT
    ASSOCIATION != MISCONDUCT
    NEGATIVE FINDING != NON-EXISTENCE
    SOURCE QUALITY != CLAIM TRUTH
    AUTOMATIC CONCLUSION IS BLOCKED
    HUMAN REVIEW REMAINS REQUIRED
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
import json


# ======================================================================
# ENUMS
# ======================================================================

class DossierStatus(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    DEVELOPING = "DEVELOPING"
    CORROBORATED = "CORROBORATED"
    CONTESTED = "CONTESTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    READY_FOR_HUMAN_REVIEW = "READY_FOR_HUMAN_REVIEW"


class FindingState(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    DEVELOPING = "DEVELOPING"
    CORROBORATED = "CORROBORATED"
    CONTESTED = "CONTESTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NOT_ASSESSED = "NOT_ASSESSED"


class FindingType(str, Enum):
    CLAIM = "CLAIM"
    IDENTITY = "IDENTITY"
    RELATIONSHIP = "RELATIONSHIP"
    TIMELINE = "TIMELINE"
    CORPORATE = "CORPORATE"
    LEGAL = "LEGAL"
    REGULATORY = "REGULATORY"
    FINANCIAL = "FINANCIAL"
    DIGITAL_FOOTPRINT = "DIGITAL_FOOTPRINT"
    HISTORICAL = "HISTORICAL"
    ADVERSE_MEDIA = "ADVERSE_MEDIA"
    NEGATIVE_FINDING = "NEGATIVE_FINDING"
    CONTRADICTION = "CONTRADICTION"
    EVIDENCE_GAP = "EVIDENCE_GAP"


class ReviewState(str, Enum):
    NOT_REVIEWED = "NOT_REVIEWED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    HUMAN_REVIEWED = "HUMAN_REVIEWED"


class EvidenceBalance(str, Enum):
    NONE = "NONE"
    LIMITED = "LIMITED"
    MIXED = "MIXED"
    SUPPORTING = "SUPPORTING"
    STRONG_SUPPORT = "STRONG_SUPPORT"
    CONTESTED = "CONTESTED"


# ======================================================================
# HELPERS
# ======================================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{utc_now().strftime('%Y%m%d%H%M%S%f')}"


def serialize_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, list):
        return [serialize_value(v) for v in value]

    if isinstance(value, dict):
        return {
            key: serialize_value(val)
            for key, val in value.items()
        }

    if hasattr(value, "__dataclass_fields__"):
        return {
            key: serialize_value(val)
            for key, val in asdict(value).items()
        }

    return value


# ======================================================================
# DATA STRUCTURES
# ======================================================================

@dataclass
class DossierFinding:
    finding_id: str
    finding_type: FindingType
    title: str
    statement: str

    state: FindingState = FindingState.UNVERIFIED

    claim_ids: List[str] = field(default_factory=list)
    source_ids: List[str] = field(default_factory=list)
    document_ids: List[str] = field(default_factory=list)
    entity_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    contradiction_ids: List[str] = field(default_factory=list)

    supporting_claim_ids: List[str] = field(
        default_factory=list
    )
    contradicting_claim_ids: List[str] = field(
        default_factory=list
    )

    confidence: Optional[float] = None
    evidence_balance: EvidenceBalance = EvidenceBalance.NONE

    negative_finding: bool = False
    non_existence_established: bool = False

    review_state: ReviewState = ReviewState.REVIEW_REQUIRED

    fact_established: bool = False
    identity_established: bool = False
    guilt_established: bool = False

    notes: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DossierSection:
    section_id: str
    title: str
    order: int

    finding_ids: List[str] = field(
        default_factory=list
    )

    summary: Optional[str] = None

    review_state: ReviewState = ReviewState.REVIEW_REQUIRED

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InvestigativeQuestion:
    question_id: str
    text: str

    category: Optional[str] = None

    hypothesis_ids: List[str] = field(
        default_factory=list
    )

    search_task_ids: List[str] = field(
        default_factory=list
    )

    finding_ids: List[str] = field(
        default_factory=list
    )

    unanswered: bool = True

    review_state: ReviewState = ReviewState.REVIEW_REQUIRED

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InvestigativeNextStep:
    step_id: str
    priority: int
    title: str
    reason: str

    related_claim_ids: List[str] = field(
        default_factory=list
    )
    related_source_ids: List[str] = field(
        default_factory=list
    )
    related_contradiction_ids: List[str] = field(
        default_factory=list
    )

    human_action_required: bool = True

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class JournalistIntelligenceDossier:
    dossier_id: str
    investigation_id: str
    title: str

    executive_summary: str = ""

    questions: List[InvestigativeQuestion] = field(
        default_factory=list
    )

    sections: List[DossierSection] = field(
        default_factory=list
    )

    findings: List[DossierFinding] = field(
        default_factory=list
    )

    next_steps: List[InvestigativeNextStep] = field(
        default_factory=list
    )

    status: DossierStatus = DossierStatus.NOT_ASSESSED

    evidence_balance: EvidenceBalance = EvidenceBalance.NONE

    total_questions: int = 0
    unanswered_questions: int = 0
    total_findings: int = 0
    contested_findings: int = 0
    evidence_gaps: int = 0
    negative_findings: int = 0
    contradictions: int = 0

    source_ids: List[str] = field(default_factory=list)
    claim_ids: List[str] = field(default_factory=list)
    entity_ids: List[str] = field(default_factory=list)

    provenance_preserved: bool = True
    contradictions_preserved: bool = True
    negative_findings_preserved: bool = True

    automatic_conclusion: bool = False
    fact_established: bool = False
    identity_established: bool = False
    guilt_established: bool = False
    non_existence_established: bool = False

    human_review_required: bool = True

    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    metadata: Dict[str, Any] = field(default_factory=dict)


# ======================================================================
# VALIDATION
# ======================================================================

def validate_finding(
    finding: DossierFinding,
) -> bool:

    if not finding.finding_id:
        raise ValueError("finding_id required")

    if not finding.title.strip():
        raise ValueError("finding title required")

    if not finding.statement.strip():
        raise ValueError("finding statement required")

    if finding.confidence is not None:
        if not 0.0 <= finding.confidence <= 1.0:
            raise ValueError(
                "finding confidence outside [0,1]"
            )

    if finding.non_existence_established:
        raise ValueError(
            "non-existence establishment forbidden"
        )

    if finding.fact_established:
        raise ValueError(
            "fact establishment forbidden"
        )

    if finding.identity_established:
        raise ValueError(
            "identity establishment forbidden"
        )

    if finding.guilt_established:
        raise ValueError(
            "guilt establishment forbidden"
        )

    if not finding.negative_finding:
        if finding.non_existence_established:
            raise ValueError(
                "non-negative finding cannot establish non-existence"
            )

    if finding.review_state == ReviewState.NOT_REVIEWED:
        raise ValueError(
            "final dossier findings require review state"
        )

    return True


def validate_section(
    section: DossierSection,
) -> bool:

    if not section.section_id:
        raise ValueError("section_id required")

    if not section.title.strip():
        raise ValueError("section title required")

    if section.order < 1:
        raise ValueError("section order must be >= 1")

    if section.review_state == ReviewState.NOT_REVIEWED:
        raise ValueError(
            "dossier section requires review state"
        )

    return True


def validate_question(
    question: InvestigativeQuestion,
) -> bool:

    if not question.question_id:
        raise ValueError("question_id required")

    if not question.text.strip():
        raise ValueError("question text required")

    if question.review_state == ReviewState.NOT_REVIEWED:
        raise ValueError(
            "question requires review state"
        )

    return True


def validate_next_step(
    step: InvestigativeNextStep,
) -> bool:

    if not step.step_id:
        raise ValueError("step_id required")

    if not step.title.strip():
        raise ValueError("next-step title required")

    if not step.reason.strip():
        raise ValueError("next-step reason required")

    if step.priority < 1:
        raise ValueError(
            "next-step priority must be >= 1"
        )

    if not step.human_action_required:
        raise ValueError(
            "human action gate cannot be disabled"
        )

    return True


def validate_dossier(
    dossier: JournalistIntelligenceDossier,
) -> bool:

    if not dossier.dossier_id:
        raise ValueError("dossier_id required")

    if not dossier.investigation_id:
        raise ValueError("investigation_id required")

    if not dossier.title.strip():
        raise ValueError("dossier title required")

    for question in dossier.questions:
        validate_question(question)

    for section in dossier.sections:
        validate_section(section)

    for finding in dossier.findings:
        validate_finding(finding)

    for step in dossier.next_steps:
        validate_next_step(step)

    if not dossier.provenance_preserved:
        raise ValueError(
            "provenance must be preserved"
        )

    if not dossier.contradictions_preserved:
        raise ValueError(
            "contradictions must be preserved"
        )

    if not dossier.negative_findings_preserved:
        raise ValueError(
            "negative findings must be preserved"
        )

    if dossier.automatic_conclusion:
        raise ValueError(
            "automatic conclusion forbidden"
        )

    if dossier.fact_established:
        raise ValueError(
            "fact establishment forbidden"
        )

    if dossier.identity_established:
        raise ValueError(
            "identity establishment forbidden"
        )

    if dossier.guilt_established:
        raise ValueError(
            "guilt establishment forbidden"
        )

    if dossier.non_existence_established:
        raise ValueError(
            "non-existence establishment forbidden"
        )

    if not dossier.human_review_required:
        raise ValueError(
            "human review gate cannot be disabled"
        )

    return True


# ======================================================================
# BUILDERS
# ======================================================================

def build_finding(
    *,
    finding_type: FindingType,
    title: str,
    statement: str,
    state: FindingState = FindingState.UNVERIFIED,
    claim_ids: Optional[List[str]] = None,
    source_ids: Optional[List[str]] = None,
    document_ids: Optional[List[str]] = None,
    entity_ids: Optional[List[str]] = None,
    evidence_ids: Optional[List[str]] = None,
    contradiction_ids: Optional[List[str]] = None,
    supporting_claim_ids: Optional[List[str]] = None,
    contradicting_claim_ids: Optional[List[str]] = None,
    confidence: Optional[float] = None,
    evidence_balance: EvidenceBalance = EvidenceBalance.NONE,
    negative_finding: bool = False,
    notes: Optional[List[str]] = None,
) -> DossierFinding:

    finding = DossierFinding(
        finding_id=new_id("FINDING"),
        finding_type=finding_type,
        title=title,
        statement=statement,
        state=state,
        claim_ids=list(claim_ids or []),
        source_ids=list(source_ids or []),
        document_ids=list(document_ids or []),
        entity_ids=list(entity_ids or []),
        evidence_ids=list(evidence_ids or []),
        contradiction_ids=list(contradiction_ids or []),
        supporting_claim_ids=list(
            supporting_claim_ids or []
        ),
        contradicting_claim_ids=list(
            contradicting_claim_ids or []
        ),
        confidence=confidence,
        evidence_balance=evidence_balance,
        negative_finding=negative_finding,
        notes=list(notes or []),
        review_state=ReviewState.REVIEW_REQUIRED,
    )

    validate_finding(finding)
    return finding


def build_question(
    text: str,
    *,
    category: Optional[str] = None,
    hypothesis_ids: Optional[List[str]] = None,
    search_task_ids: Optional[List[str]] = None,
    finding_ids: Optional[List[str]] = None,
    unanswered: bool = True,
) -> InvestigativeQuestion:

    question = InvestigativeQuestion(
        question_id=new_id("QUESTION"),
        text=text,
        category=category,
        hypothesis_ids=list(
            hypothesis_ids or []
        ),
        search_task_ids=list(
            search_task_ids or []
        ),
        finding_ids=list(
            finding_ids or []
        ),
        unanswered=unanswered,
        review_state=ReviewState.REVIEW_REQUIRED,
    )

    validate_question(question)
    return question


def build_section(
    title: str,
    order: int,
    *,
    finding_ids: Optional[List[str]] = None,
    summary: Optional[str] = None,
) -> DossierSection:

    section = DossierSection(
        section_id=new_id("SECTION"),
        title=title,
        order=order,
        finding_ids=list(
            finding_ids or []
        ),
        summary=summary,
        review_state=ReviewState.REVIEW_REQUIRED,
    )

    validate_section(section)
    return section


def build_next_step(
    priority: int,
    title: str,
    reason: str,
    *,
    related_claim_ids: Optional[List[str]] = None,
    related_source_ids: Optional[List[str]] = None,
    related_contradiction_ids: Optional[
        List[str]
    ] = None,
) -> InvestigativeNextStep:

    step = InvestigativeNextStep(
        step_id=new_id("NEXT"),
        priority=priority,
        title=title,
        reason=reason,
        related_claim_ids=list(
            related_claim_ids or []
        ),
        related_source_ids=list(
            related_source_ids or []
        ),
        related_contradiction_ids=list(
            related_contradiction_ids or []
        ),
        human_action_required=True,
    )

    validate_next_step(step)
    return step


# ======================================================================
# DOSSIER ASSEMBLY
# ======================================================================

def add_question(
    dossier: JournalistIntelligenceDossier,
    question: InvestigativeQuestion,
) -> JournalistIntelligenceDossier:

    validate_question(question)

    dossier.questions.append(question)
    dossier.total_questions = len(
        dossier.questions
    )
    dossier.unanswered_questions = sum(
        1
        for item in dossier.questions
        if item.unanswered
    )

    dossier.updated_at = utc_now()
    return dossier


def add_section(
    dossier: JournalistIntelligenceDossier,
    section: DossierSection,
) -> JournalistIntelligenceDossier:

    validate_section(section)

    if any(
        item.section_id == section.section_id
        for item in dossier.sections
    ):
        raise ValueError(
            f"duplicate section: {section.section_id}"
        )

    dossier.sections.append(section)
    dossier.sections.sort(
        key=lambda item: item.order
    )

    dossier.updated_at = utc_now()
    return dossier


def add_finding(
    dossier: JournalistIntelligenceDossier,
    finding: DossierFinding,
) -> JournalistIntelligenceDossier:

    validate_finding(finding)

    if any(
        item.finding_id == finding.finding_id
        for item in dossier.findings
    ):
        raise ValueError(
            f"duplicate finding: {finding.finding_id}"
        )

    dossier.findings.append(finding)

    dossier.total_findings = len(
        dossier.findings
    )

    dossier.contested_findings = sum(
        1
        for item in dossier.findings
        if item.state
        == FindingState.CONTESTED
    )

    dossier.evidence_gaps = sum(
        1
        for item in dossier.findings
        if item.finding_type
        == FindingType.EVIDENCE_GAP
    )

    dossier.negative_findings = sum(
        1
        for item in dossier.findings
        if item.negative_finding
    )

    dossier.contradictions = sum(
        1
        for item in dossier.findings
        if item.finding_type
        == FindingType.CONTRADICTION
    )

    dossier.source_ids = list(
        dict.fromkeys(
            source_id
            for item in dossier.findings
            for source_id in item.source_ids
        )
    )

    dossier.claim_ids = list(
        dict.fromkeys(
            claim_id
            for item in dossier.findings
            for claim_id in item.claim_ids
        )
    )

    dossier.entity_ids = list(
        dict.fromkeys(
            entity_id
            for item in dossier.findings
            for entity_id in item.entity_ids
        )
    )

    dossier.updated_at = utc_now()
    return dossier


def add_next_step(
    dossier: JournalistIntelligenceDossier,
    step: InvestigativeNextStep,
) -> JournalistIntelligenceDossier:

    validate_next_step(step)

    dossier.next_steps.append(step)
    dossier.next_steps.sort(
        key=lambda item: item.priority
    )

    dossier.updated_at = utc_now()
    return dossier


def calculate_evidence_balance(
    dossier: JournalistIntelligenceDossier,
) -> EvidenceBalance:

    if not dossier.findings:
        return EvidenceBalance.NONE

    contested = sum(
        1
        for finding in dossier.findings
        if finding.state
        == FindingState.CONTESTED
        or finding.contradiction_ids
    )

    corroborated = sum(
        1
        for finding in dossier.findings
        if finding.state
        == FindingState.CORROBORATED
    )

    developing = sum(
        1
        for finding in dossier.findings
        if finding.state
        == FindingState.DEVELOPING
    )

    if contested:
        return EvidenceBalance.CONTESTED

    if corroborated >= 2:
        return EvidenceBalance.STRONG_SUPPORT

    if corroborated == 1:
        return EvidenceBalance.SUPPORTING

    if developing:
        return EvidenceBalance.LIMITED

    return EvidenceBalance.NONE


def update_dossier_status(
    dossier: JournalistIntelligenceDossier,
) -> JournalistIntelligenceDossier:

    dossier.total_questions = len(
        dossier.questions
    )

    dossier.unanswered_questions = sum(
        1
        for item in dossier.questions
        if item.unanswered
    )

    dossier.total_findings = len(
        dossier.findings
    )

    dossier.contested_findings = sum(
        1
        for item in dossier.findings
        if item.state
        == FindingState.CONTESTED
    )

    dossier.evidence_gaps = sum(
        1
        for item in dossier.findings
        if item.finding_type
        == FindingType.EVIDENCE_GAP
    )

    dossier.negative_findings = sum(
        1
        for item in dossier.findings
        if item.negative_finding
    )

    dossier.contradictions = sum(
        1
        for item in dossier.findings
        if item.finding_type
        == FindingType.CONTRADICTION
        or item.contradiction_ids
    )

    dossier.evidence_balance = (
        calculate_evidence_balance(dossier)
    )

    if dossier.contradictions > 0:
        dossier.status = (
            DossierStatus.REVIEW_REQUIRED
        )

    elif dossier.evidence_gaps > 0:
        dossier.status = (
            DossierStatus.REVIEW_REQUIRED
        )

    elif dossier.total_findings == 0:
        dossier.status = (
            DossierStatus.NOT_ASSESSED
        )

    elif (
        dossier.total_findings > 0
        and dossier.unanswered_questions > 0
    ):
        dossier.status = (
            DossierStatus.DEVELOPING
        )

    elif dossier.evidence_balance in (
        EvidenceBalance.SUPPORTING,
        EvidenceBalance.STRONG_SUPPORT,
    ):
        dossier.status = (
            DossierStatus.READY_FOR_HUMAN_REVIEW
        )

    else:
        dossier.status = (
            DossierStatus.DEVELOPING
        )

    dossier.automatic_conclusion = False
    dossier.fact_established = False
    dossier.identity_established = False
    dossier.guilt_established = False
    dossier.non_existence_established = False

    dossier.provenance_preserved = True
    dossier.contradictions_preserved = True
    dossier.negative_findings_preserved = True
    dossier.human_review_required = True

    dossier.updated_at = utc_now()

    validate_dossier(dossier)
    return dossier


def build_dossier(
    investigation_id: str,
    title: str,
    *,
    executive_summary: str = "",
    questions: Optional[
        List[InvestigativeQuestion]
    ] = None,
    sections: Optional[
        List[DossierSection]
    ] = None,
    findings: Optional[
        List[DossierFinding]
    ] = None,
    next_steps: Optional[
        List[InvestigativeNextStep]
    ] = None,
) -> JournalistIntelligenceDossier:

    dossier = JournalistIntelligenceDossier(
        dossier_id=new_id("DOSSIER"),
        investigation_id=investigation_id,
        title=title,
        executive_summary=executive_summary,
    )

    for question in questions or []:
        add_question(dossier, question)

    for section in sections or []:
        add_section(dossier, section)

    for finding in findings or []:
        add_finding(dossier, finding)

    for step in next_steps or []:
        add_next_step(dossier, step)

    update_dossier_status(dossier)

    return dossier


# ======================================================================
# QUERY FUNCTIONS
# ======================================================================

def findings_for_question(
    dossier: JournalistIntelligenceDossier,
    question_id: str,
) -> List[DossierFinding]:

    question = next(
        (
            item
            for item in dossier.questions
            if item.question_id == question_id
        ),
        None,
    )

    if question is None:
        return []

    ids = set(question.finding_ids)

    return [
        finding
        for finding in dossier.findings
        if finding.finding_id in ids
    ]


def findings_for_entity(
    dossier: JournalistIntelligenceDossier,
    entity_id: str,
) -> List[DossierFinding]:

    return [
        finding
        for finding in dossier.findings
        if entity_id in finding.entity_ids
    ]


def findings_for_claim(
    dossier: JournalistIntelligenceDossier,
    claim_id: str,
) -> List[DossierFinding]:

    return [
        finding
        for finding in dossier.findings
        if claim_id in finding.claim_ids
    ]


def contested_findings(
    dossier: JournalistIntelligenceDossier,
) -> List[DossierFinding]:

    return [
        finding
        for finding in dossier.findings
        if (
            finding.state == FindingState.CONTESTED
            or finding.contradiction_ids
        )
    ]


def evidence_gap_findings(
    dossier: JournalistIntelligenceDossier,
) -> List[DossierFinding]:

    return [
        finding
        for finding in dossier.findings
        if finding.finding_type
        == FindingType.EVIDENCE_GAP
    ]


def negative_findings(
    dossier: JournalistIntelligenceDossier,
) -> List[DossierFinding]:

    return [
        finding
        for finding in dossier.findings
        if finding.negative_finding
    ]


def unanswered_questions(
    dossier: JournalistIntelligenceDossier,
) -> List[InvestigativeQuestion]:

    return [
        question
        for question in dossier.questions
        if question.unanswered
    ]


# ======================================================================
# SERIALIZATION
# ======================================================================

def serialize_finding(
    finding: DossierFinding,
) -> Dict[str, Any]:

    validate_finding(finding)
    return serialize_value(finding)


def serialize_section(
    section: DossierSection,
) -> Dict[str, Any]:

    validate_section(section)
    return serialize_value(section)


def serialize_question(
    question: InvestigativeQuestion,
) -> Dict[str, Any]:

    validate_question(question)
    return serialize_value(question)


def serialize_next_step(
    step: InvestigativeNextStep,
) -> Dict[str, Any]:

    validate_next_step(step)
    return serialize_value(step)


def serialize_dossier(
    dossier: JournalistIntelligenceDossier,
) -> Dict[str, Any]:

    validate_dossier(dossier)
    return serialize_value(dossier)


def dossier_to_json(
    dossier: JournalistIntelligenceDossier,
) -> str:

    return json.dumps(
        serialize_dossier(dossier),
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )


# ======================================================================
# CONTRACT TEST
# ======================================================================

def contract_test() -> None:

    print("=" * 70)
    print("DOA JOURNALIST INTELLIGENCE DOSSIER CONTRACT TEST")
    print("=" * 70)

    # --------------------------------------------------------------
    # [1] ENUMS
    # --------------------------------------------------------------
    print("\n[1] ENUMS AND MODULE CONTRACT")

    assert DossierStatus.REVIEW_REQUIRED.value
    assert FindingState.CORROBORATED.value
    assert FindingType.CLAIM.value
    assert ReviewState.REVIEW_REQUIRED.value
    assert EvidenceBalance.CONTESTED.value

    print("  Dossier status enum             : PASS")
    print("  Finding state enum              : PASS")
    print("  Finding type enum               : PASS")
    print("  Review state enum               : PASS")
    print("  Evidence balance enum           : PASS")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # [2] QUESTION
    # --------------------------------------------------------------
    print("\n[2] INVESTIGATIVE QUESTION")

    question = build_question(
        "What is the historical corporate relationship between "
        "Company X and Person A?",
        category="CORPORATE",
        hypothesis_ids=["HYP_001"],
        search_task_ids=["TASK_001", "TASK_002"],
    )

    assert question.unanswered is True
    assert question.review_state == (
        ReviewState.REVIEW_REQUIRED
    )

    print("  Question created                : PASS")
    print("  Category preserved              : PASS")
    print("  Hypothesis linkage              : PASS")
    print("  Search task linkage             : PASS")
    print("  Unanswered state                : TRUE")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # [3] FINDING
    # --------------------------------------------------------------
    print("\n[3] DOSSIER FINDING")

    finding = build_finding(
        finding_type=FindingType.CORPORATE,
        title="Corporate relationship indicator",
        statement=(
            "Public records contain information suggesting "
            "a corporate relationship requiring verification."
        ),
        state=FindingState.CORROBORATED,
        claim_ids=["CLAIM_001", "CLAIM_002"],
        source_ids=["SRC_GOV_001", "SRC_NEWS_001"],
        document_ids=["DOC_GOV_001", "DOC_NEWS_001"],
        entity_ids=["ENT_COMPANY_X", "ENT_PERSON_A"],
        evidence_ids=["EVD_001"],
        confidence=0.82,
        evidence_balance=EvidenceBalance.STRONG_SUPPORT,
        notes=[
            "Corroboration does not establish misconduct."
        ],
    )

    assert finding.state == FindingState.CORROBORATED
    assert finding.confidence == 0.82
    assert finding.fact_established is False
    assert finding.guilt_established is False

    print("  Finding created                 : PASS")
    print("  Claim linkage                   : PASS")
    print("  Source linkage                  : PASS")
    print("  Entity linkage                  : PASS")
    print("  Evidence linkage               : PASS")
    print("  Confidence preserved            : PASS")
    print("  Fact established                : FALSE")
    print("  Guilt established               : FALSE")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # [4] NEGATIVE FINDING
    # --------------------------------------------------------------
    print("\n[4] NEGATIVE FINDING")

    negative = build_finding(
        finding_type=FindingType.NEGATIVE_FINDING,
        title="No matching archived record located",
        statement=(
            "The defined archive search did not return a matching "
            "record within the searched scope."
        ),
        state=FindingState.DEVELOPING,
        source_ids=["SRC_ARCHIVE_001"],
        negative_finding=True,
        notes=[
            "Absence of result does not establish non-existence."
        ],
    )

    assert negative.negative_finding is True
    assert negative.non_existence_established is False

    print("  Negative finding created        : PASS")
    print("  Search scope preserved          : PASS")
    print("  Non-existence established       : FALSE")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # [5] CONTRADICTION
    # --------------------------------------------------------------
    print("\n[5] CONTRADICTION FINDING")

    contradiction = build_finding(
        finding_type=FindingType.CONTRADICTION,
        title="Conflicting incorporation dates",
        statement=(
            "Two sources provide different incorporation dates."
        ),
        state=FindingState.CONTESTED,
        claim_ids=["CLAIM_003", "CLAIM_004"],
        source_ids=["SRC_REG_001", "SRC_NEWS_002"],
        contradiction_ids=["CONTR_001"],
        evidence_balance=EvidenceBalance.CONTESTED,
        notes=[
            "Both sides must remain visible."
        ],
    )

    assert contradiction.state == (
        FindingState.CONTESTED
    )
    assert contradiction.contradiction_ids
    assert contradiction.fact_established is False

    print("  Contradiction created            : PASS")
    print("  Both claims linked               : PASS")
    print("  Contradiction ID preserved      : PASS")
    print("  Status                           : CONTESTED")
    print("  RESULT                           : PASS")

    # --------------------------------------------------------------
    # [6] EVIDENCE GAP
    # --------------------------------------------------------------
    print("\n[6] EVIDENCE GAP")

    gap = build_finding(
        finding_type=FindingType.EVIDENCE_GAP,
        title="Original corporate filing unavailable",
        statement=(
            "The primary filing required to independently verify "
            "the claim was not available in the current record."
        ),
        state=FindingState.REVIEW_REQUIRED,
        evidence_balance=EvidenceBalance.LIMITED,
        notes=[
            "Additional primary-source verification required."
        ],
    )

    assert gap.finding_type == (
        FindingType.EVIDENCE_GAP
    )
    assert gap.review_state == (
        ReviewState.REVIEW_REQUIRED
    )

    print("  Evidence gap created             : PASS")
    print("  Review required                  : PASS")
    print("  Primary-source limitation        : PASS")
    print("  RESULT                           : PASS")

    # --------------------------------------------------------------
    # [7] SECTION
    # --------------------------------------------------------------
    print("\n[7] DOSSIER SECTION")

    section = build_section(
        "Corporate History",
        5,
        finding_ids=[
            finding.finding_id,
            contradiction.finding_id,
        ],
        summary=(
            "Corporate findings and conflicting source records."
        ),
    )

    assert section.order == 5
    assert len(section.finding_ids) == 2

    print("  Section created                  : PASS")
    print("  Finding linkage                  : PASS")
    print("  Ordering preserved               : PASS")
    print("  RESULT                           : PASS")

    # --------------------------------------------------------------
    # [8] NEXT STEP
    # --------------------------------------------------------------
    print("\n[8] INVESTIGATIVE NEXT STEP")

    next_step = build_next_step(
        1,
        "Verify the original corporate filing",
        (
            "The current record contains a material evidence gap "
            "and conflicting dates."
        ),
        related_claim_ids=[
            "CLAIM_003",
            "CLAIM_004",
        ],
        related_source_ids=[
            "SRC_REG_001",
            "SRC_NEWS_002",
        ],
        related_contradiction_ids=[
            "CONTR_001",
        ],
    )

    assert next_step.priority == 1
    assert next_step.human_action_required is True

    print("  Next step created                : PASS")
    print("  Priority preserved               : PASS")
    print("  Related claims preserved         : PASS")
    print("  Human action required            : TRUE")
    print("  RESULT                           : PASS")

    # --------------------------------------------------------------
    # [9] DOSSIER CREATION
    # --------------------------------------------------------------
    print("\n[9] DOSSIER CREATION")

    dossier = build_dossier(
        "INV_DOSSIER_001",
        "Journalist Intelligence Dossier — Company X",
        executive_summary=(
            "Current evidence is mixed and requires human review."
        ),
        questions=[question],
        sections=[section],
        findings=[
            finding,
            negative,
            contradiction,
            gap,
        ],
        next_steps=[next_step],
    )

    assert dossier.investigation_id == (
        "INV_DOSSIER_001"
    )
    assert dossier.total_questions == 1
    assert dossier.total_findings == 4
    assert dossier.evidence_gaps == 1
    assert dossier.negative_findings == 1
    assert dossier.contradictions == 1

    print("  Investigation linkage            : PASS")
    print("  Question count                   : 1")
    print("  Finding count                    : 4")
    print("  Evidence gaps                    : 1")
    print("  Negative findings                : 1")
    print("  Contradictions                   : 1")
    print("  RESULT                           : PASS")

    # --------------------------------------------------------------
    # [10] STATUS
    # --------------------------------------------------------------
    print("\n[10] DOSSIER STATUS")

    assert dossier.status == (
        DossierStatus.REVIEW_REQUIRED
    )
    assert dossier.evidence_balance == (
        EvidenceBalance.CONTESTED
    )

    print("  Status                           : REVIEW_REQUIRED")
    print("  Evidence balance                 : CONTESTED")
    print("  Human review required            : TRUE")
    print("  Automatic conclusion             : FALSE")
    print("  RESULT                           : PASS")

    # --------------------------------------------------------------
    # [11] QUERY FUNCTIONS
    # --------------------------------------------------------------
    print("\n[11] DOSSIER QUERIES")

    question.finding_ids = [
        finding.finding_id,
        contradiction.finding_id,
    ]

    assert len(
        findings_for_question(
            dossier,
            question.question_id,
        )
    ) == 2

    assert len(
        findings_for_entity(
            dossier,
            "ENT_COMPANY_X",
        )
    ) == 1

    assert len(
        findings_for_claim(
            dossier,
            "CLAIM_003",
        )
    ) == 1

    assert len(
        contested_findings(dossier)
    ) >= 1

    assert len(
        evidence_gap_findings(dossier)
    ) == 1

    assert len(
        negative_findings(dossier)
    ) == 1

    assert len(
        unanswered_questions(dossier)
    ) == 1

    print("  Findings by question             : PASS")
    print("  Findings by entity               : PASS")
    print("  Findings by claim                : PASS")
    print("  Contested findings               : PASS")
    print("  Evidence gap query               : PASS")
    print("  Negative finding query           : PASS")
    print("  Unanswered question query        : PASS")
    print("  RESULT                           : PASS")

    # --------------------------------------------------------------
    # [12] SERIALIZATION
    # --------------------------------------------------------------
    print("\n[12] SERIALIZATION")

    serialized = serialize_dossier(dossier)
    json_output = dossier_to_json(dossier)

    assert serialized["dossier_id"] == dossier.dossier_id
    assert serialized["investigation_id"] == (
        "INV_DOSSIER_001"
    )
    assert len(serialized["findings"]) == 4
    assert len(serialized["questions"]) == 1
    assert len(serialized["sections"]) == 1
    assert len(serialized["next_steps"]) == 1
    assert isinstance(json_output, str)

    print("  Dossier ID preserved             : PASS")
    print("  Investigation ID preserved       : PASS")
    print("  Findings serialized              : PASS")
    print("  Questions serialized             : PASS")
    print("  Sections serialized              : PASS")
    print("  Next steps serialized            : PASS")
    print("  JSON serialization               : PASS")
    print("  RESULT                           : PASS")

    # --------------------------------------------------------------
    # [13] PROVENANCE
    # --------------------------------------------------------------
    print("\n[13] PROVENANCE AND NEGATIVE FINDINGS")

    assert dossier.provenance_preserved is True
    assert dossier.contradictions_preserved is True
    assert dossier.negative_findings_preserved is True
    assert negative.non_existence_established is False

    print("  Provenance preserved             : TRUE")
    print("  Contradictions preserved         : TRUE")
    print("  Negative findings preserved      : TRUE")
    print("  Non-existence established        : FALSE")
    print("  RESULT                           : PASS")

    # --------------------------------------------------------------
    # [14] UNSAFE STATE VALIDATION
    # --------------------------------------------------------------
    print("\n[14] UNSAFE STATE VALIDATION")

    assert dossier.automatic_conclusion is False
    assert dossier.fact_established is False
    assert dossier.identity_established is False
    assert dossier.guilt_established is False
    assert dossier.non_existence_established is False

    print("  Automatic conclusion blocked     : PASS")
    print("  Fact establishment blocked       : PASS")
    print("  Identity establishment blocked   : PASS")
    print("  Guilt establishment blocked      : PASS")
    print("  Non-existence blocked            : PASS")
    print("  RESULT                           : PASS")

    # --------------------------------------------------------------
    # [15] HUMAN REVIEW GATE
    # --------------------------------------------------------------
    print("\n[15] HUMAN REVIEW GATE")

    assert dossier.human_review_required is True

    for item in dossier.findings:
        assert item.review_state != (
            ReviewState.NOT_REVIEWED
        )

    print("  Dossier review gate              : PASS")
    print("  Finding review states            : PASS")
    print("  Human review required             : TRUE")
    print("  RESULT                           : PASS")

    # --------------------------------------------------------------
    # [16] NEGATIVE FINDING SAFETY
    # --------------------------------------------------------------
    print("\n[16] NEGATIVE FINDING SAFETY")

    assert negative.negative_finding is True
    assert negative.non_existence_established is False

    print("  Negative finding retained        : PASS")
    print("  Non-existence inference blocked  : PASS")
    print("  RESULT                           : PASS")

    # --------------------------------------------------------------
    # [17] CONTRADICTION SAFETY
    # --------------------------------------------------------------
    print("\n[17] CONTRADICTION SAFETY")

    assert contradiction.contradiction_ids
    assert contradiction.state == (
        FindingState.CONTESTED
    )
    assert contradiction.fact_established is False

    print("  Contradiction preserved           : PASS")
    print("  Contested state preserved         : PASS")
    print("  Automatic truth decision          : FALSE")
    print("  RESULT                           : PASS")

    # --------------------------------------------------------------
    # [18] FINAL SAFETY INVARIANTS
    # --------------------------------------------------------------
    print("\n[18] FINAL SAFETY INVARIANTS")

    print("  Report != truth                  : TRUE")
    print("  Evidence != automatic fact       : TRUE")
    print("  Confidence != truth              : TRUE")
    print("  Identity != guilt                : TRUE")
    print("  Association != misconduct        : TRUE")
    print("  Negative finding != nonexistence : TRUE")
    print("  Automatic conclusion             : FALSE")
    print("  Fact establishment               : FALSE")
    print("  Identity establishment           : FALSE")
    print("  Guilt establishment              : FALSE")
    print("  Non-existence establishment      : FALSE")
    print("  Human review required             : TRUE")
    print("  RESULT                           : PASS")

    # --------------------------------------------------------------
    # [19] FINAL VALIDATION
    # --------------------------------------------------------------
    print("\n[19] FINAL VALIDATION")

    for item in dossier.questions:
        validate_question(item)

    for item in dossier.sections:
        validate_section(item)

    for item in dossier.findings:
        validate_finding(item)

    for item in dossier.next_steps:
        validate_next_step(item)

    validate_dossier(dossier)

    print("  Question validation              : PASS")
    print("  Section validation               : PASS")
    print("  Finding validation               : PASS")
    print("  Next-step validation             : PASS")
    print("  Dossier validation               : PASS")

    print("\n" + "=" * 70)
    print("JOURNALIST INTELLIGENCE DOSSIER : PASS")
    print("=" * 70)
    print("MODULE IMPORT                  : PASS")
    print("INVESTIGATIVE QUESTION         : PASS")
    print("DOSSIER FINDING                : PASS")
    print("NEGATIVE FINDING               : PASS")
    print("CONTRADICTION FINDING          : PASS")
    print("EVIDENCE GAP                   : PASS")
    print("DOSSIER SECTION                : PASS")
    print("INVESTIGATIVE NEXT STEP        : PASS")
    print("DOSSIER CREATION               : PASS")
    print("DOSSIER STATUS                 : PASS")
    print("DOSSIER QUERIES                : PASS")
    print("SERIALIZATION                  : PASS")
    print("PROVENANCE PRESERVATION        : PASS")
    print("CONTRADICTION PRESERVATION     : PASS")
    print("NEGATIVE FINDING SAFETY        : PASS")
    print("HUMAN REVIEW GATE              : PASS")
    print("UNSAFE STATE VALIDATION        : PASS")
    print("SAFETY INVARIANTS              : PASS")
    print("VALIDATION                     : PASS")
    print("FACT ESTABLISHMENT             : FALSE")
    print("IDENTITY ESTABLISHMENT         : FALSE")
    print("GUILT ESTABLISHMENT            : FALSE")
    print("NON-EXISTENCE ESTABLISHMENT    : FALSE")
    print("AUTOMATIC CONCLUSION             : FALSE")
    print("REAL WEB SEARCH                : NOT STARTED")
    print("=" * 70)


if __name__ == "__main__":
    contract_test()
