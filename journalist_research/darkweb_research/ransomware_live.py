"""
ransomware.live API PRO (free key, X-API-KEY) — leak-site monitoring metadata.

DOA uses ONLY the listing metadata (victim organisation, group, dates, country).
It never visits the leak sites and never downloads leaked data. A listing is a
CRIMINAL GROUP'S CLAIM, not a fact: status is always an UNVERIFIED lead, tier LOW.

Key: env RANSOMWARE_LIVE_API_KEY, or /home/nexforensics/app/.doa_secrets.env (600).
Limits: 60 req/min, 500k/month. Every response is snapshotted with SHA-256.
"""
from __future__ import annotations
import hashlib, json, os, time
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import quote

import requests

from .safety_filters import redact_credentials

API = "https://api-pro.ransomware.live"
USER_AGENT = "NexForensics-DOA/0.2 (+https://nexforensics.com)"
HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))
SECRETS = os.path.join(APP, ".doa_secrets.env")
STORE = os.path.join(HERE, "..", "runtime", "artifacts", "sources", "darkweb", "ransomware_live")
ATTRIBUTION = "Data: ransomware.live (leak-site monitoring). Listing = threat actor claim, unverified."


class KeyMissing(Exception):
    pass


def load_key() -> str:
    k = os.environ.get("RANSOMWARE_LIVE_API_KEY")
    if not k and os.path.exists(SECRETS):
        for line in open(SECRETS):
            if line.startswith("RANSOMWARE_LIVE_API_KEY="):
                k = line.split("=", 1)[1].strip()
    if not k:
        raise KeyMissing("RANSOMWARE_LIVE_API_KEY not configured")
    return k


class RansomwareLive:
    def __init__(self, key: Optional[str] = None, store: str = STORE, session=None, min_gap: float = 1.1):
        self.key = key or load_key()
        self.store = os.path.abspath(store)
        self.s = session or requests.Session()
        self.s.headers.update({"X-API-KEY": self.key, "User-Agent": USER_AGENT})
        self.min_gap, self._last = min_gap, 0.0

    def _get(self, path: str) -> Dict:
        gap = time.monotonic() - self._last
        if gap < self.min_gap:
            time.sleep(self.min_gap - gap)
        self._last = time.monotonic()
        r = self.s.get(API + path, timeout=45)
        if r.status_code == 429:
            raise RuntimeError("ransomware.live rate limit (429)")
        r.raise_for_status()
        raw = r.content
        sha = hashlib.sha256(raw).hexdigest()
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        os.makedirs(os.path.join(self.store, "responses"), exist_ok=True)
        p = os.path.join(self.store, "responses", f"{ts}_{sha[:12]}.json")
        if not os.path.exists(p):
            with open(p, "wb") as f:
                f.write(raw)
        data = r.json()
        data["_sha256"], data["_fetched_utc"], data["_snapshot"] = sha, ts, os.path.basename(p)
        return data

    def search(self, query: str) -> List[Dict]:
        data = self._get("/victims/search?q=" + quote(query))
        return [normalise(v, data) for v in data.get("victims", [])]


def normalise(v: Dict, resp: Dict) -> Dict:
    desc, n = redact_credentials(v.get("description") or "")
    return {
        "listing_id": v.get("id"),
        "organisation": v.get("post_title"),
        "group": v.get("group_name"),
        "published": v.get("published"),
        "discovered": v.get("discovered"),
        "website": v.get("website"),
        "country": v.get("country"),
        "sector": v.get("activity"),
        "description": desc[:1500],
        "redactions": n,
        "response_sha256": resp.get("_sha256"),
        "snapshot": resp.get("_snapshot"),
        "fetched_utc": resp.get("_fetched_utc"),
        "status": "UNVERIFIED",
        "match_kind": "NAME_ONLY_LEAD",
        "caveat": "Listing on a ransomware leak site is the attacker's claim; not verified.",
    }
