"""
Dark-web hits -> DOAPipeline InputDocuments.

All dark-web material is tier LOW (never ADEQUATE), so it can at most raise an
UNVERIFIED / REPORTED lead and never establish a fact, identity, guilt or
non-existence. Misses read "not found in the sources searched".
"""
from __future__ import annotations
from typing import List, Optional

from ..runtime.doa_pipeline import InputDocument, SubjectProfile
from .ransomware_live import API as RL_API, ATTRIBUTION, KeyMissing, RansomwareLive
from .onion_monitor import OnionMonitor

CHECK_RL = "Ransomware leak-site listings (ransomware.live)"
CHECK_ONION = "Dark-web watchlist pages (Tor)"


def _names(p: SubjectProfile) -> List[str]:
    return [n for n in [p.name, *p.aliases] if n and n.strip()]


def ransomware_documents(profile: SubjectProfile, client: Optional[RansomwareLive] = None) -> List[InputDocument]:
    try:
        client = client or RansomwareLive()
    except KeyMissing:
        return [InputDocument(document_id=f"rl-na-{profile.subject_id}", source_id="ransomware-live",
                              url=RL_API, title="ransomware.live", text="", tier="LOW",
                              source_kind="REPORT", status="UNAVAILABLE", checklist_item=CHECK_RL)]
    names = list(_names(profile)) + list(getattr(profile, "organizations", []) or [])
    docs, seen = [], set()
    for q in names:
        try:
            hits = client.search(q)
        except Exception as e:  # noqa: BLE001 — any failure is NOT_AVAILABLE, never "not found"
            return [InputDocument(document_id=f"rl-err-{profile.subject_id}", source_id="ransomware-live",
                                  url=RL_API, title="ransomware.live", text=str(e)[:200], tier="LOW",
                                  status="UNAVAILABLE", checklist_item=CHECK_RL)]
        for h in hits:
            if h["listing_id"] in seen: continue
            seen.add(h["listing_id"])
            text = (f"Ransomware group '{h['group']}' listed '{h['organisation']}' on its leak site "
                    f"(published {h['published']}, discovered {h['discovered']}, country {h['country']}). "
                    f"{h['caveat']}")
            docs.append(InputDocument(
                document_id=f"rl-{h['listing_id']}", source_id=f"rl-{h['listing_id']}",
                url=f"{RL_API}/victim/{h['listing_id']}", title=f"Leak-site listing: {h['organisation']}",
                text=text, tier="LOW", publisher=ATTRIBUTION, source_kind="REPORT",
                lineage_id=f"ransomware:{h['group']}:{h['organisation']}", published_at=None,
                checklist_item=CHECK_RL,
                mention={"name": q, "organizations": [h["organisation"]], "match_kind": "NAME_ONLY_LEAD",
                         "response_sha256": h["response_sha256"], "snapshot": h["snapshot"],
                         "status_cap": "UNVERIFIED"}))
    if not docs:
        docs.append(InputDocument(document_id=f"rl-none-{profile.subject_id}", source_id="ransomware-live",
                                  url=RL_API, title="ransomware.live", text="", tier="LOW",
                                  status="NO_RESULT", checklist_item=CHECK_RL,
                                  mention={"queries": names}))
    return docs


def onion_documents(profile: SubjectProfile, monitor: Optional[OnionMonitor] = None) -> List[InputDocument]:
    monitor = monitor or OnionMonitor()
    stored = monitor.stored_pages()
    if not stored:
        return [InputDocument(document_id=f"onion-na-{profile.subject_id}", source_id="onion-watchlist",
                              url="tor://watchlist", title="Dark-web watchlist", text="", tier="LOW",
                              status="UNAVAILABLE", checklist_item=CHECK_ONION,
                              mention={"reason": "no monitored pages stored yet"})]
    names = list(_names(profile)) + list(getattr(profile, "organizations", []) or [])
    res = {"pages": stored, "hits": monitor.search(names, stored)}
    ok = stored
    docs = [InputDocument(
        document_id=f"onion-{h['text_sha256'][:12]}-{h['offsets'][0]}", source_id=f"onion-{h['text_sha256'][:12]}",
        url=h["url"], title=f"Dark-web page {h['label']}".strip(), text=h["quote"], tier="LOW",
        source_kind="REPORT", lineage_id=f"onion:{h['url']}", checklist_item=CHECK_ONION,
        mention={"name": h["name"], "offsets": h["offsets"], "text_sha256": h["text_sha256"],
                 "match_kind": "NAME_ONLY_LEAD", "status_cap": "UNVERIFIED"}) for h in res["hits"]]
    if not docs:
        docs.append(InputDocument(document_id=f"onion-none-{profile.subject_id}", source_id="onion-watchlist",
                                  url="tor://watchlist", title="Dark-web watchlist", text="", tier="LOW",
                                  status="NO_RESULT" if ok else "UNAVAILABLE", checklist_item=CHECK_ONION,
                                  mention={"pages_searched": len(ok),
                                           "oldest_snapshot_utc": min(p["fetched_utc"] for p in ok)}))
    return docs
