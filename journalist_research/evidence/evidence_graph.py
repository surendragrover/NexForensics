
"""
Deep OSINT Agent (DOA)
Evidence Graph

Purpose
-------
Build a provenance-preserving graph connecting:

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

The graph is an evidence structure, not a truth oracle.

Core invariants
---------------
1. Graph structure does not establish facts.
2. Graph structure does not establish guilt.
3. Graph structure does not establish identity.
4. Provenance is preserved.
5. Contradictory evidence is retained.
6. Claims may remain unresolved.
7. Missing evidence remains visible.
8. Confidence is an investigative state, not proof.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4


# ============================================================
# ENUMS
# ============================================================

class EvidenceNodeType(str, Enum):
    CLAIM = "CLAIM"
    SOURCE = "SOURCE"
    DOCUMENT = "DOCUMENT"
    ENTITY = "ENTITY"
    EVIDENCE = "EVIDENCE"
    CONTRADICTION = "CONTRADICTION"
    CONFIDENCE = "CONFIDENCE"
    INVESTIGATION = "INVESTIGATION"


class EvidenceEdgeType(str, Enum):
    CLAIM_SUPPORTED_BY_SOURCE = "CLAIM_SUPPORTED_BY_SOURCE"
    CLAIM_DERIVED_FROM_DOCUMENT = "CLAIM_DERIVED_FROM_DOCUMENT"
    CLAIM_REFERENCES_ENTITY = "CLAIM_REFERENCES_ENTITY"
    SOURCE_CONTAINS_DOCUMENT = "SOURCE_CONTAINS_DOCUMENT"
    SOURCE_SUPPORTS_CLAIM = "SOURCE_SUPPORTS_CLAIM"
    DOCUMENT_MENTIONS_ENTITY = "DOCUMENT_MENTIONS_ENTITY"
    DOCUMENT_CONTAINS_CLAIM = "DOCUMENT_CONTAINS_CLAIM"
    ENTITY_RELATED_TO_CLAIM = "ENTITY_RELATED_TO_CLAIM"
    CLAIM_CORROBORATES_CLAIM = "CLAIM_CORROBORATES_CLAIM"
    CLAIM_CONTRADICTS_CLAIM = "CLAIM_CONTRADICTS_CLAIM"
    CLAIM_HAS_EVIDENCE = "CLAIM_HAS_EVIDENCE"
    EVIDENCE_SUPPORTS_CLAIM = "EVIDENCE_SUPPORTS_CLAIM"
    EVIDENCE_CONTRADICTS_CLAIM = "EVIDENCE_CONTRADICTS_CLAIM"
    CONTRADICTION_LINKS_CLAIM = "CONTRADICTION_LINKS_CLAIM"
    CLAIM_HAS_CONFIDENCE = "CLAIM_HAS_CONFIDENCE"
    INVESTIGATION_CONTAINS_CLAIM = "INVESTIGATION_CONTAINS_CLAIM"
    INVESTIGATION_CONTAINS_SOURCE = "INVESTIGATION_CONTAINS_SOURCE"
    INVESTIGATION_CONTAINS_ENTITY = "INVESTIGATION_CONTAINS_ENTITY"


class EvidenceGraphStatus(str, Enum):
    EMPTY = "EMPTY"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class EvidencePolarity(str, Enum):
    SUPPORTING = "SUPPORTING"
    CONTRADICTORY = "CONTRADICTORY"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


# ============================================================
# DATACLASSES
# ============================================================

@dataclass
class EvidenceNode:
    node_id: str
    node_type: EvidenceNodeType
    label: str
    source_ids: List[str] = field(default_factory=list)
    claim_ids: List[str] = field(default_factory=list)
    entity_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceEdge:
    edge_id: str
    source_node_id: str
    target_node_id: str
    edge_type: EvidenceEdgeType
    polarity: EvidencePolarity = EvidencePolarity.UNKNOWN
    provenance_ids: List[str] = field(default_factory=list)
    claim_ids: List[str] = field(default_factory=list)
    source_ids: List[str] = field(default_factory=list)
    notes: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceGraph:
    graph_id: str
    investigation_id: Optional[str] = None
    nodes: Dict[str, EvidenceNode] = field(default_factory=dict)
    edges: Dict[str, EvidenceEdge] = field(default_factory=dict)
    status: EvidenceGraphStatus = EvidenceGraphStatus.EMPTY
    metadata: Dict[str, Any] = field(default_factory=dict)

    fact_established: bool = False
    guilt_established: bool = False
    identity_established: bool = False


# ============================================================
# HELPERS
# ============================================================

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


# ============================================================
# VALIDATION
# ============================================================

def validate_node(node: EvidenceNode) -> List[str]:
    errors = []

    if not node.node_id:
        errors.append("node_id is required.")

    if not isinstance(node.node_type, EvidenceNodeType):
        errors.append("node_type must be EvidenceNodeType.")

    if not node.label:
        errors.append("label is required.")

    return errors


def validate_edge(edge: EvidenceEdge) -> List[str]:
    errors = []

    if not edge.edge_id:
        errors.append("edge_id is required.")

    if not edge.source_node_id:
        errors.append("source_node_id is required.")

    if not edge.target_node_id:
        errors.append("target_node_id is required.")

    if edge.source_node_id == edge.target_node_id:
        errors.append(
            "Self-referential evidence edges are not allowed."
        )

    if not isinstance(edge.edge_type, EvidenceEdgeType):
        errors.append(
            "edge_type must be EvidenceEdgeType."
        )

    return errors


def validate_graph(graph: EvidenceGraph) -> List[str]:
    errors = []

    if not graph.graph_id:
        errors.append("graph_id is required.")

    for node in graph.nodes.values():
        errors.extend(validate_node(node))

    for edge in graph.edges.values():

        errors.extend(validate_edge(edge))

        if edge.source_node_id not in graph.nodes:
            errors.append(
                f"Edge {edge.edge_id} references missing "
                f"source node {edge.source_node_id}."
            )

        if edge.target_node_id not in graph.nodes:
            errors.append(
                f"Edge {edge.edge_id} references missing "
                f"target node {edge.target_node_id}."
            )

    if graph.fact_established:
        errors.append(
            "Evidence graph cannot establish facts."
        )

    if graph.guilt_established:
        errors.append(
            "Evidence graph cannot establish guilt."
        )

    if graph.identity_established:
        errors.append(
            "Evidence graph cannot establish identity."
        )

    return errors


# ============================================================
# BUILDERS
# ============================================================

def build_node(
    node_type: EvidenceNodeType,
    label: str,
    *,
    node_id: Optional[str] = None,
    source_ids: Optional[Iterable[str]] = None,
    claim_ids: Optional[Iterable[str]] = None,
    entity_ids: Optional[Iterable[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> EvidenceNode:

    node = EvidenceNode(
        node_id=node_id or new_id(node_type.value),
        node_type=node_type,
        label=label,
        source_ids=list(source_ids or []),
        claim_ids=list(claim_ids or []),
        entity_ids=list(entity_ids or []),
        metadata=dict(metadata or {}),
    )

    errors = validate_node(node)

    if errors:
        raise ValueError("; ".join(errors))

    return node


def build_edge(
    source_node_id: str,
    target_node_id: str,
    edge_type: EvidenceEdgeType,
    *,
    polarity: EvidencePolarity = EvidencePolarity.UNKNOWN,
    provenance_ids: Optional[Iterable[str]] = None,
    claim_ids: Optional[Iterable[str]] = None,
    source_ids: Optional[Iterable[str]] = None,
    notes: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> EvidenceEdge:

    edge = EvidenceEdge(
        edge_id=new_id("EDGE"),
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        edge_type=edge_type,
        polarity=polarity,
        provenance_ids=list(provenance_ids or []),
        claim_ids=list(claim_ids or []),
        source_ids=list(source_ids or []),
        notes=notes,
        metadata=dict(metadata or {}),
    )

    errors = validate_edge(edge)

    if errors:
        raise ValueError("; ".join(errors))

    return edge


# ============================================================
# GRAPH OPERATIONS
# ============================================================

def create_graph(
    investigation_id: Optional[str] = None,
) -> EvidenceGraph:

    return EvidenceGraph(
        graph_id=new_id("EGRAPH"),
        investigation_id=investigation_id,
        status=EvidenceGraphStatus.EMPTY,
        metadata={
            "provenance_preserved": True,
            "contradictions_preserved": True,
            "automatic_truth_decision": False,
            "human_review_required_for_resolution": True,
        },
        fact_established=False,
        guilt_established=False,
        identity_established=False,
    )


def add_node(
    graph: EvidenceGraph,
    node: EvidenceNode,
) -> str:

    if node.node_id in graph.nodes:
        raise ValueError(
            f"Node already exists: {node.node_id}"
        )

    graph.nodes[node.node_id] = node

    if graph.status == EvidenceGraphStatus.EMPTY:
        graph.status = EvidenceGraphStatus.PARTIAL

    return node.node_id


def add_edge(
    graph: EvidenceGraph,
    edge: EvidenceEdge,
) -> str:

    if edge.edge_id in graph.edges:
        raise ValueError(
            f"Edge already exists: {edge.edge_id}"
        )

    if edge.source_node_id not in graph.nodes:
        raise ValueError(
            f"Missing source node: {edge.source_node_id}"
        )

    if edge.target_node_id not in graph.nodes:
        raise ValueError(
            f"Missing target node: {edge.target_node_id}"
        )

    graph.edges[edge.edge_id] = edge

    return edge.edge_id


# ============================================================
# QUERY OPERATIONS
# ============================================================

def outgoing_edges(
    graph: EvidenceGraph,
    node_id: str,
) -> List[EvidenceEdge]:

    return [
        edge
        for edge in graph.edges.values()
        if edge.source_node_id == node_id
    ]


def incoming_edges(
    graph: EvidenceGraph,
    node_id: str,
) -> List[EvidenceEdge]:

    return [
        edge
        for edge in graph.edges.values()
        if edge.target_node_id == node_id
    ]


def neighbors(
    graph: EvidenceGraph,
    node_id: str,
) -> List[EvidenceNode]:

    result = []

    for edge in graph.edges.values():

        if edge.source_node_id == node_id:
            result.append(
                graph.nodes[edge.target_node_id]
            )

        elif edge.target_node_id == node_id:
            result.append(
                graph.nodes[edge.source_node_id]
            )

    seen = set()
    unique = []

    for node in result:

        if node.node_id in seen:
            continue

        seen.add(node.node_id)
        unique.append(node)

    return unique


def edges_by_claim(
    graph: EvidenceGraph,
    claim_id: str,
) -> List[EvidenceEdge]:

    return [
        edge
        for edge in graph.edges.values()
        if claim_id in edge.claim_ids
    ]


def contradictions_for_claim(
    graph: EvidenceGraph,
    claim_node_id: str,
) -> List[EvidenceNode]:

    result = []

    for edge in graph.edges.values():

        if (
            edge.edge_type
            != EvidenceEdgeType.CONTRADICTION_LINKS_CLAIM
        ):
            continue

        if (
            edge.source_node_id == claim_node_id
            or edge.target_node_id == claim_node_id
        ):

            other_id = (
                edge.target_node_id
                if edge.source_node_id == claim_node_id
                else edge.source_node_id
            )

            if other_id in graph.nodes:

                node = graph.nodes[other_id]

                if node.node_type == (
                    EvidenceNodeType.CONTRADICTION
                ):
                    result.append(node)

    return result


# ============================================================
# RELATIONSHIP HELPERS
# ============================================================

def link_corroborating_claims(
    graph: EvidenceGraph,
    claim_a_node_id: str,
    claim_b_node_id: str,
    *,
    source_ids: Optional[List[str]] = None,
) -> str:

    edge = build_edge(
        claim_a_node_id,
        claim_b_node_id,
        EvidenceEdgeType.CLAIM_CORROBORATES_CLAIM,
        polarity=EvidencePolarity.SUPPORTING,
        claim_ids=[
            claim_a_node_id,
            claim_b_node_id,
        ],
        source_ids=source_ids,
    )

    return add_edge(graph, edge)


def link_contradiction(
    graph: EvidenceGraph,
    contradiction_node_id: str,
    claim_node_id: str,
    *,
    source_ids: Optional[List[str]] = None,
) -> str:

    edge = build_edge(
        contradiction_node_id,
        claim_node_id,
        EvidenceEdgeType.CONTRADICTION_LINKS_CLAIM,
        polarity=EvidencePolarity.CONTRADICTORY,
        claim_ids=[claim_node_id],
        source_ids=source_ids,
    )

    return add_edge(graph, edge)


# ============================================================
# STATUS
# ============================================================

def update_graph_status(
    graph: EvidenceGraph,
) -> EvidenceGraphStatus:

    has_claim = any(
        node.node_type == EvidenceNodeType.CLAIM
        for node in graph.nodes.values()
    )

    has_source = any(
        node.node_type == EvidenceNodeType.SOURCE
        for node in graph.nodes.values()
    )

    has_document = any(
        node.node_type == EvidenceNodeType.DOCUMENT
        for node in graph.nodes.values()
    )

    if not graph.nodes:
        graph.status = EvidenceGraphStatus.EMPTY

    elif has_claim and has_source and has_document:
        graph.status = EvidenceGraphStatus.COMPLETE

    else:
        graph.status = EvidenceGraphStatus.PARTIAL

    return graph.status


# ============================================================
# SUMMARY
# ============================================================

def graph_summary(
    graph: EvidenceGraph,
) -> Dict[str, Any]:

    node_counts: Dict[str, int] = {}

    for node in graph.nodes.values():

        key = node.node_type.value
        node_counts[key] = (
            node_counts.get(key, 0) + 1
        )

    edge_counts: Dict[str, int] = {}

    for edge in graph.edges.values():

        key = edge.edge_type.value
        edge_counts[key] = (
            edge_counts.get(key, 0) + 1
        )

    return {
        "graph_id": graph.graph_id,
        "investigation_id": graph.investigation_id,
        "status": graph.status.value,
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "node_counts": node_counts,
        "edge_counts": edge_counts,
        "provenance_preserved": graph.metadata.get(
            "provenance_preserved", False
        ),
        "contradictions_preserved": graph.metadata.get(
            "contradictions_preserved", False
        ),
        "fact_established": False,
        "guilt_established": False,
        "identity_established": False,
        "automatic_truth_decision": False,
    }


# ============================================================
# SERIALIZATION
# ============================================================

def serialize_node(
    node: EvidenceNode,
) -> Dict[str, Any]:

    return {
        "node_id": node.node_id,
        "node_type": node.node_type.value,
        "label": node.label,
        "source_ids": list(node.source_ids),
        "claim_ids": list(node.claim_ids),
        "entity_ids": list(node.entity_ids),
        "metadata": dict(node.metadata),
    }


def serialize_edge(
    edge: EvidenceEdge,
) -> Dict[str, Any]:

    return {
        "edge_id": edge.edge_id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "edge_type": edge.edge_type.value,
        "polarity": edge.polarity.value,
        "provenance_ids": list(edge.provenance_ids),
        "claim_ids": list(edge.claim_ids),
        "source_ids": list(edge.source_ids),
        "notes": edge.notes,
        "metadata": dict(edge.metadata),
    }


def serialize_graph(
    graph: EvidenceGraph,
) -> Dict[str, Any]:

    return {
        "graph_id": graph.graph_id,
        "investigation_id": graph.investigation_id,
        "status": graph.status.value,
        "nodes": [
            serialize_node(node)
            for node in graph.nodes.values()
        ],
        "edges": [
            serialize_edge(edge)
            for edge in graph.edges.values()
        ],
        "metadata": dict(graph.metadata),
        "fact_established": False,
        "guilt_established": False,
        "identity_established": False,
    }


# ============================================================
# PUBLIC API
# ============================================================

__all__ = [
    "EvidenceNodeType",
    "EvidenceEdgeType",
    "EvidenceGraphStatus",
    "EvidencePolarity",
    "EvidenceNode",
    "EvidenceEdge",
    "EvidenceGraph",
    "new_id",
    "validate_node",
    "validate_edge",
    "validate_graph",
    "build_node",
    "build_edge",
    "create_graph",
    "add_node",
    "add_edge",
    "outgoing_edges",
    "incoming_edges",
    "neighbors",
    "edges_by_claim",
    "contradictions_for_claim",
    "link_corroborating_claims",
    "link_contradiction",
    "update_graph_status",
    "graph_summary",
    "serialize_node",
    "serialize_edge",
    "serialize_graph",
]
