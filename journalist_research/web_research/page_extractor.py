
"""
DOA Phase 4B - HTML Page Extractor

Extracts readable text and page metadata.
Does not claim that extracted statements are true.
Does not execute JavaScript.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List
from urllib.parse import urljoin

from bs4 import BeautifulSoup


@dataclass
class ExtractedPage:
    url: str
    title: str = ""
    text: str = ""
    description: str = ""
    author: str = ""
    published_at: str = ""
    modified_at: str = ""
    language: str = ""
    canonical_url: str = ""
    headings: List[str] = field(default_factory=list)
    links: List[Dict[str, str]] = field(default_factory=list)
    content_hash: str = ""
    extraction_status: str = "NOT_ASSESSED"
    metadata: Dict[str, Any] = field(default_factory=dict)


class PageExtractor:

    REMOVE_TAGS = [
        "script",
        "style",
        "noscript",
        "svg",
        "canvas",
        "iframe",
        "template",
        "nav",
        "footer",
        "header",
        "form",
        "button",
    ]

    @staticmethod
    def _meta(soup, *names):
        for name in names:
            node = soup.find(
                "meta",
                attrs={"name": name},
            )
            if node and node.get("content"):
                return node["content"].strip()

            node = soup.find(
                "meta",
                attrs={"property": name},
            )
            if node and node.get("content"):
                return node["content"].strip()

        return ""

    def extract(
        self,
        html: bytes,
        url: str,
        content_type: str = "text/html",
    ) -> ExtractedPage:

        if not html:
            return ExtractedPage(
                url=url,
                extraction_status="EMPTY_CONTENT",
            )

        charset = "utf-8"

        try:
            soup = BeautifulSoup(
                html,
                "html.parser",
            )

            if "text/plain" in content_type.lower():
                raw_text = html.decode(
                    charset,
                    errors="replace",
                ).strip()

                digest = hashlib.sha256(
                    raw_text.encode("utf-8")
                ).hexdigest()

                return ExtractedPage(
                    url=url,
                    text=raw_text,
                    content_hash=digest,
                    extraction_status=(
                        "EXTRACTED" if raw_text else "EMPTY_CONTENT"
                    ),
                    metadata={
                        "content_type": content_type,
                        "parser": "plain_text",
                    },
                )

            for tag in self.REMOVE_TAGS:
                for node in soup.find_all(tag):
                    node.decompose()

            title_node = soup.find("title")
            title = (
                title_node.get_text(" ", strip=True)
                if title_node else ""
            )

            description = self._meta(
                soup,
                "description",
                "og:description",
                "twitter:description",
            )

            author = self._meta(
                soup,
                "author",
                "article:author",
            )

            published_at = self._meta(
                soup,
                "article:published_time",
                "datePublished",
                "pubdate",
                "publish-date",
            )

            modified_at = self._meta(
                soup,
                "article:modified_time",
                "dateModified",
            )

            language = ""

            if soup.html:
                language = soup.html.get("lang", "")

            canonical_url = ""
            canonical = soup.find(
                "link",
                rel=lambda value: (
                    value and "canonical" in value
                ),
            )

            if canonical and canonical.get("href"):
                canonical_url = urljoin(
                    url,
                    canonical["href"],
                )

            headings = []

            for node in soup.find_all(
                ["h1", "h2", "h3"]
            ):
                value = node.get_text(
                    " ",
                    strip=True,
                )
                if value:
                    headings.append(value)

            main = (
                soup.find("main")
                or soup.find("article")
                or soup.body
                or soup
            )

            text = main.get_text(
                separator="\n",
                strip=True,
            )

            lines = [
                " ".join(line.split())
                for line in text.splitlines()
            ]

            lines = [
                line for line in lines
                if line
            ]

            normalized_text = "\n".join(lines)

            digest = hashlib.sha256(
                normalized_text.encode("utf-8")
            ).hexdigest()

            links = []

            for node in soup.find_all("a", href=True):
                label = node.get_text(
                    " ",
                    strip=True,
                )
                href = urljoin(
                    url,
                    node["href"],
                )

                if label and href.startswith(("http://", "https://")):
                    links.append({
                        "text": label[:300],
                        "url": href,
                    })

                if len(links) >= 100:
                    break

            if not normalized_text:
                status = "EMPTY_CONTENT"
            elif len(normalized_text) < 100:
                status = "LOW_CONTENT"
            else:
                status = "EXTRACTED"

            # This is a heuristic warning only.
            # No JavaScript execution is attempted.
            body_text = (
                soup.body.get_text(" ", strip=True)
                if soup.body else ""
            )

            script_markers = [
                "__NEXT_DATA__",
                "data-reactroot",
                "ng-version",
            ]

            render_hint = any(
                marker in str(html)
                for marker in script_markers
            )

            return ExtractedPage(
                url=url,
                title=title,
                text=normalized_text,
                description=description,
                author=author,
                published_at=published_at,
                modified_at=modified_at,
                language=language,
                canonical_url=canonical_url,
                headings=headings[:100],
                links=links,
                content_hash=digest,
                extraction_status=status,
                metadata={
                    "content_type": content_type,
                    "parser": "beautifulsoup_html.parser",
                    "text_length": len(normalized_text),
                    "heading_count": len(headings),
                    "link_count": len(links),
                    "possible_javascript_rendering": render_hint,
                    "javascript_executed": False,
                },
            )

        except Exception as exc:
            return ExtractedPage(
                url=url,
                extraction_status="EXTRACTION_ERROR",
                metadata={
                    "error": type(exc).__name__ + ": " + str(exc)[:300],
                },
            )
