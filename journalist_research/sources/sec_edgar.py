"""
SEC EDGAR (US) - free, public domain, no key. Fair-access: identifying UA, <=10 req/s (we do 1 per 3 s).

  full_text(name)   : EDGAR full-text search (efts.sec.gov/LATEST/search-index), filings since 2001,
                      phrase query. Returns filing-level LEADS (form, date, filer, document URL).
  companies(name)   : company/filer lookup (browse-edgar atom) -> CIK candidates.

A filing that mentions a name is a lead: the filing's text is SELF_REPORTED by the filer
(SEC is the publisher, not the author). Identity needs non-name anchors.
"""
from __future__ import annotations
import json, re, urllib.parse
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from .http_polite import PoliteFetcher, SourceBlocked

EFTS = "https://efts.sec.gov/LATEST/search-index?q={q}&dateRange=custom&startdt=2001-01-01"
BROWSE = ("https://www.sec.gov/cgi-bin/browse-edgar?company={q}&type=&dateb=&owner=include"
          "&count=20&action=getcompany&output=atom")


def _doc_url(hit: Dict) -> str:
    adsh, _, fname = hit["_id"].partition(":")
    cik = (hit["_source"].get("ciks") or ["0"])[0].lstrip("0") or "0"
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace('-', '')}/{fname}"


def parse_efts(data: bytes, max_hits: int = 20) -> Dict:
    j = json.loads(data.decode("utf-8", errors="replace"))
    hits = j.get("hits", {})
    out = []
    for h in hits.get("hits", [])[:max_hits]:
        s = h.get("_source", {})
        out.append({"adsh": s.get("adsh"), "form": s.get("form") or s.get("file_type"),
                    "file_date": s.get("file_date"), "filer": (s.get("display_names") or [""])[0],
                    "ciks": s.get("ciks", []), "file_type": s.get("file_type"),
                    "description": s.get("file_description"), "url": _doc_url(h),
                    "source_tier": "PRIMARY_OFFICIAL_SELF_REPORTED", "match_kind": "NAME_ONLY_LEAD"})
    tot = hits.get("total", {})
    return {"total": tot.get("value"), "total_relation": tot.get("relation"), "hits": out}


def parse_browse(data: bytes) -> List[Dict]:
    ns = {"a": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return []
    out = []
    for e in root.findall("a:entry", ns):
        content = e.find("a:content", ns)
        cik = name = ""
        if content is not None:
            cik = (content.findtext("a:cik", default="", namespaces=ns) or "").strip()
            name = (content.findtext("a:name", default="", namespaces=ns) or "").strip()
        title = (e.findtext("a:title", default="", namespaces=ns) or "").strip()
        m = re.search(r"\((\d{10})\)", title)
        out.append({"cik": cik or (m.group(1) if m else ""), "name": name or title})
    return out


class SecEdgar:
    def __init__(self, f: Optional[PoliteFetcher] = None):
        self.f = f or PoliteFetcher()

    def full_text(self, name: str, max_hits: int = 20) -> Dict:
        q = urllib.parse.quote(f'"{name}"')
        try:
            r = self.f.get(EFTS.format(q=q))
        except SourceBlocked as e:
            return {"status": "NOT_AVAILABLE", "reason": str(e), "hits": []}
        if r.status != 200:
            return {"status": "NOT_AVAILABLE", "reason": f"HTTP {r.status}", "hits": []}
        res = parse_efts(r.content, max_hits)
        res.update(status="OK" if res["hits"] else "NO_RESULT", query=name, sha256=r.sha256,
                   fetched_at_utc=r.fetched_at_utc)
        return res

    def companies(self, name: str) -> Dict:
        try:
            r = self.f.get(BROWSE.format(q=urllib.parse.quote(name)))
        except SourceBlocked as e:
            return {"status": "NOT_AVAILABLE", "reason": str(e), "companies": []}
        c = parse_browse(r.content)
        return {"status": "OK" if c else "NO_RESULT", "companies": c, "sha256": r.sha256}
