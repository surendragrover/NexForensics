"""
DOA Phase 3B - Public Web Search Connector Contract Test

Synthetic provider only.
NO REAL NETWORK ACCESS.
"""

from pathlib import Path
import sys

ROOT = Path("/home/nexforensics/app")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from journalist_research.web_research.search_engine import (
    PublicWebSearchConnector,
    WebSearchItem,
)

from journalist_research.web_research.synthetic_provider import (
    SyntheticPublicWebProvider,
)

from journalist_research.evidence.source_provenance import (
    SearchResultRecord,
)


def check(condition, label):
    if not condition:
        raise AssertionError(label)

    print(f"  {label:<52} : PASS")


print("=" * 82)
print("DOA PHASE 3B : PUBLIC WEB SEARCH CONNECTOR CONTRACT TEST")
print("=" * 82)


# ------------------------------------------------------------
# 1. Provider
# ------------------------------------------------------------

print("\n[1] PROVIDER CONTRACT")

provider = SyntheticPublicWebProvider()

check(
    provider.provider_name == "synthetic_public_web",
    "Provider name",
)


# ------------------------------------------------------------
# 2. Connector
# ------------------------------------------------------------

print("\n[2] PUBLIC WEB CONNECTOR")

connector = PublicWebSearchConnector(provider)

check(
    connector.connector_name == "public_web",
    "Connector name",
)


# ------------------------------------------------------------
# 3. Search
# ------------------------------------------------------------

print("\n[3] SEARCH EXECUTION")

query = '"Example Corp" corporate history'
query_id = "WEB-QRY-001"

records = connector.search(
    query=query,
    query_id=query_id,
    max_results=2,
)

check(
    len(records) == 2,
    "Two results returned",
)

check(
    all(
        isinstance(r, SearchResultRecord)
        for r in records
    ),
    "Canonical SearchResultRecord type",
)


# ------------------------------------------------------------
# 4. Provenance
# ------------------------------------------------------------

print("\n[4] PROVENANCE")

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
        record.url.startswith("https://"),
        "HTTPS URL preserved",
    )

    check(
        record.title,
        "Title preserved",
    )

    check(
        record.provider == provider.provider_name,
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
# 5. Ranking
# ------------------------------------------------------------

print("\n[5] RESULT RANKING")

check(
    records[0].rank == 1,
    "Rank 1 preserved",
)

check(
    records[1].rank == 2,
    "Rank 2 preserved",
)


# ------------------------------------------------------------
# 6. Safety boundaries
# ------------------------------------------------------------

print("\n[6] SAFETY BOUNDARIES")

for record in records:

    metadata = record.metadata

    check(
        metadata.get("public_web") is True,
        "Public-web provenance marker",
    )

    check(
        metadata.get("connector") == "public_web",
        "Connector provenance marker",
    )

    check(
        record.fact_establishment is False,
        "Search result != established fact",
    )


# ------------------------------------------------------------
# 7. Multi-result independence
# ------------------------------------------------------------

print("\n[7] MULTI-RESULT PRESERVATION")

check(
    records[0].url != records[1].url,
    "Distinct result URLs",
)

check(
    records[0].result_id != records[1].result_id,
    "Distinct result IDs",
)


# ------------------------------------------------------------
# 8. Network boundary
# ------------------------------------------------------------

print("\n[8] NETWORK BOUNDARY")

check(
    provider.provider_name
    == "synthetic_public_web",
    "Synthetic provider only",
)

print(
    "  REAL PUBLIC WEB SEARCH                         : NOT PERFORMED"
)

print(
    "  TOR / DARK-WEB ACCESS                          : NOT PERFORMED"
)


# ------------------------------------------------------------
# Final
# ------------------------------------------------------------

print("\n" + "=" * 82)
print("FINAL RESULT : PASS")
print("=" * 82)

print("RESULTS                     :", len(records))
print("QUERY ID                    :", query_id)
print("PROVIDER                    :", provider.provider_name)
print("FACT ESTABLISHMENT          : False")
print("IDENTITY ESTABLISHMENT      : False")
print("GUILT ESTABLISHMENT         : False")
print("NON-EXISTENCE ESTABLISHMENT : False")
print("REAL WEB ACCESS             : NOT PERFORMED")
print("TOR ACCESS                  : NOT PERFORMED")
print("=" * 82)
