"""
DOA Research Connectors

Connector boundary between search providers and the
journalist_research evidence/provenance layer.
"""

from .base import (
    ConnectorResult,
    SearchConnector,
    validate_connector_result,
)

__all__ = [
    "ConnectorResult",
    "SearchConnector",
    "validate_connector_result",
]
