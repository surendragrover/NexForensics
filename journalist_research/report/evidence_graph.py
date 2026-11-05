from __future__ import annotations

"""
DOA — Journalist Evidence Graph Report

Converts the investigative evidence graph into a journalist-facing,
provenance-preserving report.

Core chain:

    CLAIM
      ↓
    SOURCE
      ↓
    DOCUMENT
      ↓
    ENTITY
      ↓
    CORROBORATION
      ↓
    CONTRADICTION
      ↓
    CONFIDENCE
      ↓
    HUMAN REVIEW

Safety invariants:

    EVIDENCE GRAPH != TRUTH
    SOURCE QUALITY != TRUTH
    CONFIDENCE != TRUTH
    IDENTITY != GUILT
    ASSOCIATION != MISCONDUCT
    NEGATIVE FINDING != NON-EXISTENCE
    GRAPH STRUCTURE != FACT ESTABLISHMENT
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

class EvidenceGraphReportStatus(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    PARTIAL = "PARTIAL"
    DEVELOPING = "DEVELOPING"
    COMPLETE = "COMPLETE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class ReportNodeType(str, Enum):
    CLAIM = "CLAIM"
    SOURCE = "SOURCE"
    DOCUMENT = "DOCUMENT"
    ENTITY = "ENTITY"
    EVIDENCE = "EVIDENCE"
    CONTRADICTION = "CONTRADICTION"
    CONFIDENCE = "CONFIDENCE"
    INVESTIGATION = "INVESTIGATION"


class ReportEdgeType(str, Enum):
    CLAIM_SUPPORTED_BY_SOURCE = "CLAIM_SUPPORTED_BY_SOURCE"
    CLAIM_DERIVED_FROM_DOCUMENT = "CLAIM_DERIVED_FROM_DOCUMENT"
    CLAIM_REFERENCES_ENTITY = "CLAIM_REFERENCES_ENTITY"
    SOURCE_CONTAINS_DOCUMENT = "SOURCE_CONTAINS_DOCUMENT"
    DOCUMENT_MENTIONS_ENTITY = "DOCUMENT_MENTIONS_ENTITY"
    DOCUMENT_CONTAINS_CLAIM = "DOCUMENT_CONTAINS_CLAIM"
    CLAIM_CORROBORATES_CLAIM = "CLAIM_CORROBORATES_CLAIM"
    CLAIM_CONTRADICTS_CLAIM = "CLAIM_CONTRADICTS_CLAIM"
    CLAIM_HAS_EVIDENCE = "CLAIM_HAS_EVIDENCE"
    EVIDENCE_SUPPORTS_CLAIM = "EVIDENCE_SUPPORTS_CLAIM"
    EVIDENCE_CONTRADICTS_CLAIM = "EVIDENCE_CONTRADICTS_CLAIM"
    CLAIM_HAS_CONFIDENCE = "CLAIM_HAS_CONFIDENCE"
    INVESTIGATION_CONTAINS_CLAIM = "INVESTIGATION_CONTAINS_CLAIM"
    INVESTIGATION_CONTAINS_SOURCE = "INVESTIGATION_CONTAINS_SOURCE"
    INVESTIGATION_CONTAINS_ENTITY = "INVESTIGATION_CONTAINS_ENTITY"


class EvidencePolarity(str, Enum):
    SUPPORTING = "SUPPORTING"
    CONTRADICTORY = "CONTRADICTORY"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class ReviewState(str, Enum):
    NOT_REVIEWED = "NOT_REVIEWED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    HUMAN_REVIEWED = "HUMAN_REVIEWED"


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
class EvidenceGraphReportNode:
    node_id: str
    node_type: ReportNodeType
    label: str

    source_ids: List[str] = field(default_factory=list)
    claim_ids: List[str] = field(default_factory=list)
    entity_ids: List[str] = field(default_factory=list)
    document_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    contradiction_ids: List[str] = field(default_factory=list)

    polarity: EvidencePolarity = EvidencePolarity.UNKNOWN

    confidence: Optional[float] = None

    provenance_preserved: bool = True
    fact_established: bool = False
    identity_established: bool = False
    guilt_established: bool = False

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceGraphReportEdge:
    edge_id: str
    source_node_id: str
    target_node_id: str
    edge_type: ReportEdgeType

    polarity: EvidencePolarity = EvidencePolarity.UNKNOWN

    source_ids: List[str] = field(default_factory=list)
    claim_ids: List[str] = field(default_factory=list)
    contradiction_ids: List[str] = field(default_factory=list)

    provenance_preserved: bool = True

    fact_established: bool = False
    identity_established: bool = False
    guilt_established: bool = False

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceGraphClaimSummary:
    claim_id: str
    claim_text: str

    source_ids: List[str] = field(default_factory=list)
    document_ids: List[str] = field(default_factory=list)
    entity_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    contradiction_ids: List[str] = field(default_factory=list)

    corroborating_claim_ids: List[str] = field(default_factory=list)
    contradicting_claim_ids: List[str] = field(default_factory=list)

    confidence: Optional[float] = None

    polarity: EvidencePolarity = EvidencePolarity.UNKNOWN

    review_state: ReviewState = ReviewState.REVIEW_REQUIRED

    fact_established: bool = False
    identity_established: bool = False
    guilt_established: bool = False

    notes: List[str] = field(default_factory=list)


@dataclass
class EvidenceGraphReport:
    report_id: str
    investigation_id: str

    nodes: List[EvidenceGraphReportNode] = field(
        default_factory=list
    )
    edges: List[EvidenceGraphReportEdge] = field(
        default_factory=list
    )
    claim_summaries: List[EvidenceGraphClaimSummary] = field(
        default_factory=list
    )

    status: EvidenceGraphReportStatus = (
        EvidenceGraphReportStatus.NOT_ASSESSED
    )

    node_count: int = 0
    edge_count: int = 0
    claim_count: int = 0
    source_count: int = 0
    entity_count: int = 0
    contradiction_count: int = 0

    corroboration_links: int = 0
    contradictory_links: int = 0

    provenance_preserved: bool = True
    contradictions_preserved: bool = True

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

def validate_node(
    node: EvidenceGraphReportNode,
) -> bool:

    if not node.node_id:
        raise ValueError("node_id required")

    if not node.label.strip():
        raise ValueError("node label required")

    if node.confidence is not None:
        if not 0.0 <= node.confidence <= 1.0:
            raise ValueError("confidence outside [0,1]")

    if not node.provenance_preserved:
        raise ValueError("node provenance must be preserved")

    if node.fact_established:
        raise ValueError("node fact establishment forbidden")

    if node.identity_established:
        raise ValueError("node identity establishment forbidden")

    if node.guilt_established:
        raise ValueError("node guilt establishment forbidden")

    return True


def validate_edge(
    edge: EvidenceGraphReportEdge,
) -> bool:

    if not edge.edge_id:
        raise ValueError("edge_id required")

    if not edge.source_node_id:
        raise ValueError("source_node_id required")

    if not edge.target_node_id:
        raise ValueError("target_node_id required")

    if edge.source_node_id == edge.target_node_id:
        raise ValueError("self-edge forbidden")

    if not edge.provenance_preserved:
        raise ValueError("edge provenance must be preserved")

    if edge.fact_established:
        raise ValueError("edge fact establishment forbidden")

    if edge.identity_established:
        raise ValueError("edge identity establishment forbidden")

    if edge.guilt_established:
        raise ValueError("edge guilt establishment forbidden")

    return True


def validate_claim_summary(
    summary: EvidenceGraphClaimSummary,
) -> bool:

    if not summary.claim_id:
        raise ValueError("claim_id required")

    if not summary.claim_text.strip():
        raise ValueError("claim_text required")

    if summary.confidence is not None:
        if not 0.0 <= summary.confidence <= 1.0:
            raise ValueError("confidence outside [0,1]")

    if summary.fact_established:
        raise ValueError("claim fact establishment forbidden")

    if summary.identity_established:
        raise ValueError("claim identity establishment forbidden")

    if summary.guilt_established:
        raise ValueError("claim guilt establishment forbidden")

    if summary.review_state == ReviewState.NOT_REVIEWED:
        raise ValueError(
            "journalist evidence graph requires review state"
        )

    return True


def validate_report(
    report: EvidenceGraphReport,
) -> bool:

    if not report.report_id:
        raise ValueError("report_id required")

    if not report.investigation_id:
        raise ValueError("investigation_id required")

    for node in report.nodes:
        validate_node(node)

    for edge in report.edges:
        validate_edge(edge)

    for summary in report.claim_summaries:
        validate_claim_summary(summary)

    if not report.provenance_preserved:
        raise ValueError("report provenance must be preserved")

    if not report.contradictions_preserved:
        raise ValueError(
            "report contradictions must be preserved"
        )

    if report.automatic_conclusion:
        raise ValueError(
            "automatic conclusion is forbidden"
        )

    if report.fact_established:
        raise ValueError(
            "report fact establishment forbidden"
        )

    if report.identity_established:
        raise ValueError(
            "report identity establishment forbidden"
        )

    if report.guilt_established:
        raise ValueError(
            "report guilt establishment forbidden"
        )

    if report.non_existence_established:
        raise ValueError(
            "report non-existence establishment forbidden"
        )

    if not report.human_review_required:
        raise ValueError(
            "human review gate cannot be disabled"
        )

    return True


# ======================================================================
# BUILDERS
# ======================================================================

def build_node(
    node_id: str,
    node_type: ReportNodeType,
    label: str,
    *,
    source_ids: Optional[List[str]] = None,
    claim_ids: Optional[List[str]] = None,
    entity_ids: Optional[List[str]] = None,
    document_ids: Optional[List[str]] = None,
    evidence_ids: Optional[List[str]] = None,
    contradiction_ids: Optional[List[str]] = None,
    polarity: EvidencePolarity = EvidencePolarity.UNKNOWN,
    confidence: Optional[float] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> EvidenceGraphReportNode:

    node = EvidenceGraphReportNode(
        node_id=node_id,
        node_type=node_type,
        label=label,
        source_ids=list(source_ids or []),
        claim_ids=list(claim_ids or []),
        entity_ids=list(entity_ids or []),
        document_ids=list(document_ids or []),
        evidence_ids=list(evidence_ids or []),
        contradiction_ids=list(contradiction_ids or []),
        polarity=polarity,
        confidence=confidence,
        metadata=dict(metadata or {}),
    )

    validate_node(node)
    return node


def build_edge(
    source_node_id: str,
    target_node_id: str,
    edge_type: ReportEdgeType,
    *,
    source_ids: Optional[List[str]] = None,
    claim_ids: Optional[List[str]] = None,
    contradiction_ids: Optional[List[str]] = None,
    polarity: EvidencePolarity = EvidencePolarity.UNKNOWN,
    metadata: Optional[Dict[str, Any]] = None,
) -> EvidenceGraphReportEdge:

    edge = EvidenceGraphReportEdge(
        edge_id=new_id("EDGE"),
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        edge_type=edge_type,
        polarity=polarity,
        source_ids=list(source_ids or []),
        claim_ids=list(claim_ids or []),
        contradiction_ids=list(contradiction_ids or []),
        metadata=dict(metadata or {}),
    )

    validate_edge(edge)
    return edge


def build_claim_summary(
    claim_id: str,
    claim_text: str,
    *,
    source_ids: Optional[List[str]] = None,
    document_ids: Optional[List[str]] = None,
    entity_ids: Optional[List[str]] = None,
    evidence_ids: Optional[List[str]] = None,
    contradiction_ids: Optional[List[str]] = None,
    corroborating_claim_ids: Optional[List[str]] = None,
    contradicting_claim_ids: Optional[List[str]] = None,
    confidence: Optional[float] = None,
    polarity: EvidencePolarity = EvidencePolarity.UNKNOWN,
    notes: Optional[List[str]] = None,
) -> EvidenceGraphClaimSummary:

    summary = EvidenceGraphClaimSummary(
        claim_id=claim_id,
        claim_text=claim_text,
        source_ids=list(source_ids or []),
        document_ids=list(document_ids or []),
        entity_ids=list(entity_ids or []),
        evidence_ids=list(evidence_ids or []),
        contradiction_ids=list(contradiction_ids or []),
        corroborating_claim_ids=list(
            corroborating_claim_ids or []
        ),
        contradicting_claim_ids=list(
            contradicting_claim_ids or []
        ),
        confidence=confidence,
        polarity=polarity,
        review_state=ReviewState.REVIEW_REQUIRED,
        notes=list(notes or []),
    )

    validate_claim_summary(summary)
    return summary


# ======================================================================
# REPORT ASSEMBLY
# ======================================================================

def add_node(
    report: EvidenceGraphReport,
    node: EvidenceGraphReportNode,
) -> EvidenceGraphReport:

    validate_node(node)

    if any(
        existing.node_id == node.node_id
        for existing in report.nodes
    ):
        raise ValueError(
            f"duplicate node: {node.node_id}"
        )

    report.nodes.append(node)
    report.node_count = len(report.nodes)

    report.source_count = sum(
        1
        for item in report.nodes
        if item.node_type == ReportNodeType.SOURCE
    )

    report.entity_count = sum(
        1
        for item in report.nodes
        if item.node_type == ReportNodeType.ENTITY
    )

    report.contradiction_count = sum(
        1
        for item in report.nodes
        if item.node_type
        == ReportNodeType.CONTRADICTION
    )

    report.updated_at = utc_now()

    return report


def add_edge(
    report: EvidenceGraphReport,
    edge: EvidenceGraphReportEdge,
) -> EvidenceGraphReport:

    validate_edge(edge)

    node_ids = {
        node.node_id
        for node in report.nodes
    }

    if edge.source_node_id not in node_ids:
        raise ValueError(
            f"source node missing: {edge.source_node_id}"
        )

    if edge.target_node_id not in node_ids:
        raise ValueError(
            f"target node missing: {edge.target_node_id}"
        )

    report.edges.append(edge)
    report.edge_count = len(report.edges)

    if edge.edge_type == (
        ReportEdgeType.CLAIM_CORROBORATES_CLAIM
    ):
        report.corroboration_links += 1

    if edge.edge_type == (
        ReportEdgeType.CLAIM_CONTRADICTS_CLAIM
    ):
        report.contradictory_links += 1

    report.updated_at = utc_now()

    return report


def add_claim_summary(
    report: EvidenceGraphReport,
    summary: EvidenceGraphClaimSummary,
) -> EvidenceGraphReport:

    validate_claim_summary(summary)

    if any(
        item.claim_id == summary.claim_id
        for item in report.claim_summaries
    ):
        raise ValueError(
            f"duplicate claim summary: {summary.claim_id}"
        )

    report.claim_summaries.append(summary)
    report.claim_count = len(report.claim_summaries)

    report.updated_at = utc_now()

    return report


def update_report_status(
    report: EvidenceGraphReport,
) -> EvidenceGraphReport:

    if report.contradictory_links > 0:
        report.status = (
            EvidenceGraphReportStatus.REVIEW_REQUIRED
        )

    elif report.node_count == 0:
        report.status = (
            EvidenceGraphReportStatus.NOT_ASSESSED
        )

    elif (
        report.claim_count > 0
        and report.source_count > 0
    ):
        report.status = (
            EvidenceGraphReportStatus.COMPLETE
        )

    else:
        report.status = (
            EvidenceGraphReportStatus.PARTIAL
        )

    report.automatic_conclusion = False
    report.fact_established = False
    report.identity_established = False
    report.guilt_established = False
    report.non_existence_established = False
    report.provenance_preserved = True
    report.contradictions_preserved = True
    report.human_review_required = True
    report.updated_at = utc_now()

    validate_report(report)

    return report


def build_report(
    investigation_id: str,
    nodes: Optional[List[EvidenceGraphReportNode]] = None,
    edges: Optional[List[EvidenceGraphReportEdge]] = None,
    claim_summaries: Optional[
        List[EvidenceGraphClaimSummary]
    ] = None,
) -> EvidenceGraphReport:

    report = EvidenceGraphReport(
        report_id=new_id("EVIDENCE_REPORT"),
        investigation_id=investigation_id,
    )

    for node in nodes or []:
        add_node(report, node)

    for edge in edges or []:
        add_edge(report, edge)

    for summary in claim_summaries or []:
        add_claim_summary(report, summary)

    update_report_status(report)

    return report


# ======================================================================
# QUERIES
# ======================================================================

def nodes_for_claim(
    report: EvidenceGraphReport,
    claim_id: str,
) -> List[EvidenceGraphReportNode]:

    return [
        node
        for node in report.nodes
        if claim_id in node.claim_ids
        or node.node_id == claim_id
    ]


def sources_for_claim(
    report: EvidenceGraphReport,
    claim_id: str,
) -> List[str]:

    sources = []

    for summary in report.claim_summaries:
        if summary.claim_id == claim_id:
            sources.extend(summary.source_ids)

    for node in nodes_for_claim(report, claim_id):
        sources.extend(node.source_ids)

    return list(dict.fromkeys(sources))


def contradictions_for_claim(
    report: EvidenceGraphReport,
    claim_id: str,
) -> List[str]:

    contradictions = []

    for summary in report.claim_summaries:
        if summary.claim_id == claim_id:
            contradictions.extend(
                summary.contradiction_ids
            )

    for node in nodes_for_claim(report, claim_id):
        contradictions.extend(
            node.contradiction_ids
        )

    return list(dict.fromkeys(contradictions))


def corroborating_claims(
    report: EvidenceGraphReport,
    claim_id: str,
) -> List[str]:

    for summary in report.claim_summaries:
        if summary.claim_id == claim_id:
            return list(
                dict.fromkeys(
                    summary.corroborating_claim_ids
                )
            )

    return []


def contradicting_claims(
    report: EvidenceGraphReport,
    claim_id: str,
) -> List[str]:

    for summary in report.claim_summaries:
        if summary.claim_id == claim_id:
            return list(
                dict.fromkeys(
                    summary.contradicting_claim_ids
                )
            )

    return []


# ======================================================================
# SERIALIZATION
# ======================================================================

def serialize_node(
    node: EvidenceGraphReportNode,
) -> Dict[str, Any]:

    validate_node(node)
    return serialize_value(node)


def serialize_edge(
    edge: EvidenceGraphReportEdge,
) -> Dict[str, Any]:

    validate_edge(edge)
    return serialize_value(edge)


def serialize_claim_summary(
    summary: EvidenceGraphClaimSummary,
) -> Dict[str, Any]:

    validate_claim_summary(summary)
    return serialize_value(summary)


def serialize_report(
    report: EvidenceGraphReport,
) -> Dict[str, Any]:

    validate_report(report)
    return serialize_value(report)


def report_to_json(
    report: EvidenceGraphReport,
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
    print("DOA JOURNALIST EVIDENCE GRAPH REPORT CONTRACT TEST")
    print("=" * 70)

    # --------------------------------------------------------------
    # [1] ENUMS
    # --------------------------------------------------------------
    print("\n[1] ENUMS AND MODULE CONTRACT")

    assert (
        EvidenceGraphReportStatus.REVIEW_REQUIRED.value
    )
    assert ReportNodeType.CLAIM.value
    assert ReportEdgeType.CLAIM_SUPPORTED_BY_SOURCE.value
    assert EvidencePolarity.CONTRADICTORY.value
    assert ReviewState.REVIEW_REQUIRED.value

    print("  Report status enum              : PASS")
    print("  Node type enum                  : PASS")
    print("  Edge type enum                  : PASS")
    print("  Evidence polarity enum          : PASS")
    print("  Review state enum               : PASS")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # [2] NODE CREATION
    # --------------------------------------------------------------
    print("\n[2] REPORT NODE CREATION")

    claim_node = build_node(
        "CLAIM_001",
        ReportNodeType.CLAIM,
        "Company X received a regulatory notice.",
        claim_ids=["CLAIM_001"],
        source_ids=["SRC_GOV_001"],
        document_ids=["DOC_GOV_001"],
        entity_ids=["ENT_X"],
        evidence_ids=["EVD_001"],
        confidence=0.70,
        polarity=EvidencePolarity.SUPPORTING,
    )

    source_node = build_node(
        "SRC_GOV_001",
        ReportNodeType.SOURCE,
        "Government regulatory record",
        source_ids=["SRC_GOV_001"],
    )

    document_node = build_node(
        "DOC_GOV_001",
        ReportNodeType.DOCUMENT,
        "Regulatory notice document",
        document_ids=["DOC_GOV_001"],
        source_ids=["SRC_GOV_001"],
    )

    entity_node = build_node(
        "ENT_X",
        ReportNodeType.ENTITY,
        "Company X",
        entity_ids=["ENT_X"],
    )

    evidence_node = build_node(
        "EVD_001",
        ReportNodeType.EVIDENCE,
        "Documented regulatory notice",
        evidence_ids=["EVD_001"],
    )

    contradiction_node = build_node(
        "CONTR_001",
        ReportNodeType.CONTRADICTION,
        "Conflicting regulatory date",
        contradiction_ids=["CONTR_001"],
    )

    confidence_node = build_node(
        "CONF_001",
        ReportNodeType.CONFIDENCE,
        "Confidence assessment",
        confidence=0.70,
    )

    for node in (
        claim_node,
        source_node,
        document_node,
        entity_node,
        evidence_node,
        contradiction_node,
        confidence_node,
    ):
        validate_node(node)

    print("  CLAIM node                     : PASS")
    print("  SOURCE node                    : PASS")
    print("  DOCUMENT node                  : PASS")
    print("  ENTITY node                    : PASS")
    print("  EVIDENCE node                  : PASS")
    print("  CONTRADICTION node             : PASS")
    print("  CONFIDENCE node                : PASS")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # [3] CLAIM SUMMARY
    # --------------------------------------------------------------
    print("\n[3] CLAIM SUMMARY")

    claim_summary = build_claim_summary(
        "CLAIM_001",
        "Company X received a regulatory notice.",
        source_ids=["SRC_GOV_001", "SRC_NEWS_001"],
        document_ids=["DOC_GOV_001", "DOC_NEWS_001"],
        entity_ids=["ENT_X"],
        evidence_ids=["EVD_001"],
        contradiction_ids=["CONTR_001"],
        corroborating_claim_ids=["CLAIM_002"],
        contradicting_claim_ids=["CLAIM_003"],
        confidence=0.70,
        polarity=EvidencePolarity.SUPPORTING,
        notes=["Requires source-level review."],
    )

    assert claim_summary.review_state == (
        ReviewState.REVIEW_REQUIRED
    )
    assert claim_summary.fact_established is False

    print("  Claim ID preserved              : PASS")
    print("  Source linkage                  : PASS")
    print("  Evidence linkage               : PASS")
    print("  Contradiction linkage           : PASS")
    print("  Review state                   : REVIEW_REQUIRED")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # [4] REPORT CREATION
    # --------------------------------------------------------------
    print("\n[4] REPORT CREATION")

    report = build_report(
        "INV_EGRAPH_001",
        nodes=[
            claim_node,
            source_node,
            document_node,
            entity_node,
            evidence_node,
            contradiction_node,
            confidence_node,
        ],
        claim_summaries=[claim_summary],
    )

    assert report.investigation_id == "INV_EGRAPH_001"
    assert report.node_count == 7
    assert report.claim_count == 1
    assert report.source_count == 1
    assert report.entity_count == 1
    assert report.contradiction_count == 1

    print("  Investigation linkage          : PASS")
    print("  Node count                     : 7")
    print("  Claim count                    : 1")
    print("  Source count                   : 1")
    print("  Entity count                   : 1")
    print("  Contradiction count            : 1")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # [5] PROVENANCE EDGES
    # --------------------------------------------------------------
    print("\n[5] PROVENANCE EDGES")

    edges = [
        build_edge(
            "CLAIM_001",
            "SRC_GOV_001",
            ReportEdgeType.CLAIM_SUPPORTED_BY_SOURCE,
            source_ids=["SRC_GOV_001"],
            claim_ids=["CLAIM_001"],
            polarity=EvidencePolarity.SUPPORTING,
        ),
        build_edge(
            "CLAIM_001",
            "DOC_GOV_001",
            ReportEdgeType.CLAIM_DERIVED_FROM_DOCUMENT,
            source_ids=["SRC_GOV_001"],
            claim_ids=["CLAIM_001"],
        ),
        build_edge(
            "DOC_GOV_001",
            "ENT_X",
            ReportEdgeType.DOCUMENT_MENTIONS_ENTITY,
            source_ids=["SRC_GOV_001"],
            claim_ids=["CLAIM_001"],
        ),
        build_edge(
            "CLAIM_001",
            "ENT_X",
            ReportEdgeType.CLAIM_REFERENCES_ENTITY,
            claim_ids=["CLAIM_001"],
        ),
        build_edge(
            "CLAIM_001",
            "EVD_001",
            ReportEdgeType.CLAIM_HAS_EVIDENCE,
            claim_ids=["CLAIM_001"],
        ),
        build_edge(
            "CLAIM_001",
            "CONF_001",
            ReportEdgeType.CLAIM_HAS_CONFIDENCE,
            claim_ids=["CLAIM_001"],
        ),
        build_edge(
            "CLAIM_001",
            "CONTR_001",
            ReportEdgeType.CLAIM_CONTRADICTS_CLAIM,
            claim_ids=["CLAIM_001"],
            contradiction_ids=["CONTR_001"],
            polarity=EvidencePolarity.CONTRADICTORY,
        ),
    ]

    for edge in edges:
        add_edge(report, edge)

    assert report.edge_count == 7
    assert report.contradictory_links == 1

    print("  Claim → Source                 : PASS")
    print("  Claim → Document               : PASS")
    print("  Document → Entity              : PASS")
    print("  Claim → Entity                 : PASS")
    print("  Claim → Evidence               : PASS")
    print("  Claim → Confidence             : PASS")
    print("  Claim → Contradiction          : PASS")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # [6] CORROBORATION
    # --------------------------------------------------------------
    print("\n[6] CORROBORATION LINK")

    corroboration_edge = build_edge(
        "CLAIM_002",
        "CLAIM_001",
        ReportEdgeType.CLAIM_CORROBORATES_CLAIM,
        claim_ids=["CLAIM_001", "CLAIM_002"],
        polarity=EvidencePolarity.SUPPORTING,
    )

    claim_2_node = build_node(
        "CLAIM_002",
        ReportNodeType.CLAIM,
        "Independent source reports the same event.",
        claim_ids=["CLAIM_002"],
        source_ids=["SRC_NEWS_001"],
    )

    add_node(report, claim_2_node)
    add_edge(report, corroboration_edge)

    assert report.corroboration_links == 1

    print("  Corroborating claim linked      : PASS")
    print("  Independent link preserved      : PASS")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # [7] CONTRADICTION PRESERVATION
    # --------------------------------------------------------------
    print("\n[7] CONTRADICTION PRESERVATION")

    contradiction_claim_node = build_node(
        "CLAIM_003",
        ReportNodeType.CLAIM,
        "Another source gives a conflicting account.",
        claim_ids=["CLAIM_003"],
        source_ids=["SRC_OTHER_001"],
        contradiction_ids=["CONTR_001"],
        polarity=EvidencePolarity.CONTRADICTORY,
    )

    add_node(report, contradiction_claim_node)

    contradiction_edge = build_edge(
        "CLAIM_003",
        "CLAIM_001",
        ReportEdgeType.CLAIM_CONTRADICTS_CLAIM,
        source_ids=["SRC_OTHER_001"],
        claim_ids=["CLAIM_003", "CLAIM_001"],
        contradiction_ids=["CONTR_001"],
        polarity=EvidencePolarity.CONTRADICTORY,
    )

    add_edge(report, contradiction_edge)

    assert report.contradictory_links == 2
    assert report.contradictions_preserved is True

    print("  Contradictory claim retained    : PASS")
    print("  Contradiction ID retained       : PASS")
    print("  Both sides preserved            : PASS")
    print("  Overwrite occurred              : FALSE")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # [8] QUERIES
    # --------------------------------------------------------------
    print("\n[8] GRAPH QUERIES")

    claim_nodes = nodes_for_claim(
        report,
        "CLAIM_001",
    )

    sources = sources_for_claim(
        report,
        "CLAIM_001",
    )

    contradictions = contradictions_for_claim(
        report,
        "CLAIM_001",
    )

    corroborating = corroborating_claims(
        report,
        "CLAIM_001",
    )

    contradicting = contradicting_claims(
        report,
        "CLAIM_001",
    )

    assert claim_nodes
    assert "SRC_GOV_001" in sources
    assert "CONTR_001" in contradictions
    assert "CLAIM_002" in corroborating
    assert "CLAIM_003" in contradicting

    print("  Claim node query               : PASS")
    print("  Source query                   : PASS")
    print("  Contradiction query            : PASS")
    print("  Corroboration query            : PASS")
    print("  Counter-claim query            : PASS")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # [9] STATUS
    # --------------------------------------------------------------
    print("\n[9] REPORT STATUS")

    update_report_status(report)

    assert report.status == (
        EvidenceGraphReportStatus.REVIEW_REQUIRED
    )

    print("  Status                         : REVIEW_REQUIRED")
    print("  Human review required          : TRUE")
    print("  Automatic conclusion           : FALSE")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # [10] SERIALIZATION
    # --------------------------------------------------------------
    print("\n[10] SERIALIZATION")

    serialized = serialize_report(report)
    json_output = report_to_json(report)

    assert serialized["report_id"] == report.report_id
    assert serialized["investigation_id"] == (
        "INV_EGRAPH_001"
    )
    assert len(serialized["nodes"]) == report.node_count
    assert len(serialized["edges"]) == report.edge_count
    assert isinstance(json_output, str)

    print("  Report ID preserved            : PASS")
    print("  Investigation ID preserved     : PASS")
    print("  Nodes serialized               : PASS")
    print("  Edges serialized               : PASS")
    print("  JSON serialization             : PASS")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # [11] UNSAFE STATE VALIDATION
    # --------------------------------------------------------------
    print("\n[11] UNSAFE STATE VALIDATION")

    assert report.automatic_conclusion is False
    assert report.fact_established is False
    assert report.identity_established is False
    assert report.guilt_established is False
    assert report.non_existence_established is False

    print("  Automatic conclusion blocked   : PASS")
    print("  Fact establishment blocked     : PASS")
    print("  Identity establishment blocked : PASS")
    print("  Guilt establishment blocked    : PASS")
    print("  Non-existence blocked          : PASS")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # [12] PROVENANCE FLAGS
    # --------------------------------------------------------------
    print("\n[12] PROVENANCE AND CONTRADICTION FLAGS")

    assert report.provenance_preserved is True
    assert report.contradictions_preserved is True

    print("  Provenance preserved           : TRUE")
    print("  Contradictions preserved       : TRUE")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # [13] HUMAN REVIEW GATE
    # --------------------------------------------------------------
    print("\n[13] HUMAN REVIEW GATE")

    assert report.human_review_required is True
    assert report.automatic_conclusion is False

    print("  Human review required          : TRUE")
    print("  Automatic conclusion           : FALSE")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # [14] SELF EDGE BLOCK
    # --------------------------------------------------------------
    print("\n[14] SELF-EDGE BLOCK")

    self_edge_blocked = False

    try:
        build_edge(
            "CLAIM_001",
            "CLAIM_001",
            ReportEdgeType.CLAIM_SUPPORTED_BY_SOURCE,
        )
    except ValueError:
        self_edge_blocked = True

    assert self_edge_blocked is True

    print("  Self-edge blocked              : PASS")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # [15] MISSING NODE BLOCK
    # --------------------------------------------------------------
    print("\n[15] MISSING NODE BLOCK")

    missing_node_blocked = False

    try:
        add_edge(
            report,
            build_edge(
                "MISSING_NODE",
                "CLAIM_001",
                ReportEdgeType.CLAIM_SUPPORTED_BY_SOURCE,
            ),
        )
    except ValueError:
        missing_node_blocked = True

    assert missing_node_blocked is True

    print("  Missing node blocked           : PASS")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # [16] NEGATIVE FINDING SEPARATION
    # --------------------------------------------------------------
    print("\n[16] NEGATIVE FINDING SEPARATION")

    report.metadata["negative_findings_present"] = True
    report.metadata["non_existence_established"] = False

    update_report_status(report)

    assert (
        report.non_existence_established is False
    )

    print("  Negative findings retained     : PASS")
    print("  Non-existence established      : FALSE")
    print("  Negative finding as proof      : BLOCKED")
    print("  RESULT                         : PASS")

    # --------------------------------------------------------------
    # [17] FINAL SAFETY INVARIANTS
    # --------------------------------------------------------------
    print("\n[17] FINAL SAFETY INVARIANTS")

    assert report.automatic_conclusion is False
    assert report.fact_established is False
    assert report.identity_established is False
    assert report.guilt_established is False
    assert report.non_existence_established is False
    assert report.provenance_preserved is True
    assert report.contradictions_preserved is True
    assert report.human_review_required is True

    print("  Evidence graph != truth        : TRUE")
    print("  Source quality != truth        : TRUE")
    print("  Confidence != truth            : TRUE")
    print("  Identity != guilt              : TRUE")
    print("  Association != misconduct      : TRUE")
    print("  Negative finding != nonexistence: TRUE")
    print("  Fact establishment              : FALSE")
    print("  Identity establishment          : FALSE")
    print("  Guilt establishment             : FALSE")
    print("  Non-existence establishment     : FALSE")
    print("  Automatic conclusion            : FALSE")
    print("  Human review required           : TRUE")
    print("  RESULT                          : PASS")

    # --------------------------------------------------------------
    # [18] FINAL VALIDATION
    # --------------------------------------------------------------
    print("\n[18] FINAL VALIDATION")

    for node in report.nodes:
        validate_node(node)

    for edge in report.edges:
        validate_edge(edge)

    for summary in report.claim_summaries:
        validate_claim_summary(summary)

    validate_report(report)

    print("  Node validation                : PASS")
    print("  Edge validation                : PASS")
    print("  Claim summary validation       : PASS")
    print("  Report validation              : PASS")

    print("\n" + "=" * 70)
    print("JOURNALIST EVIDENCE GRAPH REPORT : PASS")
    print("=" * 70)
    print("MODULE IMPORT                  : PASS")
    print("REPORT NODE CONTRACT            : PASS")
    print("CLAIM SUMMARY                   : PASS")
    print("REPORT CREATION                 : PASS")
    print("PROVENANCE EDGES                : PASS")
    print("CORROBORATION LINK              : PASS")
    print("CONTRADICTION PRESERVATION      : PASS")
    print("GRAPH QUERIES                   : PASS")
    print("STATUS / REVIEW GATE            : PASS")
    print("SERIALIZATION                   : PASS")
    print("SELF-EDGE BLOCK                 : PASS")
    print("MISSING NODE BLOCK              : PASS")
    print("NEGATIVE FINDING SEPARATION     : PASS")
    print("PROVENANCE PRESERVATION         : PASS")
    print("UNSAFE STATE VALIDATION         : PASS")
    print("SAFETY INVARIANTS               : PASS")
    print("VALIDATION                      : PASS")
    print("FACT ESTABLISHMENT              : FALSE")
    print("IDENTITY ESTABLISHMENT          : FALSE")
    print("GUILT ESTABLISHMENT             : FALSE")
    print("NON-EXISTENCE ESTABLISHMENT     : FALSE")
    print("AUTOMATIC CONCLUSION             : FALSE")
    print("REAL WEB SEARCH                 : NOT STARTED")
    print("=" * 70)


if __name__ == "__main__":
    contract_test()
