"""
Targeted .onion page monitor over Tor (socks5h://127.0.0.1:9050).

NOT a crawler: it fetches only
  (a) pages on the investigator-maintained watchlist (runtime/config/onion_watchlist.json), or
  (b) a single onion URL an investigator supplies for a case (manual=True),
and never follows links. Per page:
  * robots.txt honoured, 5 s per host, 2 MB cap, text content-types only;
  * media / archives / dumps refused by extension and content-type;
  * abuse tripwire -> page discarded, nothing stored but sha256(url) + reason;
  * credentials redacted before storage; raw HTML is NOT stored (only redacted text);
  * SHA-256 of the raw bytes and of the stored text, fetch time UTC.
Everything found is an UNVERIFIED lead (tier LOW). No forms, no logins, no captcha solving.
"""
from __future__ import annotations
import hashlib, json, os, re, time
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests

from .safety_filters import abuse_tripwire, content_type_ok, redact_credentials, url_ext_blocked
from ..sources.http_polite import PoliteFetcher, SourceBlocked, USER_AGENT

TOR_PROXY = os.environ.get("DOA_TOR_PROXY", "socks5h://127.0.0.1:9050")
MAX_BYTES = 2 * 1024 * 1024
HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, "..", "runtime")
WATCHLIST = os.path.join(RUNTIME, "config", "onion_watchlist.json")
STORE = os.path.join(RUNTIME, "artifacts", "sources", "darkweb", "onion")
ONION_RX = re.compile(r"^[a-z2-7]{56}\.onion$")


def tor_session() -> requests.Session:
    s = requests.Session()
    s.proxies = {"http": TOR_PROXY, "https": TOR_PROXY}
    s.headers["User-Agent"] = USER_AGENT
    return s


def is_onion(url: str) -> bool:
    return bool(ONION_RX.match((urlparse(url).hostname or "").lower()))


def load_watchlist(path: str = WATCHLIST) -> List[Dict]:
    if not os.path.exists(path):
        return []
    return [w for w in json.load(open(path)) if is_onion(w.get("url", ""))]


