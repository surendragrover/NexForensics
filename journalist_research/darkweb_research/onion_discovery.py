"""
Continuous onion-source discovery (no blind crawling).

Discovery feeds (addresses only, from published clearnet indexes):
  1. ransomware.live API PRO /groups + /groups/<g>  -> leak-site (DLS) onion addresses,
     with available / captcha / seized flags. Category RANSOMWARE_DLS (auto-watch).
  2. Ahmia public onion list https://ahmia.fi/onions/ (Ahmia filters abuse material;
     robots.txt allows /onions/). Category UNCLASSIFIED until probed.

Probe (per run, capped): fetch the HOME PAGE only (depth 0) of unclassified onions via
OnionMonitor.fetch(manual=True) -> same safety: robots, text-only, 2 MB, no redirects,
abuse tripwire (address is then BLOCKED forever and nothing is stored), credential redaction.
Classified by keywords into LEAK_FORUM / FORUM / NEWS_WHISTLEBLOWER / PASTE / MARKET / OTHER.
LEAK_FORUM, FORUM, PASTE, NEWS_WHISTLEBLOWER and RANSOMWARE_DLS are auto-added to the
watchlist (origin "auto"); MARKET / OTHER stay in the registry only. Manual watchlist
entries (origin "manual") are never removed.
"""
from __future__ import annotations
import json, os, re, time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests

from .onion_monitor import OnionMonitor, WATCHLIST, is_onion, ONION_RX
from .ransomware_live import RansomwareLive, KeyMissing
from .safety_filters import abuse_tripwire
from ..sources.http_polite import PoliteFetcher, USER_AGENT

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "..", "runtime", "artifacts", "sources", "darkweb", "registry.json")
AHMIA_LIST = "https://ahmia.fi/onions/"
WATCH_CATEGORIES = {"RANSOMWARE_DLS", "LEAK_FORUM", "FORUM", "PASTE", "NEWS_WHISTLEBLOWER"}
ADDR_RX = re.compile(r"\b([a-z2-7]{56}\.onion)\b")

CLASSIFY = [
    ("LEAK_FORUM", r"\b(leak|leaks|leaked|breach|breached|dump|dumps|database|combolist|stealer|logs)\b"),
    ("PASTE", r"\b(paste|pastebin|stikked|privatebin|ghostbin)\b"),
    ("NEWS_WHISTLEBLOWER", r"\b(securedrop|whistleblow\w*|newsroom|news|journalis\w*|press)\b"),
    ("FORUM", r"\b(forum|board|community|discussion|threads?|topics?|members)\b"),
    ("MARKET", r"\b(market|shop|vendor|escrow|cart|buy|sell|store)\b"),
]


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def classify(text: str) -> str:
    low = (text or "")[:20000].lower()
    scores = {cat: len(re.findall(rx, low)) for cat, rx in CLASSIFY}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else "OTHER"


class Registry:
    def __init__(self, path: str = REGISTRY):
        self.path = os.path.abspath(path)
        self.d: Dict[str, Dict] = json.load(open(self.path)) if os.path.exists(self.path) else {}

    def upsert(self, addr: str, source: str, **kw) -> bool:
        new = addr not in self.d
        r = self.d.setdefault(addr, {"first_seen": now_utc(), "sources": [], "category": "UNCLASSIFIED",
                                     "status": "NEW", "blocked": False})
        if source not in r["sources"]:
            r["sources"].append(source)
        for k, v in kw.items():
            if v is not None and not (k == "category" and r.get("blocked")):
                r[k] = v
        r["last_listed"] = now_utc()
        return new

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        json.dump(self.d, open(tmp, "w"), indent=1, sort_keys=True)
        os.replace(tmp, self.path)


def discover_ransomware(reg: Registry, client: Optional[RansomwareLive] = None, max_groups: int = 500) -> Dict:
    try:
        client = client or RansomwareLive()
    except KeyMissing:
        return {"status": "NOT_AVAILABLE", "reason": "key missing"}
    groups = client._get("/groups").get("groups", [])
    new = n = 0
    for g in groups[:max_groups]:
        name = g.get("group")
        try:
            det = client._get("/groups/" + requests.utils.quote(name))
        except Exception:  # noqa: BLE001
            continue
        for loc in det.get("locations") or []:
            fq = (loc.get("fqdn") or "").lower()
            if not ONION_RX.match(fq):
                continue
            n += 1
            cat = "RANSOMWARE_DLS" if (loc.get("type") or "").upper() == "DLS" else "RANSOMWARE_OTHER"
            new += reg.upsert(fq, "ransomware.live", category=cat, group=name, title=loc.get("title") or None,
                              rl_available=loc.get("available"), rl_captcha=loc.get("captcha"),
                              rl_seized=loc.get("seized"),
                              status="LISTED")
    return {"status": "OK", "groups": len(groups), "onions": n, "new": new}


def discover_ahmia(reg: Registry, fetcher: Optional[PoliteFetcher] = None) -> Dict:
    f = fetcher or PoliteFetcher()
    r = f.get(AHMIA_LIST)
    addrs = sorted(set(ADDR_RX.findall(r.text if isinstance(r.text, str) else r.text())))
    new = sum(reg.upsert(a, "ahmia") for a in addrs)
    return {"status": "OK", "listed": len(addrs), "new": new, "sha256": r.sha256}


def probe(reg: Registry, monitor: OnionMonitor, limit: int = 60) -> Dict:
    todo = [a for a, r in reg.d.items() if r["category"] == "UNCLASSIFIED" and not r["blocked"]
            and r.get("status") in ("NEW", "LISTED", "NOT_AVAILABLE")
            and (r.get("probe_attempts", 0) < 3)]
    todo.sort(key=lambda a: reg.d[a].get("probe_attempts", 0))
    out = {"probed": 0, "ok": 0, "blocked": 0, "unavailable": 0, "by_category": {}}
    for a in todo[:limit]:
        rec = reg.d[a]
        res = monitor.fetch(f"http://{a}/", manual=True, label="discovery-probe")
        rec["probe_attempts"] = rec.get("probe_attempts", 0) + 1
        rec["last_checked"] = now_utc()
        out["probed"] += 1
        if res["status"] == "DISCARDED_SAFETY" or abuse_tripwire(rec.get("title") or ""):
            rec.update(blocked=True, status="BLOCKED_SAFETY", category="BLOCKED")
            out["blocked"] += 1
            continue
        if res["status"] != "OK":
            rec["status"] = "NOT_AVAILABLE"; out["unavailable"] += 1
            continue
        cat = classify(res["text"])
        title = res["text"][:120]
        rec.update(status="OK", category=cat, title=title)
        out["ok"] += 1
        out["by_category"][cat] = out["by_category"].get(cat, 0) + 1
    return out


def build_watchlist(reg: Registry, path: str = WATCHLIST) -> Dict:
    cur = json.load(open(path)) if os.path.exists(path) else []
    manual = [w for w in cur if w.get("origin", "manual") == "manual" and is_onion(w.get("url", ""))]
    murls = {w["url"] for w in manual}
    auto = []
    for a, r in sorted(reg.d.items()):
        if r.get("blocked") or r["category"] not in WATCH_CATEGORIES:
            continue
        if r.get("rl_seized") or r.get("rl_captcha"):
            continue
        url = f"http://{a}/"
        if url in murls:
            continue
        auto.append({"url": url, "label": (r.get("group") or r.get("title") or "")[:80],
                     "category": r["category"], "origin": "auto"})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    json.dump(manual + auto, open(tmp, "w"), indent=1)
    os.replace(tmp, path)
    return {"manual": len(manual), "auto": len(auto)}
