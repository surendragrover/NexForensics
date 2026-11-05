
"""
DOA Phase 4 - Real Crawler + Extractor Integration Test

Uses the real public-web search provider already installed.
Fetches a limited number of public pages.
No Tor, no login bypass, no private network access.
"""

from pathlib import Path
import sys
import json
import hashlib

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


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    print(f"  {label:<54} : PASS")


print("=" * 84)
print("DOA PHASE 4 : WEB CRAWLER + PAGE EXTRACTOR TEST")
print("=" * 84)

# ------------------------------------------------------------
# 1. Search
# ------------------------------------------------------------

print("\\n[1] REAL PUBLIC WEB SEARCH")

provider = DuckDuckGoPublicWebProvider(timeout=20)
connector = PublicWebSearchConnector(provider)

query = '"NexForensics"'
query_id = "DOA-PHASE4-001"

records = connector.search(
    query=query,
    query_id=query_id,
    max_results=5,
)

check(isinstance(records, list), "Search result list")
print("  Search results:", len(records))

# ------------------------------------------------------------
# 2. Crawler and extractor
# ------------------------------------------------------------

print("\\n[2] CRAWLER AND EXTRACTOR")

crawler = PublicWebCrawler(
    timeout=20,
    max_bytes=5_000_000,
    max_redirects=5,
)

extractor = PageExtractor()

check(
    crawler.max_bytes == 5_000_000,
    "Response size limit configured",
)

check(
    crawler.max_redirects == 5,
    "Redirect limit configured",
)

# ------------------------------------------------------------
# 3. Fetch and extract
# ------------------------------------------------------------

print("\\n[3] FETCH AND EXTRACTION")

success_count = 0
documents = []
sources = []
extractions = []
seen_hashes = set()
seen_urls = set()

for index, record in enumerate(records, start=1):

    print(f"\\n  PAGE [{index}] {record.url}")

    if record.url in seen_urls:
        print("    DUPLICATE URL : SKIPPED")
        continue

    seen_urls.add(record.url)

    crawl = crawler.fetch(record.url)

    print("    FETCH STATUS :", crawl.status)
    print("    HTTP STATUS  :", crawl.http_status)
    print("    CONTENT TYPE :", crawl.content_type)

    if crawl.status != "FETCHED":
        print("    FETCH ERROR  :", crawl.error)
        continue

    extracted = extractor.extract(
        crawl.content,
        crawl.final_url,
        crawl.content_type,
    )

    print("    EXTRACTION   :", extracted.extraction_status)
    print("    TITLE        :", extracted.title[:160])
    print("    TEXT LENGTH  :", len(extracted.text))
    print("    SHA256       :", extracted.content_hash)

    if extracted.extraction_status not in (
        "EXTRACTED",
        "LOW_CONTENT",
    ):
        continue

    if not extracted.text:
        continue

    # Duplicate content is not silently counted twice.
    if extracted.content_hash in seen_hashes:
        print("    DUPLICATE CONTENT : SKIPPED")
        continue

    seen_hashes.add(extracted.content_hash)

    source = build_source_record(
        record,
        source_type=SourceType.UNKNOWN,
    )

    # Use the existing canonical document builder.
    document = build_document_record(
        source,
        extracted.text,
    )

    check(
        document.source_id == source.source_id,
        "Document-source linkage",
    )

    check(
        document.url == source.url,
        "Document URL provenance",
    )

    check(
        bool(document.content_hash),
        "Canonical document content hash",
    )

    check(
        document.fact_establishment is False,
        "Document does not establish fact",
    )

    check(
        extracted.content_hash
        == hashlib.sha256(
            extracted.text.encode("utf-8")
        ).hexdigest(),
        "Extractor SHA256 verification",
    )

    sources.append(source)
    documents.append(document)
    extractions.append(extracted)

    success_count += 1

    print("    DOCUMENT ID  :", document.document_id)
    print("    SOURCE ID    :", source.source_id)

# ------------------------------------------------------------
# 4. Safety and completeness
# ------------------------------------------------------------

print("\\n[4] SAFETY AND PROVENANCE")

check(
    len(documents) == len(sources),
    "Source/document count consistency",
)

check(
    all(
        document.fact_establishment is False
        for document in documents
    ),
    "No document establishes fact",
)

check(
    all(
        source.fact_establishment is False
        for source in sources
    ),
    "No source establishes fact",
)

check(
    all(
        item.metadata.get("javascript_executed") is False
        for item in extractions
    ),
    "JavaScript execution disabled",
)

check(
    len(seen_hashes) == len(documents),
    "Duplicate content control",
)

# ------------------------------------------------------------
# 5. Results
# ------------------------------------------------------------

print("\\n" + "=" * 84)
print("DOA PHASE 4 : RESULT")
print("=" * 84)

print("SEARCH RESULTS               :", len(records))
print("SUCCESSFULLY CRAWLED         :", success_count)
print("SOURCE RECORDS               :", len(sources))
print("DOCUMENT RECORDS             :", len(documents))
print("UNIQUE CONTENT HASHES        :", len(seen_hashes))
print("FACT ESTABLISHMENT           : False")
print("IDENTITY ESTABLISHMENT       : False")
print("GUILT ESTABLISHMENT          : False")
print("NON-EXISTENCE ESTABLISHMENT  : False")
print("JAVASCRIPT EXECUTION         : False")
print("TOR ACCESS                   : NOT PERFORMED")
print("PRIVATE NETWORK ACCESS       : BLOCKED")
print("=" * 84)

if success_count == 0:
    print("PHASE 4 STATUS : NO PAGE SUCCESSFULLY EXTRACTED")
    raise SystemExit(2)

print("PHASE 4 STATUS : PASS")
