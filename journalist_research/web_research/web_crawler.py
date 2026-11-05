
"""
DOA Phase 4A - Public Web Crawler

Fetches publicly accessible HTTP/HTTPS pages.
Includes redirect validation, public-IP checks, response
size limits, content-type checks and retrieval metadata.

No authentication bypass.
No private-network access.
No Tor access.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urljoin, urlparse

import requests


@dataclass
class CrawlResult:
    requested_url: str
    final_url: str
    status: str
    http_status: Optional[int] = None
    content_type: str = ""
    content: bytes = b""
    retrieved_at: str = ""
    redirect_chain: list = field(default_factory=list)
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class PublicWebCrawler:

    USER_AGENT = (
        "NexForensics-DOA/1.0 "
        "(public-web-research; contact: webmaster)"
    )

    def __init__(
        self,
        timeout: int = 20,
        max_bytes: int = 5_000_000,
        max_redirects: int = 5,
    ):
        if timeout < 1:
            raise ValueError("timeout must be positive")
        if max_bytes < 1024:
            raise ValueError("max_bytes must be at least 1024")
        if max_redirects < 0:
            raise ValueError("max_redirects cannot be negative")

        self.timeout = timeout
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects

    @staticmethod
    def validate_public_url(url: str) -> tuple:
        try:
            parsed = urlparse(url)

            if parsed.scheme not in ("http", "https"):
                return False, "UNSUPPORTED_SCHEME"

            if not parsed.hostname:
                return False, "MISSING_HOST"

            if parsed.username or parsed.password:
                return False, "URL_CREDENTIALS_BLOCKED"

            host = parsed.hostname

            if host.lower() in ("localhost", "localhost.localdomain"):
                return False, "LOCAL_HOST_BLOCKED"

            try:
                addresses = [ipaddress.ip_address(host)]
            except ValueError:
                try:
                    addresses = [
                        ipaddress.ip_address(item[4][0])
                        for item in socket.getaddrinfo(
                            host,
                            parsed.port or (443 if parsed.scheme == "https" else 80),
                            type=socket.SOCK_STREAM,
                        )
                    ]
                except Exception:
                    return False, "DNS_RESOLUTION_FAILED"

            if not addresses:
                return False, "NO_IP_ADDRESS"

            for address in addresses:
                if not address.is_global:
                    return False, "NON_PUBLIC_IP_BLOCKED"

            return True, "VALID"

        except Exception:
            return False, "INVALID_URL"

    def fetch(self, url: str) -> CrawlResult:

        now = datetime.now(timezone.utc).isoformat()
        original_url = url
        current_url = url
        redirects = []

        for hop in range(self.max_redirects + 1):

            valid, reason = self.validate_public_url(current_url)

            if not valid:
                return CrawlResult(
                    requested_url=original_url,
                    final_url=current_url,
                    status="BLOCKED",
                    retrieved_at=now,
                    redirect_chain=redirects,
                    error=reason,
                )

            try:
                response = requests.get(
                    current_url,
                    headers={
                        "User-Agent": self.USER_AGENT,
                        "Accept": (
                            "text/html,application/xhtml+xml,"
                            "text/plain;q=0.9"
                        ),
                    },
                    timeout=self.timeout,
                    allow_redirects=False,
                    stream=True,
                )

                status_code = response.status_code

                if status_code in (301, 302, 303, 307, 308):

                    location = response.headers.get("Location")
                    response.close()

                    if not location:
                        return CrawlResult(
                            requested_url=original_url,
                            final_url=current_url,
                            status="REDIRECT_ERROR",
                            http_status=status_code,
                            retrieved_at=now,
                            redirect_chain=redirects,
                            error="REDIRECT_WITHOUT_LOCATION",
                        )

                    if hop >= self.max_redirects:
                        return CrawlResult(
                            requested_url=original_url,
                            final_url=current_url,
                            status="REDIRECT_LIMIT",
                            http_status=status_code,
                            retrieved_at=now,
                            redirect_chain=redirects,
                            error="MAX_REDIRECTS_EXCEEDED",
                        )

                    next_url = urljoin(current_url, location)
                    redirects.append({
                        "from": current_url,
                        "to": next_url,
                        "status": status_code,
                    })

                    current_url = next_url
                    continue

                content_type = response.headers.get(
                    "Content-Type", ""
                )

                content_length = response.headers.get(
                    "Content-Length"
                )

                if content_length:
                    try:
                        if int(content_length) > self.max_bytes:
                            response.close()
                            return CrawlResult(
                                requested_url=original_url,
                                final_url=current_url,
                                status="SIZE_LIMIT",
                                http_status=status_code,
                                content_type=content_type,
                                retrieved_at=now,
                                redirect_chain=redirects,
                                error="CONTENT_LENGTH_EXCEEDED",
                            )
                    except ValueError:
                        pass

                if status_code < 200 or status_code >= 300:
                    response.close()
                    return CrawlResult(
                        requested_url=original_url,
                        final_url=current_url,
                        status="HTTP_ERROR",
                        http_status=status_code,
                        content_type=content_type,
                        retrieved_at=now,
                        redirect_chain=redirects,
                        error=f"HTTP_{status_code}",
                    )

                media_type = content_type.split(";")[0].strip().lower()

                if media_type not in (
                    "text/html",
                    "application/xhtml+xml",
                    "text/plain",
                ):
                    response.close()
                    return CrawlResult(
                        requested_url=original_url,
                        final_url=current_url,
                        status="UNSUPPORTED_CONTENT",
                        http_status=status_code,
                        content_type=content_type,
                        retrieved_at=now,
                        redirect_chain=redirects,
                        error="UNSUPPORTED_MEDIA_TYPE",
                    )

                chunks = []
                total = 0

                for chunk in response.iter_content(65536):
                    if not chunk:
                        continue

                    total += len(chunk)

                    if total > self.max_bytes:
                        response.close()
                        return CrawlResult(
                            requested_url=original_url,
                            final_url=current_url,
                            status="SIZE_LIMIT",
                            http_status=status_code,
                            content_type=content_type,
                            retrieved_at=now,
                            redirect_chain=redirects,
                            error="STREAM_SIZE_LIMIT_EXCEEDED",
                        )

                    chunks.append(chunk)

                response.close()

                return CrawlResult(
                    requested_url=original_url,
                    final_url=current_url,
                    status="FETCHED",
                    http_status=status_code,
                    content_type=content_type,
                    content=b"".join(chunks),
                    retrieved_at=now,
                    redirect_chain=redirects,
                    metadata={
                        "content_length": total,
                        "server": response.headers.get("Server", ""),
                    },
                )

            except requests.exceptions.Timeout:
                return CrawlResult(
                    requested_url=original_url,
                    final_url=current_url,
                    status="TIMEOUT",
                    retrieved_at=now,
                    redirect_chain=redirects,
                    error="REQUEST_TIMEOUT",
                )

            except requests.exceptions.RequestException as exc:
                return CrawlResult(
                    requested_url=original_url,
                    final_url=current_url,
                    status="FETCH_ERROR",
                    retrieved_at=now,
                    redirect_chain=redirects,
                    error=type(exc).__name__ + ": " + str(exc)[:300],
                )

        return CrawlResult(
            requested_url=original_url,
            final_url=current_url,
            status="REDIRECT_LIMIT",
            retrieved_at=now,
            redirect_chain=redirects,
            error="MAX_REDIRECTS_EXCEEDED",
        )