def _html_to_text(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for t in soup(["script", "style", "noscript", "img", "video", "audio", "iframe", "form"]):
            t.decompose()
        return " ".join(soup.get_text(" ").split())
    except ImportError:
        return " ".join(re.sub(r"<[^>]+>", " ", html).split())


class OnionMonitor:
    def __init__(self, store: str = STORE, session=None, watchlist_path: str = WATCHLIST):
        self.s = session or tor_session()
        self.fetcher = PoliteFetcher(delay=5.0, timeout=90, session=self.s)
        self.store = os.path.abspath(store)
        self.watchlist = load_watchlist(watchlist_path)
        os.makedirs(self.store, exist_ok=True)

    def _log(self, rec: Dict):
        with open(os.path.join(self.store, "fetch_log.jsonl"), "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def fetch(self, url: str, manual: bool = False, label: str = "") -> Dict:
        now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        url_sha = hashlib.sha256(url.encode()).hexdigest()
        base = {"url_sha256": url_sha, "fetched_utc": now, "manual": manual, "label": label}
        if not is_onion(url):
            return {**base, "url": url, "status": "REFUSED", "reason": "not a v3 .onion URL"}
        if not manual and url not in {w["url"] for w in self.watchlist}:
            return {**base, "url": url, "status": "REFUSED", "reason": "not on watchlist"}
        if url_ext_blocked(url):
            return {**base, "url": url, "status": "REFUSED", "reason": "media/archive/dump URL"}
        try:
            if not self.fetcher.allowed(url):
                raise SourceBlocked("robots.txt disallows")
            host = urlparse(url).netloc
            self.fetcher._wait(host)
            r = self.s.get(url, timeout=90, stream=True, allow_redirects=False)
            if r.is_redirect:
                rec = {**base, "url": url, "status": "NOT_AVAILABLE", "reason": f"redirect {r.status_code} not followed"}
                self._log(rec); return rec
            if not content_type_ok(r.headers.get("Content-Type", "")):
                r.close()
                rec = {**base, "url": url, "status": "REFUSED", "reason": "non-text content-type"}
                self._log(rec); return rec
            buf = bytearray()
            for chunk in r.iter_content(1 << 15):
                buf.extend(chunk)
                if len(buf) > MAX_BYTES:
                    r.close(); raise SourceBlocked("2 MB cap")
            if r.status_code >= 400:
                raise SourceBlocked(f"HTTP {r.status_code}")
        except (SourceBlocked, requests.RequestException) as e:
            rec = {**base, "url": url, "status": "NOT_AVAILABLE", "reason": str(e)[:200]}
            self._log(rec); return rec
        raw = bytes(buf)
        html = raw.decode(r.encoding or "utf-8", errors="replace")
        text = _html_to_text(html)
        if abuse_tripwire(text) or abuse_tripwire(url):
            rec = {**base, "status": "DISCARDED_SAFETY", "reason": "abuse indicators; nothing stored"}
            self._log(rec); return rec   # note: URL itself not logged
        text, nred = redact_credentials(text)
        text_sha = hashlib.sha256(text.encode()).hexdigest()
        latest = self._latest()
        prev = latest.get(url)
        if prev and prev["text_sha256"] == text_sha:          # unchanged: no new file
            p = os.path.join(self.store, prev["path"])
        else:
            d = os.path.join(self.store, "pages", url_sha[:16])
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, f"{now}_{text_sha[:12]}.txt")
            with open(p, "w", encoding="utf-8") as f:
                f.write(text)
        latest[url] = {"path": os.path.relpath(p, self.store), "text_sha256": text_sha,
                       "fetched_utc": now, "label": label, "changed": not (prev and prev["text_sha256"] == text_sha)}
        self._save_latest(latest)
        rec = {**base, "url": url, "status": "OK", "raw_sha256": hashlib.sha256(raw).hexdigest(),
               "text_sha256": text_sha, "redactions": nred, "chars": len(text),
               "path": os.path.relpath(p, self.store)}
        self._log(rec)
        return {**rec, "text": text}

    # -- latest-snapshot index ------------------------------------------
    def _latest(self) -> Dict:
        p = os.path.join(self.store, "latest.json")
        return json.load(open(p)) if os.path.exists(p) else {}

    def _save_latest(self, d: Dict):
        p = os.path.join(self.store, "latest.json"); tmp = p + ".tmp"
        json.dump(d, open(tmp, "w"), indent=1); os.replace(tmp, p)

    def refresh_watchlist(self, limit: int = 150, min_age_hours: float = 20.0) -> Dict:
        """Continuous monitor: re-fetch watchlist pages not fetched in the last min_age_hours."""
        latest = self._latest()
        cutoff = time.time() - min_age_hours * 3600
        def age(u):
            t = latest.get(u, {}).get("fetched_utc")
            return datetime.strptime(t, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).timestamp() if t else 0
        due = sorted([w for w in self.watchlist if age(w["url"]) < cutoff], key=lambda w: age(w["url"]))
        out = {"due": len(due), "fetched": 0, "ok": 0, "changed": 0, "discarded": 0, "unavailable": 0}
        for w in due[:limit]:
            r = self.fetch(w["url"], label=w.get("label", ""))
            out["fetched"] += 1
            if r["status"] == "OK":
                out["ok"] += 1
                out["changed"] += int(self._latest().get(w["url"], {}).get("changed", False))
            elif r["status"] == "DISCARDED_SAFETY":
                out["discarded"] += 1
            else:
                out["unavailable"] += 1
        return out

    def stored_pages(self) -> List[Dict]:
        pages = []
        for url, m in self._latest().items():
            fp = os.path.join(self.store, m["path"])
            if os.path.exists(fp):
                pages.append({"status": "OK", "url": url, "label": m.get("label", ""),
                              "text": open(fp, encoding="utf-8").read(),
                              "text_sha256": m["text_sha256"], "fetched_utc": m["fetched_utc"]})
        return pages

    def search_store(self, names: List[str]) -> List[Dict]:
        """Search the latest stored snapshot of every monitored page (no network)."""
        return self.search(names, self.stored_pages())

    def search(self, names: List[str], pages: List[Dict]) -> List[Dict]:
        """Exact (case-insensitive, whitespace-normalised) name hits in fetched page text."""
        hits = []
        for pg in pages:
            if pg.get("status") != "OK":
                continue
            low = pg["text"].lower()
            for n in names:
                key = " ".join(n.lower().split())
                for m in re.finditer(re.escape(key), low):
                    a, b = max(0, m.start() - 200), min(len(low), m.end() + 200)
                    hits.append({"name": n, "url": pg["url"], "label": pg.get("label", ""),
                                 "quote": pg["text"][a:b], "offsets": [m.start(), m.end()],
                                 "text_sha256": pg["text_sha256"], "fetched_utc": pg["fetched_utc"],
                                 "status": "UNVERIFIED", "match_kind": "NAME_ONLY_LEAD"})
        return hits

    def check_watchlist(self, names: List[str]) -> Dict:
        pages = [self.fetch(w["url"], label=w.get("label", "")) for w in self.watchlist]
        return {"pages": [{k: v for k, v in p.items() if k != "text"} for p in pages],
                "hits": self.search(names, pages)}
