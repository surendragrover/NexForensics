
"""
DOA Phase 5 - Document Intelligence Integration Test

Uses real public search and page retrieval.
No synthetic claims are injected.
"""

from pathlib import Path
import sys
import json

ROOT = Path("/home/nexforensics/app")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from journalist_research.web_research.search_engine import (
    PublicWebSearchConnector,
)

from journalist_research.web_research.duckduckgo_provider import (
    DuckDuckGoPublicWebProvider,
)

from journalist_research.web_research.web_crawler import (
    PublicWebCrawler,
)

from journalist_research.web_research.page_extractor import (
    PageExtractor,
)

from journalist_research.evidence.source_provenance import (
    build_source_record,
    build_document_record,
    SourceType,
)

from journalist_research.evidence.document_intelligence import (
    DocumentIntelligence,
)


def check(condition, label):
    if not condition:
        raise AssertionError(label)

    print(f"  {label:<55} : PASS")


print("=" * 84)
print("DOA PHASE 5 : DOCUMENT INTELLIGENCE + CLAIM EXTRACTION")
print("=" * 84)

# ------------------------------------------------------------
# 1. Initialize pipeline
# ------------------------------------------------------------

print("\\n[1] PIPELINE INITIALIZATION")

provider = DuckDuckGoPublicWebProvider(
    timeout=20
)

connector = PublicWebSearchConnector(provider)

crawler = PublicWebCrawler(
    timeout=20,
    max_bytes=5_000_000,
    max_redirects=5,
)

extractor = PageExtractor()

intelligence = DocumentIntelligence()

check(
    intelligence.extract_function is not None,
    "Existing claim extractor connected",
)

print(
    "  EXTRACTOR FUNCTION:",
    intelligence.extract_function.__name__,
)

# ------------------------------------------------------------
# 2. Real search
# ------------------------------------------------------------

print("\\n[2] REAL PUBLIC WEB SEARCH")

query = '"NexForensics"'
query_id = "DOA-PHASE5-001"

records = connector.search(
    query=query,
    query_id=query_id,
    max_results=5,
)

check(
    isinstance(records, list),
    "Search results received",
)

print("  SEARCH RESULTS:", len(records))

# ------------------------------------------------------------
# 3. Crawl, extract and process claims
# ------------------------------------------------------------

print("\\n[3] DOCUMENT PROCESSING")

total_documents = 0
total_claims = 0
processed_results = []
classification_counts = {}

for index, record in enumerate(records, start=1):

    print(f"\\n  DOCUMENT [{index}] {record.url}")

    crawl = crawler.fetch(record.url)

    print("    FETCH:", crawl.status)

    if crawl.status != "FETCHED":
        print("    SKIPPED:", crawl.error)
        continue

    page = extractor.extract(
        crawl.content,
        crawl.final_url,
        crawl.content_type,
    )

    print("    EXTRACTION:", page.extraction_status)
    print("    TITLE:", page.title[:120])
    print("    TEXT LENGTH:", len(page.text))

    if page.extraction_status not in (
        "EXTRACTED",
        "LOW_CONTENT",
    ):
        print("    CLAIM EXTRACTION: SKIPPED")
        continue

    if not page.text.strip():
        print("    EMPTY DOCUMENT: SKIPPED")
        continue

    source = build_source_record(
        record,
        source_type=SourceType.UNKNOWN,
    )

    document = build_document_record(
        source,
        page.text,
    )

    result = intelligence.process(
        document=document,
        source=source,
    )

    errors = intelligence.validate_result(
        result
    )

    if errors:
        raise AssertionError(
            "Integration validation failed: "
            + "; ".join(errors)
        )

    check(
        document.document_id == result.document_id,
        "Document ID preserved",
    )

    check(
        source.source_id == result.source_id,
        "Source ID preserved",
    )

    check(
        all(
            claim.document_id == document.document_id
            for claim in result.claims
        ),
        "All claims linked to document",
    )

    check(
        all(
            claim.source_id == source.source_id
            for claim in result.claims
        ),
        "All claims linked to source",
    )

    check(
        all(
            claim.fact_established is False
            for claim in result.claims
        ),
        "Claims do not establish facts",
    )

    check(
        result.human_review_required is True,
        "Human review required",
    )

    check(
        result.automatic_conclusion is False,
        "Automatic conclusion blocked",
    )

    total_documents += 1
    total_claims += len(result.claims)

    for claim in result.claims:
        classification_counts[
            claim.classification
        ] = (
            classification_counts.get(
                claim.classification,
                0,
            ) + 1
        )

    processed_results.append(
        intelligence.serialize(result)
    )

    print(
        "    CLAIMS:",
        len(result.claims),
    )

    print(
        "    STATUS:",
        result.extraction_status,
    )

    if result.errors:
        print(
            "    ERRORS:",
            result.errors,
        )

# ------------------------------------------------------------
# 4. Classification integrity
# ------------------------------------------------------------

print("\\n[4] CLAIM CLASSIFICATION")

allowed = {
    "ASSERTION",
    "ALLEGATION",
    "UNCERTAIN",
    "NEGATED",
    "OBSERVATION",
}

for category, count in sorted(
    classification_counts.items()
):
    print(
        f"  {category:<25} : {count}"
    )

check(
    all(
        category in allowed
        for category in classification_counts
    ),
    "Classification vocabulary",
)

# ------------------------------------------------------------
# 5. Global safety
# ------------------------------------------------------------

print("\\n[5] GLOBAL SAFETY")

check(
    all(
        item["fact_established"] is False
        for item in processed_results
    ),
    "No document establishes fact",
)

check(
    all(
        item["identity_established"] is False
        for item in processed_results
    ),
    "No identity established",
)

check(
    all(
        item["guilt_established"] is False
        for item in processed_results
    ),
    "No guilt established",
)

check(
    all(
        item["automatic_conclusion"] is False
        for item in processed_results
    ),
    "No automatic conclusion",
)

check(
    all(
        item["human_review_required"] is True
        for item in processed_results
    ),
    "Human review preserved",
)

# ------------------------------------------------------------
# 6. Serialize test result
# ------------------------------------------------------------

output = {
    "phase": "DOA_PHASE_5",
    "search_results": len(records),
    "documents_processed": total_documents,
    "claims_extracted": total_claims,
    "classification_counts": classification_counts,
    "documents": processed_results,
    "fact_establishment": False,
    "identity_establishment": False,
    "guilt_establishment": False,
    "automatic_conclusion": False,
    "human_review_required": True,
}

json.dumps(
    output,
    ensure_ascii=False,
)

print("\\n" + "=" * 84)
print("DOA PHASE 5 : FINAL RESULT")
print("=" * 84)

print("SEARCH RESULTS              :", len(records))
print("DOCUMENTS PROCESSED         :", total_documents)
print("CLAIMS EXTRACTED            :", total_claims)
print("FACT ESTABLISHMENT          : False")
print("IDENTITY ESTABLISHMENT      : False")
print("GUILT ESTABLISHMENT         : False")
print("AUTOMATIC CONCLUSION        : False")
print("HUMAN REVIEW REQUIRED       : True")
print("=" * 84)

if total_documents == 0:
    print("PHASE 5 : NO DOCUMENTS PROCESSED")
    raise SystemExit(2)

print("PHASE 5 STATUS : PASS")
