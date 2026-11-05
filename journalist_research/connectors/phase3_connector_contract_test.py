"""
DOA Phase 3 Connector Contract Test

Synthetic only.
No network access.
"""

from pathlib import Path
import sys

APP_ROOT = Path("/home/nexforensics/app")

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from journalist_research.connectors.base import (
    ConnectorResult,
    validate_connector_result,
)

from journalist_research.connectors.synthetic import (
    SyntheticSearchConnector,
    to_search_result_record,
)

from journalist_research.evidence.source_provenance import (
    build_source_record,
    build_document_record,
    build_provenance_chain,
)

from journalist_research.models import SourceType


def check(condition, label):
    if not condition:
        raise AssertionError(label)

    print(f"  {label:<50} : PASS")


print("=" * 80)
print("DOA PHASE 3 : SEARCH CONNECTOR CONTRACT TEST")
print("=" * 80)


# ------------------------------------------------------------
# 1. Connector import
# ------------------------------------------------------------

print("\n[1] CONNECTOR CONTRACT")

connector = SyntheticSearchConnector()

check(
    connector.connector_name == "synthetic",
    "Connector name"
)

check(
    connector.provider_name == "synthetic_provider",
    "Provider name"
)


# ------------------------------------------------------------
# 2. Synthetic search
# ------------------------------------------------------------

print("\n[2] SYNTHETIC SEARCH")

query_id = "QRY-PHASE3-001"

results = connector.search(
    query='"Example Corp" corporate history',
    query_id=query_id,
    max_results=2,
)

check(
    len(results) == 2,
    "Two synthetic search results"
)

check(
    all(isinstance(r, ConnectorResult) for r in results),
    "ConnectorResult type"
)


# ------------------------------------------------------------
# 3. Connector safety
# ------------------------------------------------------------

print("\n[3] CONNECTOR SAFETY")

for result in results:

    errors = validate_connector_result(result)

    check(
        errors == [],
        f"Result safety validation [{result.url}]"
    )

    check(
        result.fact_establishment is False,
        "Fact establishment blocked"
    )

    check(
        result.identity_establishment is False,
        "Identity establishment blocked"
    )

    check(
        result.guilt_establishment is False,
        "Guilt establishment blocked"
    )

    check(
        result.non_existence_establishment is False,
        "Non-existence establishment blocked"
    )


# ------------------------------------------------------------
# 4. Connector -> SearchResultRecord
# ------------------------------------------------------------

print("\n[4] CONNECTOR -> PROVENANCE SEARCH RESULT")

records = []

for result in results:

    record = to_search_result_record(result)

    records.append(record)

    check(
        record.query_id == query_id,
        "Query ID preserved"
    )

    check(
        record.query == result.query,
        "Query preserved"
    )

    check(
        record.url == result.url,
        "URL preserved"
    )

    check(
        record.title == result.title,
        "Title preserved"
    )

    check(
        record.provider == result.provider,
        "Provider preserved"
    )

    check(
        record.fact_establishment is False,
        "SearchResultRecord fact boundary"
    )


# ------------------------------------------------------------
# 5. SearchResultRecord -> SourceRecord
# ------------------------------------------------------------

print("\n[5] SEARCH RESULT -> SOURCE")

sources = []

for record in records:

    # source_provenance requires the real SourceType enum.
    # Convert the connector's provider-neutral string safely.
    source_type_name = result.source_type or "UNKNOWN"

    try:
        source_type = SourceType[source_type_name]
    except KeyError:
        source_type = SourceType.UNKNOWN

    source = build_source_record(
        record,
        source_type=source_type,
    )

    sources.append(source)

    check(
        source.url == record.url,
        "Source URL preserved"
    )

    check(
        source.result_id == record.result_id,
        "Result ID preserved"
    )

    check(
        source.provider == record.provider,
        "Source provider preserved"
    )

    check(
        source.fact_establishment is False,
        "Source fact boundary"
    )


