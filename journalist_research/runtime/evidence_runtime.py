
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List


def utc_now():
    return datetime.now(timezone.utc)


def sha256_text(value: str) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


@dataclass
class EvidenceSource:
    source_id: str
    url: str
    title: str
    publisher: str
    source_type: str
    retrieved_at: str
    content_hash: str
    provenance: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceDocument:
    document_id: str
    source_id: str
    title: str
    text: str
    content_hash: str
    retrieved_at: str
    provenance: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceClaim:
    claim_id: str
    text: str
    document_id: str
    source_id: str

    status: str = "UNKNOWN"
    confidence: Any = None
    truth_verified: bool = False
    fact_established: bool = False
    identity_established: bool = False
    guilt_established: bool = False

    contradiction_ids: List[str] = field(default_factory=list)
    entity_ids: List[str] = field(default_factory=list)

    provenance: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceEntity:
    entity_id: str
    name: str
    entity_type: str
    identity_established: bool = False
    source_ids: List[str] = field(default_factory=list)


@dataclass
class EvidenceRuntimeState:
    investigation_id: str

    sources: List[EvidenceSource] = field(default_factory=list)
    documents: List[EvidenceDocument] = field(default_factory=list)
    claims: List[EvidenceClaim] = field(default_factory=list)
    entities: List[EvidenceEntity] = field(default_factory=list)

    timeline: Any = None
    relationships: Any = None
    contradictions: List[Any] = field(default_factory=list)
    evidence_graph: Any = None
    confidence: List[Any] = field(default_factory=list)
    negative_findings: List[Any] = field(default_factory=list)
    synthesis: Any = None

    status: str = "NOT_STARTED"

    provenance_preserved: bool = True
    contradictions_preserved: bool = True

    fact_established: bool = False
    identity_established: bool = False
    guilt_established: bool = False
    non_existence_established: bool = False
    automatic_conclusion: bool = False
    human_review_required: bool = True

    trace: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def mark(self, stage):
        self.trace.append(stage)

    def assert_safety(self):

        assert self.fact_established is False
        assert self.identity_established is False
        assert self.guilt_established is False
        assert self.non_existence_established is False
        assert self.automatic_conclusion is False
        assert self.human_review_required is True

        return True

    def serialize(self):

        def convert(value):
            if hasattr(value, "__dataclass_fields__"):
                return {
                    k: convert(v)
                    for k, v in asdict(value).items()
                }

            if isinstance(value, list):
                return [convert(v) for v in value]

            if isinstance(value, dict):
                return {
                    k: convert(v)
                    for k, v in value.items()
                }

            return value

        return convert(self)


class EvidenceRuntime:

    def __init__(self, investigation_id):
        self.state = EvidenceRuntimeState(
            investigation_id=investigation_id
        )

    def ingest_source(
        self,
        source_id,
        url,
        title,
        publisher,
        source_type,
        content,
    ):

        content_hash = sha256_text(content)

        source = EvidenceSource(
            source_id=source_id,
            url=url,
            title=title,
            publisher=publisher,
            source_type=source_type,
            retrieved_at=utc_now().isoformat(),
            content_hash=content_hash,
            provenance={
                "source_id": source_id,
                "url": url,
                "retrieval": "synthetic_fixture",
                "network_access": False,
            },
        )

        document = EvidenceDocument(
            document_id=f"doc_{source_id}",
            source_id=source_id,
            title=title,
            text=content,
            content_hash=content_hash,
            retrieved_at=source.retrieved_at,
            provenance={
                "source_id": source_id,
                "document_id": f"doc_{source_id}",
                "content_hash": content_hash,
            },
        )

        self.state.sources.append(source)
        self.state.documents.append(document)

        self.state.mark("SOURCE_INGESTED")
        self.state.mark("DOCUMENT_INGESTED")

        return source, document

    def add_claim(
        self,
        claim_id,
        text,
        source_id,
        document_id,
        status="UNKNOWN",
    ):

        claim = EvidenceClaim(
            claim_id=claim_id,
            text=text,
            document_id=document_id,
            source_id=source_id,
            status=status,
            provenance={
                "source_id": source_id,
                "document_id": document_id,
                "network_access": False,
            },
        )

        self.state.claims.append(claim)
        self.state.mark("CLAIM_ATTACHED")

        return claim

    def add_entity(
        self,
        entity_id,
        name,
        entity_type,
        source_ids,
    ):

        entity = EvidenceEntity(
            entity_id=entity_id,
            name=name,
            entity_type=entity_type,
            identity_established=False,
            source_ids=list(source_ids),
        )

        self.state.entities.append(entity)
        self.state.mark("ENTITY_ATTACHED")

        return entity

    def attach_claim_entity(
        self,
        claim_id,
        entity_id,
    ):

        claim = next(
            c for c in self.state.claims
            if c.claim_id == claim_id
        )

        if entity_id not in claim.entity_ids:
            claim.entity_ids.append(entity_id)

        self.state.mark("CLAIM_ENTITY_LINKED")

    def add_contradiction(
        self,
        contradiction,
    ):

        self.state.contradictions.append(
            contradiction
        )

        self.state.contradictions_preserved = True

        self.state.mark("CONTRADICTION_ATTACHED")

    def attach_graph(
        self,
        graph,
    ):

        self.state.evidence_graph = graph
        self.state.mark("EVIDENCE_GRAPH_ATTACHED")

    def attach_timeline(
        self,
        timeline,
    ):

        self.state.timeline = timeline
        self.state.mark("TIMELINE_ATTACHED")

    def attach_relationships(
        self,
        relationships,
    ):

        self.state.relationships = relationships
        self.state.mark("RELATIONSHIPS_ATTACHED")

    def attach_confidence(
        self,
        confidence,
    ):

        self.state.confidence = confidence
        self.state.mark("CONFIDENCE_ATTACHED")

    def attach_negative_findings(
        self,
        findings,
    ):

        self.state.negative_findings = findings
        self.state.mark("NEGATIVE_FINDINGS_ATTACHED")

    def finalize_for_review(self):

        self.state.assert_safety()

        self.state.status = "REVIEW_REQUIRED"

        self.state.mark("EVIDENCE_RUNTIME_COMPLETE")

        self.state.assert_safety()

        return self.state

    def to_json(self):

        return json.dumps(
            self.state.serialize(),
            ensure_ascii=False,
            indent=2,
        )
