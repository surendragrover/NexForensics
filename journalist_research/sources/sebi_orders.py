"""
SEBI enforcement orders connector (free, primary official source).

Listing:   HomeAction.do?doListing=yes&sid=2&ssid=9&smid=<n>  (25 newest per category, GET)
Order page: <...>_<id>.html  -> iframe ?file=<sebi_data/attachdocs/...pdf>
Each order: PDF downloaded once, text extracted, stored append-only under
  runtime/artifacts/sources/sebi/<order_id>/{order.pdf,text.txt,meta.json}
plus one JSON line per order in runtime/artifacts/sources/sebi/index.jsonl.

search(name) works on the local extracted corpus. A name hit is a LEAD,
never an identity match: identity needs a non-name anchor downstream.
"""
from __future__ import annotations
import json, os, re, html, gzip, fcntl
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Iterable, List, Optional, Dict

from .http_polite import PoliteFetcher, SourceBlocked
from ..extraction.pdf_text import extract_pdf_bytes

BASE = "https://www.sebi.gov.in"
LIST_URL = BASE + "/sebiweb/home/HomeAction.do?doListing=yes&sid=2&s=0&ssid=9&smid={smid}"
AJAX_URL = BASE + "/sebiweb/ajax/home/getnewslistinfo.jsp"     # pagination (POST), verified 2026-11-05
TOTAL_RE = re.compile(r"of\s+([\d,]+)\s+records", re.I)
CATEGORY_SMIDS = (1, 2, 3, 4, 5, 6, 7)       # verified 2026-11-05: all return listings
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(HERE, "runtime", "artifacts", "sources", "sebi")

ROW_RE = re.compile(
    r"<td[^>]*>\s*([A-Z][a-z]{2} \d{2}, \d{4})\s*</td>\s*<td[^>]*>\s*<a[^>]*href=['\"]"
    r"(https://www\.sebi\.gov\.in/enforcement/orders/[^'\"]+?_(\d+)\.html)['\"][^>]*>(.*?)</a>",
    re.S | re.I)
PDF_RE = re.compile(r"file=((?:https?://www\.sebi\.gov\.in)?/sebi_data/[^'\"&\s>]+?\.pdf)", re.I)
CAT_RE = re.compile(r"<li>\s*([^<]{3,80}?)\s*</li>\s*</ul>", re.I)


@dataclass
class SebiOrder:
    order_id: str
    title: str
    order_date: str          # ISO date (DAY precision, as listed by SEBI)
    page_url: str
    category: str = ""
    pdf_url: str = ""
    raw_sha256: str = ""
    text_sha256: str = ""
    page_count: int = 0
    needs_ocr: bool = False
    ocr_status: str = ""
    fetched_at_utc: str = ""
    extractor_version: str = ""
    status: str = "NOT_ASSESSED"
    source_tier: str = "PRIMARY_OFFICIAL"
    document_type: str = "REGULATORY_ORDER"
    publisher: str = "Securities and Exchange Board of India"
    error: str = ""
    pdf_bytes: int = 0
    stored: str = "TEXT_ONLY"


def parse_listing(page_html: str) -> List[SebiOrder]:
    out = []
    for d, url, oid, title in ROW_RE.findall(page_html):
        t = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
        iso = datetime.strptime(d, "%b %d, %Y").date().isoformat()
        out.append(SebiOrder(order_id=oid, title=t, order_date=iso, page_url=url))
    return out


def parse_pdf_url(order_html: str) -> Optional[str]:
    m = PDF_RE.search(order_html)
    if not m:
        return None
    u = m.group(1)
    return u if u.lower().startswith("http") else BASE + u


