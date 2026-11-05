
import sys

APP_ROOT = "/home/nexforensics/app"

if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)


def check(name, condition, failures):

    if condition:
        print(f"  {name:<48}: PASS")
        return

    print(f"  {name:<48}: FAIL")
    failures.append(name)


def main():

    failures = []

    from journalist_research.runtime.evidence_runtime import (
        EvidenceRuntime
    )

    print()
    print("=" * 76)
    print("DOA PHASE 2 : EVIDENCE RUNTIME CONTRACT TEST")
    print("=" * 76)

    runtime = EvidenceRuntime(
        "DOA-EVIDENCE-E2E-001"
    )

    # --------------------------------------------------------
    # SOURCE / DOCUMENT
    # --------------------------------------------------------

    print()
    print("[1] SOURCE -> DOCUMENT")

    content_1 = (
        "Example Corp was incorporated in 2018. "
        "Its public website described the company as a technology business."
    )

    source_1, document_1 = runtime.ingest_source(
        source_id="SRC-001",
        url="https://example.invalid/corporate-history",
        title="Example Corp Corporate History",
        publisher="Synthetic Registry",
        source_type="CORPORATE_RECORD",
        content=content_1,
    )

    check(
        "Source created",
        source_1.source_id == "SRC-001",
        failures,
    )

    check(
        "Document created",
        document_1.document_id == "doc_SRC-001",
        failures,
    )

    check(
        "Content hash preserved",
        source_1.content_hash == document_1.content_hash,
        failures,
    )

    check(
        "Provenance preserved",
        bool(source_1.provenance)
        and bool(document_1.provenance),
        failures,
    )

    # --------------------------------------------------------
    # SECOND SOURCE WITH CONTRADICTORY INFORMATION
    # --------------------------------------------------------

    print()
    print("[2] SECOND SOURCE / CONTRADICTION FIXTURE")

    content_2 = (
        "A later archived page described Example Corp "
        "as having begun operations in 2019."
    )

    source_2, document_2 = runtime.ingest_source(
        source_id="SRC-002",
        url="https://example.invalid/archive-2019",
        title="Archived Example Corp Page",
        publisher="Synthetic Archive",
        source_type="ARCHIVED_WEBPAGE",
        content=content_2,
    )

    check(
        "Second source created",
        source_2.source_id == "SRC-002",
        failures,
    )

    check(
        "Second document created",
        document_2.document_id == "doc_SRC-002",
        failures,
    )

    # --------------------------------------------------------
    # CLAIMS
    # --------------------------------------------------------

    print()
    print("[3] DOCUMENT -> CLAIM")

    claim_1 = runtime.add_claim(
        claim_id="CLM-001",
        text="Example Corp was incorporated in 2018.",
        source_id=source_1.source_id,
        document_id=document_1.document_id,
    )

    claim_2 = runtime.add_claim(
        claim_id="CLM-002",
        text="Example Corp began operations in 2019.",
        source_id=source_2.source_id,
        document_id=document_2.document_id,
    )

    check(
        "First claim attached",
        claim_1.claim_id == "CLM-001",
        failures,
    )

    check(
        "Second claim attached",
        claim_2.claim_id == "CLM-002",
        failures,
    )

    check(
        "Claims remain unverified",
        all(
            c.truth_verified is False
            for c in runtime.state.claims
        ),
        failures,
    )

    # --------------------------------------------------------
    # ENTITY
    # --------------------------------------------------------

    print()
    print("[4] CLAIM -> ENTITY")

    entity = runtime.add_entity(
        entity_id="ENT-001",
        name="Example Corp",
        entity_type="ORGANIZATION",
        source_ids=[
            source_1.source_id,
            source_2.source_id,
        ],
    )

    runtime.attach_claim_entity(
        "CLM-001",
        entity.entity_id,
    )

    runtime.attach_claim_entity(
        "CLM-002",
        entity.entity_id,
    )

    check(
        "Entity created",
        entity.entity_id == "ENT-001",
        failures,
    )

    check(
        "Claim/entity linkage preserved",
        len(claim_1.entity_ids) == 1
        and len(claim_2.entity_ids) == 1,
        failures,
    )

    check(
        "Identity remains unestablished",
        entity.identity_established is False,
        failures,
    )

    # --------------------------------------------------------
    # CONTRADICTION
    # --------------------------------------------------------

    print()
    print("[5] CONTRADICTION PRESERVATION")

    contradiction = {
        "contradiction_id": "CON-001",
        "claim_a": "CLM-001",
        "claim_b": "CLM-002",
        "type": "TEMPORAL",
        "status": "REQUIRES_REVIEW",
        "automatic_resolution": False,
    }

    runtime.add_contradiction(
        contradiction
    )

    check(
        "Contradiction stored",
        len(runtime.state.contradictions) == 1,
        failures,
    )

    check(
        "Automatic resolution blocked",
        runtime.state.contradictions[0][
            "automatic_resolution"
        ] is False,
        failures,
    )

    # --------------------------------------------------------
    # EVIDENCE GRAPH BOUNDARY
    # --------------------------------------------------------

    print()
    print("[6] EVIDENCE GRAPH BOUNDARY")

    graph_fixture = {
        "graph_id": "GRAPH-001",
        "nodes": [
            "SRC-001",
            "SRC-002",
            "CLM-001",
            "CLM-002",
            "ENT-001",
        ],
        "provenance_preserved": True,
        "contradictions_preserved": True,
        "fact_established": False,
        "identity_established": False,
        "guilt_established": False,
    }

    runtime.attach_graph(
        graph_fixture
    )

    check(
        "Evidence graph attached",
        runtime.state.evidence_graph is not None,
        failures,
    )

    check(
        "Graph provenance preserved",
        runtime.state.evidence_graph[
            "provenance_preserved"
        ] is True,
        failures,
    )

    check(
        "Graph contradictions preserved",
        runtime.state.evidence_graph[
            "contradictions_preserved"
        ] is True,
        failures,
    )

    # --------------------------------------------------------
    # NEGATIVE FINDING
    # --------------------------------------------------------

    print()
    print("[7] NEGATIVE FINDING SEPARATION")

    negative = {
        "finding_id": "NEG-001",
        "state": "NOT_FOUND",
        "source_id": "SRC-001",
        "meaning": "No relevant result found in this source.",
        "non_existence": False,
    }

    runtime.attach_negative_findings(
        [negative]
    )

    check(
        "Negative finding preserved",
        len(runtime.state.negative_findings) == 1,
        failures,
    )

    check(
        "NOT_FOUND != non-existence",
        runtime.state.negative_findings[0][
            "non_existence"
        ] is False,
        failures,
    )

    # --------------------------------------------------------
    # CONFIDENCE BOUNDARY
    # --------------------------------------------------------

    print()
    print("[8] CONFIDENCE BOUNDARY")

    confidence = {
        "claim_id": "CLM-001",
        "confidence": None,
        "truth": False,
        "human_review_required": True,
    }

    runtime.attach_confidence(
        [confidence]
    )

    check(
        "Confidence attached",
        len(runtime.state.confidence) == 1,
        failures,
    )

    check(
        "Confidence does not establish truth",
        runtime.state.confidence[0]["truth"] is False,
        failures,
    )

    # --------------------------------------------------------
    # FINAL SAFETY STATE
    # --------------------------------------------------------

    print()
    print("[9] FINAL SAFETY STATE")

    state = runtime.finalize_for_review()

    check(
        "Runtime status REVIEW_REQUIRED",
        state.status == "REVIEW_REQUIRED",
        failures,
    )

    check(
        "Provenance preserved",
        state.provenance_preserved is True,
        failures,
    )

    check(
        "Contradictions preserved",
        state.contradictions_preserved is True,
        failures,
    )

    check(
        "Fact not established",
        state.fact_established is False,
        failures,
    )

    check(
        "Identity not established",
        state.identity_established is False,
        failures,
    )

    check(
        "Guilt not established",
        state.guilt_established is False,
        failures,
    )

    check(
        "Non-existence not established",
        state.non_existence_established is False,
        failures,
    )

    check(
        "Automatic conclusion blocked",
        state.automatic_conclusion is False,
        failures,
    )

    check(
        "Human review required",
        state.human_review_required is True,
        failures,
    )

    # --------------------------------------------------------
    # SERIALIZATION
    # --------------------------------------------------------

    print()
    print("[10] SERIALIZATION")

    payload = state.serialize()

    check(
        "Investigation ID preserved",
        payload["investigation_id"]
        == "DOA-EVIDENCE-E2E-001",
        failures,
    )

    check(
        "Sources serialized",
        len(payload["sources"]) == 2,
        failures,
    )

    check(
        "Documents serialized",
        len(payload["documents"]) == 2,
        failures,
    )

    check(
        "Claims serialized",
        len(payload["claims"]) == 2,
        failures,
    )

    check(
        "Entities serialized",
        len(payload["entities"]) == 1,
        failures,
    )

    check(
        "Contradictions serialized",
        len(payload["contradictions"]) == 1,
        failures,
    )

    print()
    print("=" * 76)

    if failures:
        print("FINAL RESULT : FAIL")
        print()
        print("FAILED CHECKS:")
        for item in failures:
            print("  -", item)
        raise SystemExit(1)

    print("FINAL RESULT : PASS")
    print()
    print("SOURCES                     :", len(state.sources))
    print("DOCUMENTS                   :", len(state.documents))
    print("CLAIMS                      :", len(state.claims))
    print("ENTITIES                    :", len(state.entities))
    print("CONTRADICTIONS              :", len(state.contradictions))
    print("PROVENANCE PRESERVED        :", state.provenance_preserved)
    print("CONTRADICTIONS PRESERVED    :", state.contradictions_preserved)
    print("FACT ESTABLISHMENT          :", state.fact_established)
    print("IDENTITY ESTABLISHMENT      :", state.identity_established)
    print("GUILT ESTABLISHMENT         :", state.guilt_established)
    print("NON-EXISTENCE ESTABLISHMENT :", state.non_existence_established)
    print("AUTOMATIC CONCLUSION        :", state.automatic_conclusion)
    print("HUMAN REVIEW REQUIRED       :", state.human_review_required)
    print("REAL WEB SEARCH             : NOT PERFORMED")
    print("=" * 76)


if __name__ == "__main__":
    main()
