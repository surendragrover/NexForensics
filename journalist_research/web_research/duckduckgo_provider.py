"""
DOA Phase 3C - Real Public Web Provider

Uses DuckDuckGo's public HTML search endpoint.

No API key is required.

This module is ONLY responsible for obtaining public search
results. It does not establish facts, identity, guilt, or
non-existence.
"""

from __future__ import annotations

from typing import List
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

from .search_engine import (
    PublicWebProvider,
    WebSearchItem,
)


class DuckDuckGoPublicWebProvider(PublicWebProvider):

    provider_name = "duckduckgo_public_web"

    SEARCH_URL = "https://html.duckduckgo.com/html/"

    USER_AGENT = (
        "NexForensics-DOA/1.0 "
        "(public-web-research; evidence-provenance)"
    )

    def __init__(
        self,
        timeout: int = 20,
    ):
        if timeout < 1:
            raise ValueError("timeout must be >= 1")

        self.timeout = timeout

    def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> List[WebSearchItem]:

        if not query or not query.strip():
            raise ValueError("query is required")

        if max_results < 1:
            raise ValueError(
                "max_results must be >= 1"
            )

        response = requests.post(
            self.SEARCH_URL,
            data={
                "q": query,
            },
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=self.timeout,
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        items: List[WebSearchItem] = []

        result_nodes = soup.select(
            ".result"
        )

        for node in result_nodes:

            link = node.select_one(
                ".result__a"
            )

            if link is None:
                continue

            href = link.get("href")

            if not href:
                continue

            title = link.get_text(
                " ",
                strip=True,
            )

            snippet_node = node.select_one(
                ".result__snippet"
            )

            snippet = (
                snippet_node.get_text(
                    " ",
                    strip=True,
                )
                if snippet_node
                else ""
            )

            href = urljoin(
                self.SEARCH_URL,
                href,
            )

            items.append(
                WebSearchItem(
                    url=href,
                    title=title,
                    snippet=snippet,
                    rank=len(items) + 1,
                    provider=self.provider_name,
                    query=query,
                    metadata={
                        "provider": self.provider_name,
                        "public_web": True,
                        "real_network": True,
                        "search_endpoint": self.SEARCH_URL,
                    },
                    search_performed=True,
                    fact_establishment=False,
                    identity_establishment=False,
                    guilt_establishment=False,
                    non_existence_establishment=False,
                )
            )

            if len(items) >= max_results:
                break

        return items