class SebiOrders:
    def __init__(self, fetcher: Optional[PoliteFetcher] = None, store: str = STORE, text_only: bool = True,
                 ocr: bool = True):
        """text_only (default, Surendra 2026-11-05 "text hi rakho"): keep gzip text + PDF SHA-256 + URL,
        never store the PDF. Proof = re-download pdf_url and compare raw_sha256."""
        self.f = fetcher or PoliteFetcher()
        self.store = store
        self.text_only = text_only
        self.ocr = ocr          # backfill runs with ocr=False -> NEEDS_OCR, OCR queued later
        os.makedirs(store, exist_ok=True)
        self.index_path = os.path.join(store, "index.jsonl")

    def known_ids(self) -> set:
        if not os.path.exists(self.index_path):
            return set()
        with open(self.index_path, encoding="utf-8") as fh:
            return {json.loads(l)["order_id"] for l in fh if l.strip()}

    def list_latest(self, smids: Iterable[int] = CATEGORY_SMIDS) -> List[SebiOrder]:
        orders = []
        for smid in smids:
            r = self.f.get(LIST_URL.format(smid=smid))
            page = r.text
            for o in parse_listing(page):
                o.category = f"smid={smid}"
                orders.append(o)
        return orders

    def list_page(self, smid: int, page: int) -> Dict:
        """page 0 = GET listing; page n>0 = ajax POST (needs the listing's session cookie + Referer)."""
        ref = LIST_URL.format(smid=smid)
        if page == 0 or not self.f.s.cookies:
            r0 = self.f.get(ref)
            if page == 0:
                t = r0.text
                m = TOTAL_RE.search(t)
                return {"orders": parse_listing(t), "total": int(m.group(1).replace(",", "")) if m else None}
        data = {"nextValue": str(page), "next": "n", "search": "", "fromDate": "", "toDate": "",
                "fromYear": "", "toYear": "", "deptId": "-1", "sid": "2", "ssid": "9", "smid": str(smid),
                "ssidhidden": "9", "intmid": "-1", "sText": "Enforcement", "ssText": "Orders",
                "smText": "", "doDirect": str(page)}
        r = self.f.request("POST", AJAX_URL, data=data,
                           headers={"Referer": ref, "X-Requested-With": "XMLHttpRequest"})
        t = r.text
        m = TOTAL_RE.search(t)
        return {"orders": parse_listing(t), "total": int(m.group(1).replace(",", "")) if m else None}

    def _text_path(self, oid: str) -> Optional[str]:
        for n in ("text_ocr.txt.gz", "text.txt.gz", "text.txt"):
            p = os.path.join(self.store, oid, n)
            if os.path.exists(p):
                return p
        return None

    def read_text(self, oid: str) -> str:
        p = self._text_path(oid)
        if not p:
            return ""
        if p.endswith(".gz"):
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                return fh.read()
        return open(p, encoding="utf-8").read()

    def ingest(self, order: SebiOrder) -> SebiOrder:
        odir = os.path.join(self.store, order.order_id)
        if os.path.exists(os.path.join(odir, "meta.json")):
            return order  # append-only: never re-fetch / overwrite
        try:
            page = self.f.get(order.page_url)
            pdf_url = parse_pdf_url(page.text)
            cm = re.search(r"Orders\s*:\s*(?:</span>)?\s*(?:<[^>]+>\s*)*([A-Za-z][^<\n]{2,90})", page.text)
            if cm: order.category = html.unescape(cm.group(1)).strip()
            if not pdf_url:
                order.status, order.error = "NOT_AVAILABLE", "no PDF link on order page"
            else:
                order.pdf_url = pdf_url
                pdf = self.f.get(pdf_url)
                ex = extract_pdf_bytes(pdf.content, ocr=self.ocr)
                os.makedirs(odir, exist_ok=True)
                if not self.text_only:
                    with open(os.path.join(odir, "order.pdf"), "wb") as fh: fh.write(pdf.content)
                with gzip.open(os.path.join(odir, "text.txt.gz"), "wt", encoding="utf-8", compresslevel=9) as fh:
                    fh.write(ex.text)
                order.pdf_bytes = len(pdf.content)
                order.stored = "TEXT_ONLY" if self.text_only else "PDF+TEXT"
                order.raw_sha256, order.text_sha256 = ex.raw_sha256, ex.text_sha256
                order.page_count, order.needs_ocr, order.ocr_status = ex.page_count, ex.needs_ocr, ex.ocr_status
                order.extractor_version, order.fetched_at_utc = ex.extractor_version, pdf.fetched_at_utc
                order.error = ex.error
                order.status = "EXTRACTED" if ex.page_count and not ex.needs_ocr else (
                    "NEEDS_OCR" if ex.needs_ocr else "NOT_AVAILABLE")
        except SourceBlocked as e:
            order.status, order.error = "NOT_AVAILABLE", str(e)
        if order.status == "NOT_AVAILABLE":
            with open(os.path.join(self.store, "failures.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(order), ensure_ascii=False) + "\n")
            return order
        os.makedirs(odir, exist_ok=True)
        with open(os.path.join(self.store, ".write.lock"), "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)              # daily sync + backfill may run together
            if os.path.exists(os.path.join(odir, "meta.json")):
                return order
            with open(os.path.join(odir, "meta.json"), "w", encoding="utf-8") as fh:
                json.dump(asdict(order), fh, ensure_ascii=False, indent=1)
            with open(self.index_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(order), ensure_ascii=False) + "\n")
        return order

    def sync(self, limit: Optional[int] = None, smids: Iterable[int] = CATEGORY_SMIDS) -> Dict:
        known = self.known_ids()
        new = [o for o in self.list_latest(smids) if o.order_id not in known]
        seen, todo = set(), []
        for o in new:
            if o.order_id not in seen:
                seen.add(o.order_id); todo.append(o)
        todo.sort(key=lambda o: o.order_date, reverse=True)   # newest first
        if limit: todo = todo[:limit]
        done = [self.ingest(o) for o in todo]
        return {"listed_new": len(new), "ingested": len(done),
                "by_status": {s: sum(1 for d in done if d.status == s) for s in {d.status for d in done}}}

    # -- local corpus search ------------------------------------------------
    def search(self, name: str, max_hits: int = 50) -> List[Dict]:
        """Case-insensitive whole-phrase search over extracted order text.
        Returns LEADS with page number and a short quote + offsets."""
        if not os.path.exists(self.index_path):
            return []
        pat = re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, name.split())) + r"(?!\w)", re.I)
        hits = []
        with open(self.index_path, encoding="utf-8") as fh:
            metas = list({(mm := json.loads(l))["order_id"]: mm for l in fh if l.strip()}.values())
        for m in metas:
            txt = self.read_text(m["order_id"])
            if not txt: continue
            for pno, ptxt in enumerate(txt.split("\n\f"), 1):
                for mt in pat.finditer(ptxt):
                    s, e = mt.start(), mt.end()
                    hits.append({"order_id": m["order_id"], "title": m["title"], "order_date": m["order_date"],
                                 "pdf_url": m["pdf_url"], "page": pno, "start": s, "end": e,
                                 "quote": " ".join(ptxt[max(0, s-160):e+160].split()),
                                 "raw_sha256": m["raw_sha256"], "source_tier": "PRIMARY_OFFICIAL",
                                 "match_kind": "NAME_ONLY_LEAD"})
                    if len(hits) >= max_hits: return hits
        return hits
