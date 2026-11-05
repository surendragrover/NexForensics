"""
Bridge: local free-source corpora -> DOAPipeline InputDocuments.

  SEBI orders     : local extracted corpus (sebi_orders.SebiOrders.search)
  UK Sanctions    : latest FCDO snapshot (uk_sanctions records.json)

Every hit is a NAME LEAD; identity is decided by DOAPipeline.resolve_identity
using non-name anchors (DOB, city, organisation). A miss becomes a NO_RESULT
document so coverage reads "not found in the sources searched", never
"does not exist". Coverage notes state how much of each source was searched.
"""
from __future__ import annotations
import json, os, re, unicodedata
from typing import List, Optional

from ..runtime.doa_pipeline import InputDocument, SubjectProfile
from . import sebi_orders, uk_sanctions

CHECK_SEBI = "SEBI orders"
CHECK_UK = "UK Sanctions List"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())


def _iso_dob(raw: Optional[str]) -> Optional[str]:
    """UKSL D.O.B is dd/mm/yyyy; partial dates (00/00/1970) are NOT turned into anchors."""
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", (raw or "").strip())
    if not m or m.group(1) == "00" or m.group(2) == "00":
        return None
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"


def _names(profile: SubjectProfile) -> List[str]:
    return [n for n in [profile.name, *profile.aliases] if n and n.strip()]


def sebi_documents(profile: SubjectProfile, store: Optional[str] = None) -> List[InputDocument]:
    so = sebi_orders.SebiOrders(store=store or sebi_orders.STORE)
    corpus = len(so.known_ids())
    docs, seen = [], set()
    for n in _names(profile):
        for h in so.search(n):
            key = (h["order_id"], h["page"], h["start"])
            if key in seen: continue
            seen.add(key)
            docs.append(InputDocument(
                document_id=f"sebi-{h['order_id']}-p{h['page']}-{h['start']}",
                source_id=f"sebi-{h['order_id']}", url=h["pdf_url"], title=h["title"],
                text=h["quote"], tier="PRIMARY_OFFICIAL",
                publisher="Securities and Exchange Board of India", source_kind="RECORD",
                lineage_id=f"sebi:{h['order_id']}", published_at=h["order_date"],
                checklist_item=CHECK_SEBI,
                mention={"name": n, "page": h["page"], "offsets": [h["start"], h["end"]],
                         "raw_sha256": h["raw_sha256"], "match_kind": h["match_kind"],
                         "corpus_orders_searched": corpus}))
    if not docs:
        docs.append(InputDocument(document_id=f"sebi-none-{profile.subject_id}", source_id="sebi-corpus",
                                  url=sebi_orders.BASE + "/enforcement/orders.html",
                                  title="SEBI orders (local corpus)", text="", tier="PRIMARY_OFFICIAL",
                                  publisher="SEBI", source_kind="RECORD",
                                  status="NO_RESULT" if corpus else "UNAVAILABLE",
                                  checklist_item=CHECK_SEBI,
                                  mention={"corpus_orders_searched": corpus}))
    return docs


def uk_documents(profile: SubjectProfile, records_path: Optional[str] = None) -> List[InputDocument]:
    if records_path is None:
        st = json.load(open(uk_sanctions.STATE)) if os.path.exists(uk_sanctions.STATE) else {}
        records_path = (os.path.join(uk_sanctions.STORE, "snapshots", st["snapshot"], "records.json")
                        if st.get("snapshot") else None)
    if not records_path or not os.path.exists(records_path):
        return [InputDocument(document_id=f"uk-na-{profile.subject_id}", source_id="uk-sanctions",
                              url=uk_sanctions.URL, title="UK Sanctions List", text="",
                              tier="PRIMARY_OFFICIAL", source_kind="RECORD", status="UNAVAILABLE",
                              checklist_item=CHECK_UK)]
    recs = json.load(open(records_path))
    wanted = {_norm(n) for n in _names(profile)}
    docs = []
    for uid, r in recs.items():
        allnames = r["names"] + r["aliases"]
        hit = next((n for n in allnames if _norm(n) in wanted), None)
        if not hit: continue
        text = (f"UK Sanctions List entry {uid}: {'; '.join(allnames)}. Regime: {r['regime']}. "
                f"Designation type: {r['designation_type']}. Sanctions: {r['sanctions']}. "
                f"Designated: {r['date_designated']}. DOB: {', '.join(r['dobs']) or 'not listed'}. "
                f"Nationality: {', '.join(r['nationalities']) or 'not listed'}.")
        docs.append(InputDocument(
            document_id=f"uk-{uid}", source_id=f"uk-{uid}", url=uk_sanctions.URL,
            title=f"UK Sanctions List {uid}", text=text, tier="PRIMARY_OFFICIAL",
            publisher="UK FCDO", source_kind="RECORD", lineage_id=f"uksl:{uid}",
            published_at=None, checklist_item=CHECK_UK,
            mention={"name": hit, "dob": _iso_dob((r["dobs"] or [None])[0]), "dob_raw": r["dobs"],
                     "nationalities": r["nationalities"], "report_date": r["report_date"],
                     "record_sha256": r["record_sha256"], "match_kind": "NAME_ONLY_LEAD"}))
    if not docs:
        docs.append(InputDocument(document_id=f"uk-none-{profile.subject_id}", source_id="uk-sanctions",
                                  url=uk_sanctions.URL, title="UK Sanctions List", text="",
                                  tier="PRIMARY_OFFICIAL", source_kind="RECORD", status="NO_RESULT",
                                  checklist_item=CHECK_UK, mention={"records_searched": len(recs)}))
    return docs


def collect(profile: SubjectProfile, **kw) -> List[InputDocument]:
    return sebi_documents(profile, kw.get("sebi_store")) + uk_documents(profile, kw.get("uk_records"))
