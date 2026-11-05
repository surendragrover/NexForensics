"""
DOA Phase 3C - Real Public Web Integration Test

This test performs ONE real public-web search.

No Tor.
No dark web.
No authentication bypass.
No private-data collection.

The result is treated strictly as search evidence/provenance,
never as an established fact.
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

from journalist_research.evidence.source_provenance import (
    build_source_record,
    build_document_record,
    build_provenance_chain,
    SourceType,
)


def check(condition, label):
    if not condition:
        raise AssertionError(label)

    print(
        f"  {label:<55} : PASS"
    )


print("=" * 84)
print("DOA PHASE 3C : REAL PUBLIC WEB PROVIDER TEST")
print("=" * 84)

query = '"NexForensics"'
query_id = "WEB-REAL-001"

# ------------------------------------------------------------
# 1. Provider
# ------------------------------------------------------------

print("\n[1] REAL PROVIDER")

provider = DuckDuckGoPublicWebProvider(
    timeout=20
)

check(
    provider.provider_name
    == "duckduckgo_public_web",
    "Provider initialized",
)

# ------------------------------------------------------------
# 2. Connector
# ------------------------------------------------------------

print("\n[2] CONNECTOR")

connector = PublicWebSearchConnector(
    provider
)

check(
    connector.connector_name
    == "public_web",
    "Public web connector initialized",
)

# ------------------------------------------------------------
# 3. REAL SEARCH
# ------------------------------------------------------------

print("\n[3] REAL PUBLIC WEB SEARCH")

print("  Query:", query)

try:

    records = connector.search(
        query=query,
        query_id=query_id,
        max_results=5,
    )

except Exception as exc:

    print(
        "\n  REAL SEARCH ERROR :",
        type(exc).__name__,
        str(exc),
    )

    print("\n" + "=" * 84)
    print("DOA PHASE 3C : REAL PUBLIC WEB PROVIDER : NOT VERIFIED")
    print("=" * 84)

    raise SystemExit(2)


check(
    isinstance(records, list),
    "Result list returned",
)

print(
    "  Results returned                                  :",
    len(records),
)

# A real provider may legitimately return zero results.
# Zero results are NOT treated as non-existence.
if not records:

    print(
        "  ZERO RESULTS : NOT_FOUND ONLY; "
        "NON-EXISTENCE NOT ESTABLISHED"
    )

    print("\n" + "=" * 84)
    print("DOA PHASE 3C : REAL PUBLIC WEB PROVIDER : PASS")
    print("=" * 84)

    print("RESULTS                     : 0")
    print("FACT ESTABLISHMENT          : False")
    print("IDENTITY ESTABLISHMENT      : False")
    print("GUILT ESTABLISHMENT         : False")
    print("NON-EXISTENCE ESTABLISHMENT : False")
    print("TOR ACCESS                  : NOT PERFORMED")
    print("=" * 84)

    raise SystemExit(0)

# ------------------------------------------------------------
# 4. Result contract
# ------------------------------------------------------------

print("\n[4] RESULT CONTRACT")

for record in records:

    check(
        record.query_id == query_id,
        "Query ID preserved",
    )

    check(
        record.query == query,
        "Query preserved",
    )

    check(
        record.url.startswith(
            ("http://", "https://")
        ),
        "Valid public-web URL",
    )

    check(
        bool(record.title),
        "Title preserved",
    )

    check(
        record.provider
        == provider.provider_name,
        "Provider preserved",
    )

    check(
        record.search_performed is True,
        "Search-performed flag",
    )

    check(
        record.fact_establishment is False,
        "Fact establishment blocked",
    )

# ------------------------------------------------------------
# 5. Provenance
# ------------------------------------------------------------

print("\n[5] PROVENANCE")

sources = []
documents = []
chains = []

for record in records:

    source = build_source_record(
        record,
        source_type=SourceType.UNKNOWN,
    )

    document = build_document_record(
        source,
        record.snippet,
    )

    chain = build_provenance_chain(
        record,
        source,
        document,
    )

    sources.append(source)
    documents.append(document)
    chains.append(chain)

    check(
        source.result_id == record.result_id,
        "Source -> result provenance",
    )

    check(
        document.source_id
        == source.source_id,
        "Document -> source provenance",
    )

    check(
        chain.result_id
        == record.result_id,
        "Chain -> result provenance",
    )

    check(
        chain.source_id
        == source.source_id,
        "Chain -> source provenance",
    )

    check(
        chain.document_id
        == document.document_id,
        "Chain -> document provenance",
    )

# ------------------------------------------------------------
# 6. Safety
# ------------------------------------------------------------

print("\n[6] SAFETY")

check(
    all(
        r.fact_establishment is False
        for r in records
    ),
    "No search result establishes fact",
)

check(
    all(
        s.fact_establishment is False
        for s in sources
    ),
    "No source establishes fact",
)

check(
    all(
        d.fact_establishment is False
        for d in documents
    ),
    "No document establishes fact",
)

check(
    all(
        c.fact_establishment is False
        for c in chains
    ),
    "No provenance chain establishes fact",
)

# ------------------------------------------------------------
# 7. Display actual results
# ------------------------------------------------------------

print("\n[7] REAL RESULTS")

for i, record in enumerate(
    records,
    start=1,
):

    print(
        f"  [{i}] {record.title}"
    )

    print(
        f"      {record.url}"
    )

# ------------------------------------------------------------
# Final
# ------------------------------------------------------------

print("\n" + "=" * 84)
print("DOA PHASE 3C : REAL PUBLIC WEB PROVIDER : PASS")
print("=" * 84)

print(
    "RESULTS                     :",
    len(records),
)

print(
    "SOURCES                     :",
    len(sources),
)

print(
    "DOCUMENTS                   :",
    len(documents),
)

print(
    "PROVENANCE CHAINS           :",
    len(chains),
)

print("FACT ESTABLISHMENT          : False")
print("IDENTITY ESTABLISHMENT      : False")
print("GUILT ESTABLISHMENT         : False")
print("NON-EXISTENCE ESTABLISHMENT : False")
print("TOR ACCESS                  : NOT PERFORMED")
print("DARK-WEB ACCESS             : NOT PERFORMED")
print("=" * 84)
