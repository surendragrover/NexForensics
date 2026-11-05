"""
Deep OSINT Agent (DOA)
Core investigation data models.

Design principle:
Search result != Evidence
Evidence != Proof
Claim != Fact
Hypothesis != Finding
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


# ============================================================
# ENUMS
# ============================================================

class InvestigationStatus(str, Enum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    RESEARCHING = "RESEARCHING"
    EVIDENCE_REVIEW = "EVIDENCE_REVIEW"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ClaimStatus(str, Enum):
    ESTABLISHED = "ESTABLISHED"
    STRONG_INDICATOR = "STRONG_INDICATOR"
    UNVERIFIED = "UNVERIFIED"
    CONTRADICTED = "CONTRADICTED"
    NOT_ESTABLISHED = "NOT_ESTABLISHED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNKNOWN = "UNKNOWN"


class SourceType(str, Enum):
    GOVERNMENT = "GOVERNMENT"
    COURT = "COURT"
    REGULATORY = "REGULATORY"
    CORPORATE = "CORPORATE"
    JOURNALISM = "JOURNALISM"
    ACADEMIC = "ACADEMIC"
    ARCHIVED_WEB = "ARCHIVED_WEB"
    PUBLIC_DATABASE = "PUBLIC_DATABASE"
    SOCIAL_MEDIA = "SOCIAL_MEDIA"
    FORUM = "FORUM"
    DARK_WEB = "DARK_WEB"
    USER_SUBMITTED = "USER_SUBMITTED"
    UNKNOWN = "UNKNOWN"


class SourceReliability(str, Enum):
    VERY_HIGH = "VERY_HIGH"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    VERY_LOW = "VERY_LOW"
    UNKNOWN = "UNKNOWN"


class EvidenceType(str, Enum):
    DOCUMENT = "DOCUMENT"
    WEB_PAGE = "WEB_PAGE"
    COURT_RECORD = "COURT_RECORD"
    CORPORATE_RECORD = "CORPORATE_RECORD"
    GOVERNMENT_RECORD = "GOVERNMENT_RECORD"
    REGULATORY_RECORD = "REGULATORY_RECORD"
    MEDIA_REPORT = "MEDIA_REPORT"
    ARCHIVED_PAGE = "ARCHIVED_PAGE"
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    SOCIAL_POST = "SOCIAL_POST"
    DARK_WEB_RECORD = "DARK_WEB_RECORD"
    USER_PROVIDED = "USER_PROVIDED"
    OTHER = "OTHER"


class EntityType(str, Enum):
    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"
    COMPANY = "COMPANY"
    GOVERNMENT = "GOVERNMENT"
    LOCATION = "LOCATION"
    ADDRESS = "ADDRESS"
    DOMAIN = "DOMAIN"
    WEBSITE = "WEBSITE"
    EVENT = "EVENT"
    CASE = "CASE"
    ACCOUNT = "ACCOUNT"
    UNKNOWN = "UNKNOWN"


class RelationshipType(str, Enum):
    EMPLOYEE = "EMPLOYEE"
    DIRECTOR = "DIRECTOR"
    OWNER = "OWNER"
    SHAREHOLDER = "SHAREHOLDER"
    PARTNER = "PARTNER"
    ASSOCIATE = "ASSOCIATE"
    FAMILY = "FAMILY"
    LEGAL_REPRESENTATIVE = "LEGAL_REPRESENTATIVE"
    CUSTOMER = "CUSTOMER"
    SUPPLIER = "SUPPLIER"
    LOCATED_AT = "LOCATED_AT"
    REGISTERED_AT = "REGISTERED_AT"
    RELATED_TO_CASE = "RELATED_TO_CASE"
    MENTIONED_WITH = "MENTIONED_WITH"
    UNKNOWN = "UNKNOWN"


class SearchTaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class CorroborationStatus(str, Enum):
    NONE = "NONE"
    PARTIAL = "PARTIAL"
    INDEPENDENT = "INDEPENDENT"
    STRONG = "STRONG"
    CONTRADICTED = "CONTRADICTED"


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    import uuid
    return f"{prefix}_{uuid.uuid4().hex}"


def serialize(value: Any) -> Any:
    """
    Convert dataclasses/enums/datetimes recursively into
    JSON-compatible Python objects.
    """
    if isinstance(value, Enum):
        return value.value

    if isinstance(value, datetime):
        return value.isoformat()

    if hasattr(value, "__dataclass_fields__"):
        return {
            key: serialize(val)
            for key, val in asdict(value).items()
        }

    if isinstance(value, dict):
        return {
            str(key): serialize(val)
            for key, val in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [serialize(item) for item in value]

    return value


# ============================================================
# INVESTIGATION
# ============================================================

@dataclass
class Investigation:
    title: str
    primary_question: str

    investigation_id: str = field(
        default_factory=lambda: new_id("INV")
    )

    status: InvestigationStatus = InvestigationStatus.CREATED

    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    investigator: Optional[str] = None
    target_description: Optional[str] = None

    questions: List["Question"] = field(default_factory=list)
    hypotheses: List["Hypothesis"] = field(default_factory=list)
    search_tasks: List["SearchTask"] = field(default_factory=list)

    source_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    claim_ids: List[str] = field(default_factory=list)
    entity_ids: List[str] = field(default_factory=list)

    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# QUESTION
# ============================================================

@dataclass
class Question:
    text: str

    question_id: str = field(
        default_factory=lambda: new_id("Q")
    )

    priority: int = 1
    category: Optional[str] = None

    parent_question_id: Optional[str] = None

    generated_from: Optional[str] = None

    answered: bool = False
    answer_status: ClaimStatus = ClaimStatus.UNKNOWN

    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# HYPOTHESIS
# ============================================================

@dataclass
class Hypothesis:
    statement: str

    hypothesis_id: str = field(
        default_factory=lambda: new_id("H")
    )

    priority: int = 1

    supporting_claim_ids: List[str] = field(default_factory=list)
    contradicting_claim_ids: List[str] = field(default_factory=list)

    confidence: Optional[float] = None

    status: ClaimStatus = ClaimStatus.UNKNOWN

    required_evidence: List[str] = field(default_factory=list)

    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# SEARCH TASK
# ============================================================

@dataclass
class SearchTask:
    query: str

    task_id: str = field(
        default_factory=lambda: new_id("TASK")
    )

    purpose: Optional[str] = None
    category: Optional[str] = None

    priority: int = 1

    status: SearchTaskStatus = SearchTaskStatus.PENDING

    source_types: List[SourceType] = field(default_factory=list)

    target_entity_ids: List[str] = field(default_factory=list)

    created_at: datetime = field(default_factory=utc_now)
    completed_at: Optional[datetime] = None

    result_count: int = 0

    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# SOURCE
# ============================================================

@dataclass
class Source:
    title: str
    url: Optional[str] = None

    source_id: str = field(
        default_factory=lambda: new_id("SRC")
    )

    source_type: SourceType = SourceType.UNKNOWN
    reliability: SourceReliability = SourceReliability.UNKNOWN

    publisher: Optional[str] = None
    author: Optional[str] = None

    published_at: Optional[datetime] = None
    retrieved_at: datetime = field(default_factory=utc_now)

    language: Optional[str] = None

    is_primary_source: bool = False
    is_archived: bool = False

    parent_source_id: Optional[str] = None

    content_hash: Optional[str] = None

    notes: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# DOCUMENT
# ============================================================

@dataclass
class Document:
    source_id: str

    document_id: str = field(
        default_factory=lambda: new_id("DOC")
    )

    title: Optional[str] = None

    document_type: Optional[str] = None

    text_hash: Optional[str] = None

    extracted_text_length: int = 0

    language: Optional[str] = None

    created_at: datetime = field(default_factory=utc_now)

    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# CLAIM
# ============================================================

@dataclass
class Claim:
    text: str

    claim_id: str = field(
        default_factory=lambda: new_id("CLAIM")
    )

    status: ClaimStatus = ClaimStatus.UNVERIFIED

    source_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)

    entity_ids: List[str] = field(default_factory=list)

    confidence: Optional[float] = None

    corroboration: CorroborationStatus = CorroborationStatus.NONE

    contradiction_ids: List[str] = field(default_factory=list)

    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None

    extracted_by: Optional[str] = None

    notes: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# ENTITY
# ============================================================

@dataclass
class Entity:
    name: str
    entity_type: EntityType

    entity_id: str = field(
        default_factory=lambda: new_id("ENT")
    )

    aliases: List[str] = field(default_factory=list)

    description: Optional[str] = None

    confidence: Optional[float] = None

    source_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)

    verified: bool = False

    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# RELATIONSHIP
# ============================================================

@dataclass
class Relationship:
    source_entity_id: str
    target_entity_id: str
    relationship_type: RelationshipType

    relationship_id: str = field(
        default_factory=lambda: new_id("REL")
    )

    confidence: Optional[float] = None

    source_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)

    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None

    status: ClaimStatus = ClaimStatus.UNVERIFIED

    notes: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# EVIDENCE
# ============================================================

@dataclass
class Evidence:
    source_id: str
    evidence_type: EvidenceType

    evidence_id: str = field(
        default_factory=lambda: new_id("EVD")
    )

    title: Optional[str] = None

    description: Optional[str] = None

    captured_at: datetime = field(default_factory=utc_now)

    content_hash: Optional[str] = None

    relevant_entity_ids: List[str] = field(default_factory=list)
    relevant_claim_ids: List[str] = field(default_factory=list)

    reliability: SourceReliability = SourceReliability.UNKNOWN

    independently_verified: bool = False

    chain_of_custody: List[Dict[str, Any]] = field(
        default_factory=list
    )

    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# CONTRADICTION
# ============================================================

@dataclass
class Contradiction:
    claim_a_id: str
    claim_b_id: str

    contradiction_id: str = field(
        default_factory=lambda: new_id("CON")
    )

    description: Optional[str] = None

    severity: str = "MEDIUM"

    source_ids: List[str] = field(default_factory=list)

    resolved: bool = False

    resolution: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# VALIDATION
# ============================================================

def validate_confidence(value: Optional[float]) -> bool:
    """
    Confidence must be between 0 and 100.
    None means not assessed.
    """
    if value is None:
        return True

    return 0.0 <= float(value) <= 100.0


def validate_claim(claim: Claim) -> List[str]:
    errors: List[str] = []

    if not claim.text.strip():
        errors.append("Claim text cannot be empty.")

    if not validate_confidence(claim.confidence):
        errors.append("Claim confidence must be between 0 and 100.")

    return errors


def validate_hypothesis(hypothesis: Hypothesis) -> List[str]:
    errors: List[str] = []

    if not hypothesis.statement.strip():
        errors.append("Hypothesis statement cannot be empty.")

    if not validate_confidence(hypothesis.confidence):
        errors.append(
            "Hypothesis confidence must be between 0 and 100."
        )

    return errors


# ============================================================
# PUBLIC API
# ============================================================

__all__ = [
    "Investigation",
    "Question",
    "Hypothesis",
    "SearchTask",
    "Source",
    "Document",
    "Claim",
    "Entity",
    "Relationship",
    "Evidence",
    "Contradiction",
    "InvestigationStatus",
    "ClaimStatus",
    "SourceType",
    "SourceReliability",
    "EvidenceType",
    "EntityType",
    "RelationshipType",
    "SearchTaskStatus",
    "CorroborationStatus",
    "validate_claim",
    "validate_hypothesis",
    "serialize",
]