# ------------------------------------------------------------
# 6. Source -> Document
# ------------------------------------------------------------

print("\n[6] SOURCE -> DOCUMENT")

documents = []

for source, result in zip(sources, results):

    document = build_document_record(
        source,
        result.content,
    )

    documents.append(document)

    check(
        document.source_id == source.source_id,
        "Document source linkage"
    )

    check(
        document.url == source.url,
        "Document URL preserved"
    )

    check(
        document.content_hash,
        "Content hash generated"
    )

    check(
        document.fact_establishment is False,
        "Document fact boundary"
    )


# ------------------------------------------------------------
# 7. Provenance chain
# ------------------------------------------------------------

print("\n[7] PROVENANCE CHAIN")

chains = []

for record, source, document in zip(
    records,
    sources,
    documents,
):

    chain = build_provenance_chain(
        record,
        source,
        document,
    )

    chains.append(chain)

    check(
        chain.query_id == record.query_id,
        "Chain query ID preserved"
    )

    check(
        chain.result_id == record.result_id,
        "Chain result ID preserved"
    )

    check(
        chain.source_id == source.source_id,
        "Chain source ID preserved"
    )

    check(
        chain.document_id == document.document_id,
        "Chain document ID preserved"
    )

    check(
        chain.fact_establishment is False,
        "Chain fact boundary"
    )


# ------------------------------------------------------------
# 8. Cross-source provenance
# ------------------------------------------------------------

print("\n[8] CROSS-SOURCE PROVENANCE")

check(
    len(records) == 2,
    "Multiple search results preserved"
)

check(
    len(sources) == 2,
    "Multiple sources preserved"
)

check(
    len(documents) == 2,
    "Multiple documents preserved"
)

check(
    len(chains) == 2,
    "Multiple provenance chains preserved"
)

check(
    records[0].url != records[1].url,
    "Independent URLs preserved"
)

check(
    sources[0].source_id != sources[1].source_id,
    "Independent source IDs preserved"
)

check(
    documents[0].document_id != documents[1].document_id,
    "Independent document IDs preserved"
)


# ------------------------------------------------------------
# 9. Global safety state
# ------------------------------------------------------------

print("\n[9] GLOBAL SAFETY STATE")

check(
    all(r.fact_establishment is False for r in records),
    "No fact established"
)

check(
    all(s.fact_establishment is False for s in sources),
    "No source establishes fact"
)

check(
    all(d.fact_establishment is False for d in documents),
    "No document establishes fact"
)

check(
    all(c.fact_establishment is False for c in chains),
    "No provenance chain establishes fact"
)


# ------------------------------------------------------------
# 10. Network boundary
# ------------------------------------------------------------

print("\n[10] NETWORK BOUNDARY")

check(
    connector.connector_name == "synthetic",
    "Synthetic connector only"
)

print(
    "  REAL WEB SEARCH                                  : NOT PERFORMED"
)

print(
    "  TOR / DARK-WEB ACCESS                           : NOT PERFORMED"
)


# ------------------------------------------------------------
# Final
# ------------------------------------------------------------

print("\n" + "=" * 80)
print("FINAL RESULT : PASS")
print("=" * 80)

print("CONNECTOR RESULTS           :", len(results))
print("SEARCH RESULT RECORDS       :", len(records))
print("SOURCE RECORDS              :", len(sources))
print("DOCUMENT RECORDS            :", len(documents))
print("PROVENANCE CHAINS           :", len(chains))
print("FACT ESTABLISHMENT          : False")
print("IDENTITY ESTABLISHMENT      : False")
print("GUILT ESTABLISHMENT         : False")
print("NON-EXISTENCE ESTABLISHMENT : False")
print("NETWORK ACCESS              : NOT PERFORMED")
print("TOR ACCESS                  : NOT PERFORMED")
print("FILES MODIFIED BY TEST      : False")
print("=" * 80)
