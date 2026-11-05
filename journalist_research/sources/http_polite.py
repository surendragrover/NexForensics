"""
Polite HTTP fetcher shared by all DOA source connectors.

Rules enforced here (not optional):
  * identifying User-Agent
  * robots.txt honoured (cached per host)
  * minimum delay per host (default 3 s)
  * size cap, timeout
  * Cloudflare / bot-challenge pages are NEVER bypassed: they raise
    SourceBlocked, which callers must map to EvidenceStatus.NOT_AVAILABLE
  * every response is hashed (SHA-256) with a timezone-aware UTC fetch time
"""
from __future__ import annotations
import hashlib, time, threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.parse import urlparse
from urllib import robotparser

import requests

USER_AGENT = "NexForensics-DOA/0.2 (journalist research; +https://nexforensics.com)"
DEFAULT_DELAY = 3.0
MAX_BYTES = 200 * 1024 * 1024

CHALLENGE_MARKERS = (
    "cf-chl", "challenge-platform", "just a moment...", "verify you are human",
    "attention required! | cloudflare", "captcha",
)


class SourceBlocked(Exception):
    """Robots disallow, bot challenge, captcha or HTTP 403/429/5xx block."""


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content: bytes
    content_type: str
    sha256: str
    fetched_at_utc: str
    headers: Dict[str, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        for enc in ("utf-8", "cp1252", "latin-1"):
            try:
                return self.content.decode(enc)
            except UnicodeDecodeError:
                continue
        return self.content.decode("utf-8", errors="replace")


def looks_like_challenge(status: int, body: bytes) -> bool:
    head = body[:20000].decode("utf-8", errors="ignore").lower()
    if status in (403, 429, 503) and any(m in head for m in CHALLENGE_MARKERS):
        return True
    return status in (403, 429) or ("cf-chl" in head and "challenge" in head)


class PoliteFetcher:
    def __init__(self, delay: float = DEFAULT_DELAY, timeout: int = 60,
                 respect_robots: bool = True, session: Optional[requests.Session] = None):
        self.delay, self.timeout, self.respect_robots = delay, timeout, respect_robots
        self.s = session or requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT
        self._last: Dict[str, float] = {}
        self._robots: Dict[str, robotparser.RobotFileParser] = {}
        self._lock = threading.Lock()

    # -- robots -------------------------------------------------------
    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        rp = self._robots.get(base)
        if rp is None:
            rp = robotparser.RobotFileParser()
            try:
                r = self.s.get(base + "/robots.txt", timeout=20)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except requests.RequestException:
                rp.parse([])
            self._robots[base] = rp
        return rp.can_fetch(USER_AGENT, url)

    def _wait(self, host: str):
        with self._lock:
            gap = time.monotonic() - self._last.get(host, 0)
            if gap < self.delay:
                time.sleep(self.delay - gap)
            self._last[host] = time.monotonic()

    # -- fetch --------------------------------------------------------
    def request(self, method: str, url: str, *, headers=None, data=None,
                stream_to: Optional[str] = None) -> FetchResult:
        if not self.allowed(url):
            raise SourceBlocked(f"robots.txt disallows {url}")
        host = urlparse(url).netloc
        self._wait(host)
        r = self.s.request(method, url, headers=headers or {}, data=data,
                           timeout=self.timeout, stream=True, allow_redirects=True)
        h = hashlib.sha256(); buf = bytearray(); size = 0
        out = open(stream_to, "wb") if stream_to else None
        try:
            for chunk in r.iter_content(1 << 16):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise SourceBlocked(f"size cap exceeded for {url}")
                h.update(chunk)
                if out: out.write(chunk)
                elif method != "HEAD": buf.extend(chunk)
        finally:
            if out: out.close()
        body = bytes(buf)
        if method != "HEAD" and looks_like_challenge(r.status_code, body):
            raise SourceBlocked(f"HTTP {r.status_code} bot challenge / block at {url}")
        if r.status_code >= 500:
            raise SourceBlocked(f"HTTP {r.status_code} at {url}")
        return FetchResult(url=url, final_url=r.url, status=r.status_code, content=body,
                           content_type=r.headers.get("Content-Type", ""),
                           sha256=h.hexdigest(),
                           fetched_at_utc=datetime.now(timezone.utc).isoformat(),
                           headers={k.lower(): v for k, v in r.headers.items()})

    def get(self, url: str, **kw) -> FetchResult:
        return self.request("GET", url, **kw)

    def head(self, url: str, **kw) -> FetchResult:
        return self.request("HEAD", url, **kw)
