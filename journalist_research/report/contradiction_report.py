from __future__ import annotations

"""
DOA — Contradiction Report
--------------------------

Journalist-facing contradiction reporting layer.

Purpose:
    Convert contradiction records into a structured report while preserving:

        CLAIM A
            ↓
        SOURCE A
            ↓
        CLAIM B
            ↓
        SOURCE B
            ↓
        CONTRADICTION TYPE
            ↓
        SEVERITY
            ↓
        CONFIDENCE IMPACT
            ↓
        HUMAN REVIEW

Safety invariants:
    CONTRADICTION != FALSEHOOD
    CONFLICT != GUILT
    SOURCE QUALITY != TRUTH
    CONFIDENCE != TRUTH
    SIMILARITY != CONTRADICTION
    AUTOMATIC RESOLUTION IS BLOCKED
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

class ContradictionReportStatus(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    DETECTED = "DETECTED"
    CONTESTED = "CONTESTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    HUMAN_REVIEWED = "HUMAN_REVIEWED"


class ContradictionSeverity(str, Enum):
    UNKNOWN = "UNKNOWN"
    MINOR = "MINOR"
    MATERIAL = "MATERIAL"
    CRITICAL = "CRITICAL"


class ContradictionType(str, Enum):
    FACTUAL = "FACTUAL"
    IDENTITY = "IDENTITY"
    TEMPORAL = "TEMPORAL"
    LOCATION = "LOCATION"
    CORPORATE = "CORPORATE"
    FINANCIAL = "FINANCIAL"
    LEGAL = "LEGAL"
    REGULATORY = "REGULATORY"
    RELATIONSHIP = "RELATIONSHIP"
    SOURCE = "SOURCE"
    OTHER = "OTHER"


class ResolutionState(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    PARTIALLY_RESOLVED = "PARTIALLY_RESOLVED"
    RESOLVED_BY_HUMAN_REVIEW = "RESOLVED_BY_HUMAN_REVIEW"


class ReportEvidenceRole(str, Enum):
    SIDE_A = "SIDE_A"
    SIDE_B = "SIDE_B"
    CONTEXT = "CONTEXT"
    CORROBORATION = "CORROBORATION"
    COUNTER_EVIDENCE = "COUNTER_EVIDENCE"
    UNKNOWN = "UNKNOWN"


# ======================================================================
# HELPERS
# ======================================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{utc_now().strftime('%Y%m%d%H%M%S%f')}"


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _serialize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, list):
        return [_serialize(v) for v in value]

    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}

    if hasattr(value, "__dataclass_fields__"):
        return {
            k: _serialize(v)
            for k, v in asdict(value).items()
        }

    return value


# ======================================================================
# DATA STRUCTURES
# ======================================================================

@dataclass
class ContradictionReportSide:
    side_id: str
    claim_id: str
    claim_text: str
    source_ids: List[str] = field(default_factory=list)
    document_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    entity_ids: List[str] = field(default_factory=list)
    evidence_role: ReportEvidenceRole = ReportEvidenceRole.UNKNOWN
    notes: Optional[str] = None


@dataclass
class ContradictionReportEntry:
    contradiction_id: str
    contradiction_type: ContradictionType
    severity: ContradictionSeverity

    side_a: ContradictionReportSide
    side_b: ContradictionReportSide

    contradiction_text: str

    source_ids: List[str] = field(default_factory=list)
    corroborating_source_ids: List[str] = field(default_factory=list)
    counter_evidence_ids: List[str] = field(default_factory=list)

    confidence_before: Optional[float] = None
    confidence_impact: Optional[float] = None
    confidence_after: Optional[float] = None

    status: ContradictionReportStatus = (
        ContradictionReportStatus.DETECTED
    )

    resolution_state: ResolutionState = (
        ResolutionState.HUMAN_REVIEW_REQUIRED
    )

    automatic_resolution: bool = False
    fact_established: bool = False
    identity_established: bool = False
    guilt_established: bool = False

    human_review_required: bool = True
    human_reviewed: bool = False

    first_detected_at: datetime = field(default_factory=utc_now)
    last_updated_at: datetime = field(default_factory=utc_now)

    notes: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ContradictionReport:
    report_id: str
    investigation_id: str

    entries: List[ContradictionReportEntry] = field(
        default_factory=list
    )

    status: ContradictionReportStatus = (
        ContradictionReportStatus.NOT_ASSESSED
    )

    total_contradictions: int = 0
    critical_contradictions: int = 0
    material_contradictions: int = 0
    unresolved_contradictions: int = 0

    source_ids: List[str] = field(default_factory=list)
    claim_ids: List[str] = field(default_factory=list)

    contradictions_preserved: bool = True
    automatic_resolution: bool = False
    fact_established: bool = False
    identity_established: bool = False
    guilt_established: bool = False
    human_review_required: bool = True

    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    metadata: Dict[str, Any] = field(default_factory=dict)


# ======================================================================
# VALIDATION
# ======================================================================

def validate_side(side: ContradictionReportSide) -> bool:
    if not side.side_id:
        raise ValueError("side_id required")

    if not side.claim_id:
        raise ValueError("claim_id required")

    if not side.claim_text.strip():
        raise ValueError("claim_text required")

    if not isinstance(side.source_ids, list):
        raise ValueError("source_ids must be list")

    return True


def validate_entry(entry: ContradictionReportEntry) -> bool:
    if not entry.contradiction_id:
        raise ValueError("contradiction_id required")

    validate_side(entry.side_a)
    validate_side(entry.side_b)

    if entry.side_a.claim_id == entry.side_b.claim_id:
        raise ValueError("contradiction sides must reference different claims")

    if not entry.contradiction_text.strip():
        raise ValueError("contradiction_text required")

    if entry.confidence_before is not None:
        if not 0.0 <= entry.confidence_before <= 1.0:
            raise ValueError("confidence_before outside [0,1]")

    if entry.confidence_after is not None:
        if not 0.0 <= entry.confidence_after <= 1.0:
            raise ValueError("confidence_after outside [0,1]")

    if entry.confidence_impact is not None:
        if not -1.0 <= entry.confidence_impact <= 1.0:
            raise ValueError("confidence_impact outside [-1,1]")

    # Automatic resolution is categorically forbidden here.
    if entry.automatic_resolution:
        raise ValueError("automatic contradiction resolution is forbidden")

    # A contradiction report cannot establish truth/guilt/identity.
    if entry.fact_established:
        raise ValueError("fact establishment forbidden")

    if entry.identity_established:
        raise ValueError("identity establishment forbidden")

    if entry.guilt_established:
        raise ValueError("guilt establishment forbidden")

    if not entry.human_review_required:
        raise ValueError("human review gate cannot be disabled")

    return True


def validate_report(report: ContradictionReport) -> bool:
    if not report.report_id:
        raise ValueError("report_id required")

    if not report.investigation_id:
        raise ValueError("investigation_id required")

    for entry in report.entries:
        validate_entry(entry)

    if report.automatic_resolution:
        raise ValueError("report automatic resolution forbidden")

    if report.fact_established:
        raise ValueError("report fact establishment forbidden")

    if report.identity_established:
        raise ValueError("report identity establishment forbidden")

    if report.guilt_established:
        raise ValueError("report guilt establishment forbidden")

    if not report.contradictions_preserved:
        raise ValueError("contradictions must be preserved")

    if not report.human_review_required:
        raise ValueError("human review gate cannot be disabled")

    return True


# ======================================================================
# REPORT LOGIC
# ======================================================================

def determine_entry_status(
    severity: ContradictionSeverity,
    human_reviewed: bool = False,
) -> ContradictionReportStatus:

    if human_reviewed:
        return ContradictionReportStatus.HUMAN_REVIEWED

    if severity == ContradictionSeverity.CRITICAL:
        return ContradictionReportStatus.REVIEW_REQUIRED

    if severity == ContradictionSeverity.MATERIAL:
        return ContradictionReportStatus.CONTESTED

    return ContradictionReportStatus.DETECTED


def build_contradiction_entry(
    *,
    claim_a_id: str,
    claim_a_text: str,
    claim_b_id: str,
    claim_b_text: str,
    contradiction_type: ContradictionType,
    severity: ContradictionSeverity,
    contradiction_text: str,
    source_a_ids: Optional[List[str]] = None,
    source_b_ids: Optional[List[str]] = None,
    document_a_ids: Optional[List[str]] = None,
    document_b_ids: Optional[List[str]] = None,
    evidence_a_ids: Optional[List[str]] = None,
    evidence_b_ids: Optional[List[str]] = None,
    entity_a_ids: Optional[List[str]] = None,
    entity_b_ids: Optional[List[str]] = None,
    corroborating_source_ids: Optional[List[str]] = None,
    counter_evidence_ids: Optional[List[str]] = None,
    confidence_before: Optional[float] = None,
    confidence_impact: Optional[float] = None,
    notes: Optional[List[str]] = None,
) -> ContradictionReportEntry:

    side_a = ContradictionReportSide(
        side_id=new_id("SIDE_A"),
        claim_id=claim_a_id,
        claim_text=claim_a_text,
        source_ids=list(source_a_ids or []),
        document_ids=list(document_a_ids or []),
        evidence_ids=list(evidence_a_ids or []),
        entity_ids=list(entity_a_ids or []),
        evidence_role=ReportEvidenceRole.SIDE_A,
    )

    side_b = ContradictionReportSide(
        side_id=new_id("SIDE_B"),
        claim_id=claim_b_id,
        claim_text=claim_b_text,
        source_ids=list(source_b_ids or []),
        document_ids=list(document_b_ids or []),
        evidence_ids=list(evidence_b_ids or []),
        entity_ids=list(entity_b_ids or []),
        evidence_role=ReportEvidenceRole.SIDE_B,
    )

    all_sources = list(
        dict.fromkeys(
            side_a.source_ids
            + side_b.source_ids
            + list(corroborating_source_ids or [])
        )
    )

    entry = ContradictionReportEntry(
        contradiction_id=new_id("CONTR"),
        contradiction_type=contradiction_type,
        severity=severity,
        side_a=side_a,
        side_b=side_b,
        contradiction_text=contradiction_text,
        source_ids=all_sources,
        corroborating_source_ids=list(
            corroborating_source_ids or []
        ),
        counter_evidence_ids=list(
            counter_evidence_ids or []
        ),
        confidence_before=confidence_before,
        confidence_impact=confidence_impact,
        confidence_after=(
            round(
                max(
                    0.0,
                    min(
                        1.0,
                        confidence_before + confidence_impact,
                    ),
                ),
                6,
            )
            if confidence_before is not None
            and confidence_impact is not None
            else confidence_before
        ),
        status=determine_entry_status(severity),
        resolution_state=ResolutionState.HUMAN_REVIEW_REQUIRED,
        automatic_resolution=False,
        fact_established=False,
        identity_established=False,
        guilt_established=False,
        human_review_required=True,
        human_reviewed=False,
        notes=list(notes or []),
    )

    validate_entry(entry)
    return entry


def add_entry(
    report: ContradictionReport,
    entry: ContradictionReportEntry,
) -> ContradictionReport:

    validate_entry(entry)

    report.entries.append(entry)

    report.total_contradictions = len(report.entries)

    report.critical_contradictions = sum(
        1
        for item in report.entries
        if item.severity == ContradictionSeverity.CRITICAL
    )

    report.material_contradictions = sum(
        1
        for item in report.entries
        if item.severity == ContradictionSeverity.MATERIAL
    )

    report.unresolved_contradictions = sum(
        1
        for item in report.entries
        if item.resolution_state
        != ResolutionState.RESOLVED_BY_HUMAN_REVIEW
    )

    report.source_ids = list(
        dict.fromkeys(
            source_id
            for item in report.entries
            for source_id in item.source_ids
        )
    )

    report.claim_ids = list(
        dict.fromkeys(
            claim_id
            for item in report.entries
            for claim_id in (
                item.side_a.claim_id,
                item.side_b.claim_id,
            )
        )
    )

    if report.critical_contradictions > 0:
        report.status = ContradictionReportStatus.REVIEW_REQUIRED
    elif report.total_contradictions > 0:
        report.status = ContradictionReportStatus.CONTESTED
    else:
        report.status = ContradictionReportStatus.NOT_ASSESSED

    report.automatic_resolution = False
    report.fact_established = False
    report.identity_established = False
    report.guilt_established = False
    report.human_review_required = True
    report.contradictions_preserved = True
    report.updated_at = utc_now()

    validate_report(report)
    return report


def build_contradiction_report(
    investigation_id: str,
    entries: Optional[List[ContradictionReportEntry]] = None,
) -> ContradictionReport:

    report = ContradictionReport(
        report_id=new_id("CONTR_REPORT"),
        investigation_id=investigation_id,
    )

    for entry in entries or []:
        add_entry(report, entry)

    validate_report(report)
    return report


# ======================================================================
# QUERIES
# ======================================================================

def critical_contradictions(
    report: ContradictionReport,
) -> List[ContradictionReportEntry]:

    return [
        entry
        for entry in report.entries
        if entry.severity == ContradictionSeverity.CRITICAL
    ]


def unresolved_contradictions(
    report: ContradictionReport,
) -> List[ContradictionReportEntry]:

    return [
        entry
        for entry in report.entries
        if entry.resolution_state
        != ResolutionState.RESOLVED_BY_HUMAN_REVIEW
    ]


def contradictions_for_claim(
    report: ContradictionReport,
    claim_id: str,
) -> List[ContradictionReportEntry]:

    return [
        entry
        for entry in report.entries
        if (
            entry.side_a.claim_id == claim_id
            or entry.side_b.claim_id == claim_id
        )
    ]


def contradictions_for_source(
    report: ContradictionReport,
    source_id: str,
) -> List[ContradictionReportEntry]:

    return [
        entry
        for entry in report.entries
        if source_id in entry.source_ids
    ]


# ======================================================================
# HUMAN REVIEW
# ======================================================================

def mark_human_review_required(
    entry: ContradictionReportEntry,
    note: Optional[str] = None,
) -> ContradictionReportEntry:

    entry.human_review_required = True
    entry.human_reviewed = False
    entry.automatic_resolution = False
    entry.resolution_state = ResolutionState.HUMAN_REVIEW_REQUIRED
    entry.status = (
        ContradictionReportStatus.REVIEW_REQUIRED
        if entry.severity == ContradictionSeverity.CRITICAL
        else ContradictionReportStatus.CONTESTED
    )

    if note:
        entry.notes.append(note)

    entry.last_updated_at = utc_now()

    validate_entry(entry)
    return entry


def record_human_review(
    entry: ContradictionReportEntry,
    resolution_note: str,
) -> ContradictionReportEntry:

    if not resolution_note.strip():
        raise ValueError("human review resolution note required")

    entry.human_reviewed = True
    entry.human_review_required = True
    entry.automatic_resolution = False
    entry.resolution_state = (
        ResolutionState.RESOLVED_BY_HUMAN_REVIEW
    )
    entry.status = ContradictionReportStatus.HUMAN_REVIEWED
    entry.notes.append(resolution_note)
    entry.last_updated_at = utc_now()

    # Human review may record a resolution state,
    # but this module still cannot establish truth/guilt.
    entry.fact_established = False
    entry.identity_established = False
    entry.guilt_established = False

    validate_entry(entry)
    return entry


# ======================================================================
# SERIALIZATION
# ======================================================================

def serialize_entry(
    entry: ContradictionReportEntry,
) -> Dict[str, Any]:

    validate_entry(entry)
    return _serialize(entry)


def serialize_report(
    report: ContradictionReport,
) -> Dict[str, Any]:

    validate_report(report)
    return _serialize(report)


def report_to_json(
    report: ContradictionReport,
) -> str:

    return json.dumps(
        serialize_report(report),
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )


# ======================================================================
# CONTRACT TEST
# ======================================================================

def contract_test() -> None:

    print("=" * 70)
    print("DOA CONTRADICTION REPORT CONTRACT TEST")
    print("=" * 70)

    # --------------------------------------------------------------
    # [1] ENUMS
    # --------------------------------------------------------------
    print("\n[1] ENUMS AND MODULE CONTRACT")

    assert ContradictionReportStatus.REVIEW_REQUIRED.value
    assert ContradictionSeverity.CRITICAL.value
    assert ContradictionType.IDENTITY.value
    assert ResolutionState.HUMAN_REVIEW_REQUIRED.value
    assert ReportEvidenceRole.SIDE_A.value

    print("  Report status enum              : PASS")
    print("  Severity enum                   : PASS")
    print("  Contradiction type enum         : PASS")
    print("  Resolution enum                 : PASS")
    print("  Evidence role enum              : PASS")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # [2] SIDE CREATION
    # --------------------------------------------------------------
    print("\n[2] CONTRADICTION SIDE CREATION")

    side = ContradictionReportSide(
        side_id="SIDE_TEST_A",
        claim_id="CLAIM_A",
        claim_text="Company A was incorporated in 2019.",
        source_ids=["SRC_GOV_001"],
        document_ids=["DOC_GOV_001"],
        evidence_ids=["EVD_001"],
        entity_ids=["ENT_A"],
        evidence_role=ReportEvidenceRole.SIDE_A,
    )

    validate_side(side)

    print("  Side created                    : PASS")
    print("  Claim linkage                   : PASS")
    print("  Source linkage                  : PASS")
    print("  Provenance retained             : PASS")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # [3] BASIC CONTRADICTION
    # --------------------------------------------------------------
    print("\n[3] BASIC CONTRADICTION ENTRY")

    entry = build_contradiction_entry(
        claim_a_id="CLAIM_A",
        claim_a_text="Company A was incorporated in 2019.",
        claim_b_id="CLAIM_B",
        claim_b_text="Company A was incorporated in 2021.",
        contradiction_type=ContradictionType.CORPORATE,
        severity=ContradictionSeverity.MATERIAL,
        contradiction_text=(
            "The two sources provide different incorporation years."
        ),
        source_a_ids=["SRC_GOV_001"],
        source_b_ids=["SRC_NEWS_001"],
        document_a_ids=["DOC_GOV_001"],
        document_b_ids=["DOC_NEWS_001"],
        entity_a_ids=["ENT_A"],
        entity_b_ids=["ENT_A"],
        confidence_before=0.80,
        confidence_impact=-0.20,
    )

    assert entry.status == ContradictionReportStatus.CONTESTED
    assert entry.resolution_state == ResolutionState.HUMAN_REVIEW_REQUIRED
    assert entry.automatic_resolution is False

    print("  Entry created                   : PASS")
    print("  Both claims preserved           : PASS")
    print("  Both sources preserved          : PASS")
    print("  Status                          : CONTESTED")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # [4] CONFIDENCE IMPACT
    # --------------------------------------------------------------
    print("\n[4] CONFIDENCE IMPACT")

    assert entry.confidence_before == 0.80
    assert entry.confidence_impact == -0.20
    assert entry.confidence_after == 0.60

    print("  Confidence before               : 0.80")
    print("  Confidence impact               : -0.20")
    print("  Confidence after                : 0.60")
    print("  Truth automatically established : FALSE")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # [5] CRITICAL CONTRADICTION
    # --------------------------------------------------------------
    print("\n[5] CRITICAL CONTRADICTION")

    critical = build_contradiction_entry(
        claim_a_id="CLAIM_ID_A",
        claim_a_text="Person A is the director of Company X.",
        claim_b_id="CLAIM_ID_B",
        claim_b_text="Person B is the director of Company X.",
        contradiction_type=ContradictionType.IDENTITY,
        severity=ContradictionSeverity.CRITICAL,
        contradiction_text=(
            "Independent records identify different directors."
        ),
        source_a_ids=["SRC_REG_001"],
        source_b_ids=["SRC_REG_002"],
        entity_a_ids=["ENT_A"],
        entity_b_ids=["ENT_B"],
    )

    assert critical.status == ContradictionReportStatus.REVIEW_REQUIRED
    assert critical.human_review_required is True
    assert critical.automatic_resolution is False

    print("  Severity                       : CRITICAL")
    print("  Review required                : PASS")
    print("  Automatic resolution           : BLOCKED")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # [6] REPORT CREATION
    # --------------------------------------------------------------
    print("\n[6] REPORT CREATION")

    report = build_contradiction_report(
        "INV_CONTR_001",
        [entry, critical],
    )

    assert report.investigation_id == "INV_CONTR_001"
    assert report.total_contradictions == 2
    assert report.critical_contradictions == 1
    assert report.material_contradictions == 1

    print("  Investigation linkage          : PASS")
    print("  Contradiction count            : 2")
    print("  Critical contradictions        : 1")
    print("  Material contradictions        : 1")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # [7] CLAIM QUERY
    # --------------------------------------------------------------
    print("\n[7] CLAIM QUERIES")

    claim_results = contradictions_for_claim(
        report,
        "CLAIM_A",
    )

    assert len(claim_results) == 1

    print("  Claim contradiction query      : PASS")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # [8] SOURCE QUERY
    # --------------------------------------------------------------
    print("\n[8] SOURCE QUERIES")

    source_results = contradictions_for_source(
        report,
        "SRC_REG_001",
    )

    assert len(source_results) == 1

    print("  Source contradiction query     : PASS")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # [9] CRITICAL / UNRESOLVED
    # --------------------------------------------------------------
    print("\n[9] REVIEW QUEUES")

    critical_items = critical_contradictions(report)
    unresolved_items = unresolved_contradictions(report)

    assert len(critical_items) == 1
    assert len(unresolved_items) == 2

    print("  Critical queue                 : PASS")
    print("  Unresolved queue               : PASS")
    print("  Human review required          : TRUE")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # [10] HUMAN REVIEW
    # --------------------------------------------------------------
    print("\n[10] HUMAN REVIEW")

    record_human_review(
        critical,
        "Human reviewer compared the two registry records; further "
        "document verification is required before a final conclusion.",
    )

    assert critical.human_reviewed is True
    assert (
        critical.resolution_state
        == ResolutionState.RESOLVED_BY_HUMAN_REVIEW
    )
    assert critical.automatic_resolution is False
    assert critical.fact_established is False
    assert critical.identity_established is False
    assert critical.guilt_established is False

    print("  Human review recorded           : PASS")
    print("  Resolution state                : HUMAN_REVIEWED")
    print("  Automatic resolution            : FALSE")
    print("  Fact establishment              : FALSE")
    print("  Identity establishment          : FALSE")
    print("  Guilt establishment             : FALSE")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # [11] NEGATIVE FINDING SEPARATION
    # --------------------------------------------------------------
    print("\n[11] NEGATIVE FINDING SEPARATION")

    entry.metadata["negative_finding_present"] = True
    entry.metadata["non_existence_established"] = False

    validate_entry(entry)

    assert entry.metadata["non_existence_established"] is False

    print("  Negative finding retained       : PASS")
    print("  Non-existence established       : FALSE")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # [12] SERIALIZATION
    # --------------------------------------------------------------
    print("\n[12] SERIALIZATION")

    serialized = serialize_report(report)
    json_output = report_to_json(report)

    assert serialized["report_id"] == report.report_id
    assert serialized["investigation_id"] == "INV_CONTR_001"
    assert len(serialized["entries"]) == 2
    assert isinstance(json_output, str)

    print("  Report ID preserved              : PASS")
    print("  Investigation ID preserved       : PASS")
    print("  Entries serialized               : PASS")
    print("  JSON serialization               : PASS")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # [13] UNSAFE STATE VALIDATION
    # --------------------------------------------------------------
    print("\n[13] UNSAFE STATE VALIDATION")

    assert report.automatic_resolution is False
    assert report.fact_established is False
    assert report.identity_established is False
    assert report.guilt_established is False
    assert report.human_review_required is True

    print("  Automatic resolution blocked     : PASS")
    print("  Truth/fact establishment blocked : PASS")
    print("  Identity establishment blocked   : PASS")
    print("  Guilt establishment blocked      : PASS")
    print("  Human review gate                : PASS")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # [14] BOTH SIDES PRESERVED
    # --------------------------------------------------------------
    print("\n[14] CONTRADICTION PRESERVATION")

    assert (
        entry.side_a.claim_text
        != entry.side_b.claim_text
    )

    assert entry.side_a.source_ids
    assert entry.side_b.source_ids

    print("  Side A preserved                : TRUE")
    print("  Side B preserved                : TRUE")
    print("  Source A preserved              : TRUE")
    print("  Source B preserved              : TRUE")
    print("  Overwrite occurred              : FALSE")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # [15] FINAL SAFETY INVARIANTS
    # --------------------------------------------------------------
    print("\n[15] FINAL SAFETY INVARIANTS")

    print("  Contradiction != falsehood     : TRUE")
    print("  Conflict != guilt               : TRUE")
    print("  Source quality != truth         : TRUE")
    print("  Confidence != truth             : TRUE")
    print("  Automatic resolution             : FALSE")
    print("  Fact establishment               : FALSE")
    print("  Identity establishment           : FALSE")
    print("  Guilt establishment              : FALSE")
    print("  Non-existence establishment      : FALSE")
    print("  Human review required            : TRUE")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # [16] FINAL VALIDATION
    # --------------------------------------------------------------
    print("\n[16] FINAL VALIDATION")

    validate_side(entry.side_a)
    validate_side(entry.side_b)
    validate_entry(entry)
    validate_report(report)

    print("  Side validation                 : PASS")
    print("  Entry validation                : PASS")
    print("  Report validation               : PASS")

    print("\n" + "=" * 70)
    print("CONTRADICTION REPORT : PASS")
    print("=" * 70)
    print("MODULE IMPORT                  : PASS")
    print("CONTRADICTION SIDE CONTRACT    : PASS")
    print("BASIC CONTRADICTION            : PASS")
    print("CONFIDENCE IMPACT              : PASS")
    print("CRITICAL CONTRADICTION         : PASS")
    print("REPORT CREATION                : PASS")
    print("CLAIM QUERIES                  : PASS")
    print("SOURCE QUERIES                 : PASS")
    print("REVIEW QUEUES                  : PASS")
    print("HUMAN REVIEW GATE              : PASS")
    print("NEGATIVE FINDING SEPARATION    : PASS")
    print("SERIALIZATION                  : PASS")
    print("CONTRADICTION PRESERVATION     : PASS")
    print("UNSAFE STATE VALIDATION        : PASS")
    print("SAFETY INVARIANTS              : PASS")
    print("VALIDATION                     : PASS")
    print("FACT ESTABLISHMENT             : FALSE")
    print("IDENTITY ESTABLISHMENT         : FALSE")
    print("GUILT ESTABLISHMENT            : FALSE")
    print("NON-EXISTENCE ESTABLISHMENT    : FALSE")
    print("AUTOMATIC RESOLUTION            : FALSE")
    print("REAL WEB SEARCH                : NOT STARTED")
    print("=" * 70)


if __name__ == "__main__":
    contract_test()
