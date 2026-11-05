"""
Synthetic provider for PublicWebSearchConnector testing.

NO NETWORK ACCESS.
"""

from typing import List

from .search_engine import (
    PublicWebProvider,
    WebSearchItem,
)


class SyntheticPublicWebProvider(PublicWebProvider):

    provider_name = "synthetic_public_web"

    def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> List[WebSearchItem]:

        if not query.strip():
            raise ValueError("query is required")

        results = [
            WebSearchItem(
                url="https://example.test/public-web-result-1",
                title="Synthetic Public Web Result One",
                snippet=(
                    "Synthetic result representing a "
                    "public-web search result."
                ),
                rank=1,
                provider=self.provider_name,
                query=query,
                metadata={
                    "synthetic": True,
                    "fixture_id": "WEB-SYN-001",
                },
            ),
            WebSearchItem(
                url="https://example.test/public-web-result-2",
                title="Synthetic Public Web Result Two",
                snippet=(
                    "Second synthetic result used to verify "
                    "multi-result preservation."
                ),
                rank=2,
                provider=self.provider_name,
                query=query,
                metadata={
                    "synthetic": True,
                    "fixture_id": "WEB-SYN-002",
                },
            ),
        ]

        return results[:max_results]
