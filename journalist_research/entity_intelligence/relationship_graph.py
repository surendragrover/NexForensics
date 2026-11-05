
"""
Deep OSINT Agent (DOA)
Relationship Graph

Purpose
-------
Build a provenance-preserving graph of relationships between
resolved entities.

Critical distinction:

    RELATIONSHIP != IDENTITY
    RELATIONSHIP != GUILT
    ASSOCIATION != MISCONDUCT

A graph edge records that available evidence/claims describe
a relationship. It does not establish why the relationship
exists or whether either party committed wrongdoing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4


# ============================================================
# ENUMS
# ============================================================

class RelationshipStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    ALLEGED = "ALLEGED"
    REPORTED = "REPORTED"
    CORROBORATED = "CORROBORATED"
    CONTRADICTED = "CONTRADICTED"
    ESTABLISHED = "ESTABLISHED"


class RelationshipDirection(str, Enum):
    DIRECTED = "DIRECTED"
    UNDIRECTED = "UNDIRECTED"


class RelationshipConfidence(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class RelationshipType(str, Enum):
    EMPLOYMENT = "EMPLOYMENT"
    OWNERSHIP = "OWNERSHIP"
    DIRECTORSHIP = "DIRECTORSHIP"
    PARTNERSHIP = "PARTNERSHIP"
    BUSINESS = "BUSINESS"
    FAMILY = "FAMILY"
    PROFESSIONAL = "PROFESSIONAL"
    FINANCIAL = "FINANCIAL"
    LEGAL = "LEGAL"
    CORPORATE = "CORPORATE"
    COMMUNICATION = "COMMUNICATION"
    ASSOCIATION = "ASSOCIATION"
    LOCATION = "LOCATION"
    DOMAIN = "DOMAIN"
    OTHER = "OTHER"


# ============================================================
# RELATIONSHIP SIGNAL
# ============================================================

@dataclass
class RelationshipSignal:
    """
    One source-backed signal supporting or challenging a
    relationship.
    """

    signal_id: str

    relationship_id: str

    source_ids: List[str] = field(
        default_factory=list
    )

    claim_ids: List[str] = field(
        default_factory=list
    )

    description: str = ""

    supports: bool = True

    independent: bool = False

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )


# ============================================================
# RELATIONSHIP EDGE
# ============================================================

@dataclass
class RelationshipEdge:
    """
    Graph edge between two entities.

    The edge itself never establishes guilt or misconduct.
    """

    relationship_id: str

    source_entity_id: str

    target_entity_id: str

    relationship_type: RelationshipType

    direction: RelationshipDirection = (
        RelationshipDirection.DIRECTED
    )

    status: RelationshipStatus = (
        RelationshipStatus.UNKNOWN
    )

    confidence: RelationshipConfidence = (
        RelationshipConfidence.NOT_ASSESSED
    )

    claim_ids: List[str] = field(
        default_factory=list
    )

    source_ids: List[str] = field(
        default_factory=list
    )

    signal_ids: List[str] = field(
        default_factory=list
    )

    first_seen_at: Optional[str] = None

    last_seen_at: Optional[str] = None

    description: str = ""

    contradiction_ids: List[str] = field(
        default_factory=list
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    identity_established: bool = False

    guilt_established: bool = False

    misconduct_established: bool = False


# ============================================================
# GRAPH
# ============================================================

@dataclass
class RelationshipGraph:
    """
    Complete entity relationship graph.
    """

    graph_id: str

    entity_ids: List[str] = field(
        default_factory=list
    )

    relationships: List[RelationshipEdge] = field(
        default_factory=list
    )

    signals: List[RelationshipSignal] = field(
        default_factory=list
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )


# ============================================================
# HELPERS
# ============================================================

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def validate_relationship(
    relationship: RelationshipEdge,
) -> List[str]:

    errors = []

    if not relationship.relationship_id:
        errors.append(
            "relationship_id is required."
        )

    if not relationship.source_entity_id:
        errors.append(
            "source_entity_id is required."
        )

    if not relationship.target_entity_id:
        errors.append(
            "target_entity_id is required."
        )

    if (
        relationship.source_entity_id
        == relationship.target_entity_id
    ):
        errors.append(
            "Self-referential relationship is not allowed."
        )

    if relationship.identity_established:
        errors.append(
            "Relationship graph cannot establish identity."
        )

    if relationship.guilt_established:
        errors.append(
            "Relationship graph cannot establish guilt."
        )

    if relationship.misconduct_established:
        errors.append(
            "Relationship graph cannot establish misconduct."
        )

    return errors


def validate_signal(
    signal: RelationshipSignal,
) -> List[str]:

    errors = []

    if not signal.signal_id:
        errors.append(
            "signal_id is required."
        )

    if not signal.relationship_id:
        errors.append(
            "relationship_id is required."
        )

    if (
        not signal.source_ids
        and not signal.claim_ids
    ):
        errors.append(
            "Signal requires source_ids or claim_ids."
        )

    return errors


def validate_graph(
    graph: RelationshipGraph,
) -> List[str]:

    errors = []

    if not graph.graph_id:
        errors.append(
            "graph_id is required."
        )

    entity_set = set(
        graph.entity_ids
    )

    for relationship in graph.relationships:

        errors.extend(
            validate_relationship(
                relationship
            )
        )

        if (
            relationship.source_entity_id
            not in entity_set
        ):
            errors.append(
                f"Unknown source entity: "
                f"{relationship.source_entity_id}"
            )

        if (
            relationship.target_entity_id
            not in entity_set
        ):
            errors.append(
                f"Unknown target entity: "
                f"{relationship.target_entity_id}"
            )

    relationship_ids = {
        relationship.relationship_id
        for relationship in graph.relationships
    }

    for signal in graph.signals:

        errors.extend(
            validate_signal(
                signal
            )
        )

        if (
            signal.relationship_id
            not in relationship_ids
        ):
            errors.append(
                f"Signal references unknown relationship: "
                f"{signal.relationship_id}"
            )

    return errors


# ============================================================
# BUILD RELATIONSHIP
# ============================================================

def build_relationship(
    source_entity_id: str,
    target_entity_id: str,
    relationship_type: RelationshipType,
    *,
    direction: RelationshipDirection = (
        RelationshipDirection.DIRECTED
    ),
    status: RelationshipStatus = (
        RelationshipStatus.UNKNOWN
    ),
    confidence: RelationshipConfidence = (
        RelationshipConfidence.NOT_ASSESSED
    ),
    claim_ids: Optional[List[str]] = None,
    source_ids: Optional[List[str]] = None,
    description: str = "",
    first_seen_at: Optional[str] = None,
    last_seen_at: Optional[str] = None,
) -> RelationshipEdge:

    relationship = RelationshipEdge(
        relationship_id=new_id("REL"),
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        relationship_type=relationship_type,
        direction=direction,
        status=status,
        confidence=confidence,
        claim_ids=list(
            claim_ids or []
        ),
        source_ids=list(
            source_ids or []
        ),
        description=description,
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
        metadata={
            "relationship_fact_established": False,
            "association_is_not_guilt": True,
            "identity_is_independent": True,
        },
        identity_established=False,
        guilt_established=False,
        misconduct_established=False,
    )

    errors = validate_relationship(
        relationship
    )

    if errors:
        raise ValueError(
            "; ".join(errors)
        )

    return relationship


# ============================================================
# SIGNAL ATTACHMENT
# ============================================================

def add_relationship_signal(
    relationship: RelationshipEdge,
    *,
    source_ids: Optional[List[str]] = None,
    claim_ids: Optional[List[str]] = None,
    description: str = "",
    supports: bool = True,
    independent: bool = False,
) -> RelationshipSignal:

    signal = RelationshipSignal(
        signal_id=new_id("SIGNAL"),
        relationship_id=(
            relationship.relationship_id
        ),
        source_ids=list(
            source_ids or []
        ),
        claim_ids=list(
            claim_ids or []
        ),
        description=description,
        supports=supports,
        independent=independent,
    )

    errors = validate_signal(
        signal
    )

    if errors:
        raise ValueError(
            "; ".join(errors)
        )

    relationship.signal_ids.append(
        signal.signal_id
    )

    relationship.source_ids = list(
        dict.fromkeys(
            relationship.source_ids
            + signal.source_ids
        )
    )

    relationship.claim_ids = list(
        dict.fromkeys(
            relationship.claim_ids
            + signal.claim_ids
        )
    )

    return signal


# ============================================================
# RELATIONSHIP STATUS
# ============================================================

def set_relationship_status(
    relationship: RelationshipEdge,
    status: RelationshipStatus,
) -> None:

    relationship.status = status

    # Status does NOT establish guilt, identity,
    # or misconduct.

    relationship.identity_established = False
    relationship.guilt_established = False
    relationship.misconduct_established = False


# ============================================================
# CONTRADICTION
# ============================================================

def attach_contradiction(
    relationship: RelationshipEdge,
    contradiction_id: str,
) -> None:

    if contradiction_id not in (
        relationship.contradiction_ids
    ):
        relationship.contradiction_ids.append(
            contradiction_id
        )

    relationship.status = (
        RelationshipStatus.CONTRADICTED
    )


# ============================================================
# GRAPH BUILD
# ============================================================

def build_relationship_graph(
    entity_ids: List[str],
    relationships: List[RelationshipEdge],
    signals: Optional[List[RelationshipSignal]] = None,
) -> RelationshipGraph:

    graph = RelationshipGraph(
        graph_id=new_id("GRAPH"),
        entity_ids=list(
            dict.fromkeys(
                entity_ids
            )
        ),
        relationships=list(
            relationships
        ),
        signals=list(
            signals or []
        ),
        metadata={
            "fact_established": False,
            "identity_established": False,
            "guilt_established": False,
            "misconduct_established": False,
            "provenance_preserved": True,
            "association_is_not_guilt": True,
        },
    )

    errors = validate_graph(
        graph
    )

    if errors:
        raise ValueError(
            "; ".join(errors)
        )

    return graph


# ============================================================
# GRAPH QUERIES
# ============================================================

def relationships_for_entity(
    graph: RelationshipGraph,
    entity_id: str,
) -> List[RelationshipEdge]:

    return [
        relationship
        for relationship in graph.relationships
        if (
            relationship.source_entity_id
            == entity_id
            or relationship.target_entity_id
            == entity_id
        )
    ]


def neighbors(
    graph: RelationshipGraph,
    entity_id: str,
) -> Set[str]:

    result: Set[str] = set()

    for relationship in relationships_for_entity(
        graph,
        entity_id,
    ):

        if (
            relationship.source_entity_id
            == entity_id
        ):
            result.add(
                relationship.target_entity_id
            )

        if (
            relationship.target_entity_id
            == entity_id
        ):
            result.add(
                relationship.source_entity_id
            )

    return result


def relationship_between(
    graph: RelationshipGraph,
    source_entity_id: str,
    target_entity_id: str,
) -> List[RelationshipEdge]:

    return [
        relationship
        for relationship in graph.relationships
        if (
            relationship.source_entity_id
            == source_entity_id
            and relationship.target_entity_id
            == target_entity_id
        )
        or (
            relationship.direction
            == RelationshipDirection.UNDIRECTED
            and relationship.source_entity_id
            == target_entity_id
            and relationship.target_entity_id
            == source_entity_id
        )
    ]


# ============================================================
# DEDUPLICATION
# ============================================================

def relationship_key(
    relationship: RelationshipEdge,
) -> tuple:

    if (
        relationship.direction
        == RelationshipDirection.UNDIRECTED
    ):

        entities = tuple(
            sorted(
                [
                    relationship.source_entity_id,
                    relationship.target_entity_id,
                ]
            )
        )

    else:

        entities = (
            relationship.source_entity_id,
            relationship.target_entity_id,
        )

    return (
        entities,
        relationship.relationship_type.value,
    )


def deduplicate_relationships(
    relationships: List[RelationshipEdge],
) -> List[RelationshipEdge]:

    result = []
    seen = set()

    for relationship in relationships:

        key = relationship_key(
            relationship
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(
            relationship
        )

    return result


# ============================================================
# PUBLIC API
# ============================================================

__all__ = [
    "RelationshipStatus",
    "RelationshipDirection",
    "RelationshipConfidence",
    "RelationshipType",
    "RelationshipSignal",
    "RelationshipEdge",
    "RelationshipGraph",
    "new_id",
    "validate_relationship",
    "validate_signal",
    "validate_graph",
    "build_relationship",
    "add_relationship_signal",
    "set_relationship_status",
    "attach_contradiction",
    "build_relationship_graph",
    "relationships_for_entity",
    "neighbors",
    "relationship_between",
    "relationship_key",
    "deduplicate_relationships",
]
