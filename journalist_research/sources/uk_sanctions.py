"""
UK Sanctions List (FCDO) auto-updater. Official, free, static URL.
Since 28 Jan 2026 this is the ONLY UK designations source (OFSI ConList closed).

Run modes:
  check  : conditional HEAD (ETag/Last-Modified) -> UNCHANGED | CHANGED
  sync   : download if changed, snapshot (never overwritten), parse, diff vs last
           snapshot by Unique ID, write diff.json.  No DB write.
  sync --write-db : additionally upsert into table doa_uk_sanctions (new table,
           created if missing) + append a row to doa_source_refresh_log.
           Owner approval required before enabling this in cron.
A sanctions hit is a NAME LEAD only; identity needs DOB / nationality / ID anchors.
"""
from __future__ import annotations
import csv, hashlib, io, json, os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .http_polite import PoliteFetcher

URL = "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(HERE, "runtime", "artifacts", "sources", "uk_sanctions")
STATE = os.path.join(STORE, "state.json")
NAME_COLS = ["Name 1", "Name 2", "Name 3", "Name 4", "Name 5", "Name 6"]


def _load_state() -> Dict:
    return json.load(open(STATE)) if os.path.exists(STATE) else {}


def _save_state(st: Dict):
    os.makedirs(STORE, exist_ok=True)
    tmp = STATE + ".tmp"; json.dump(st, open(tmp, "w"), indent=1); os.replace(tmp, STATE)


def parse_csv(data: bytes) -> Dict[str, Dict]:
    """Group the denormalised CSV (one row per name x address) by Unique ID."""
    text = data.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    report_date = ""
    if lines and lines[0].lower().startswith("report date"):
        report_date = lines[0].split(":", 1)[1].strip(); lines = lines[1:]
    recs: Dict[str, Dict] = {}
    for row in csv.DictReader(io.StringIO("\n".join(lines))):
        uid = (row.get("Unique ID") or "").strip()
        if not uid: continue
        r = recs.setdefault(uid, {"unique_id": uid, "names": [], "aliases": [], "non_latin": [],
                                  "addresses": [], "dobs": [], "nationalities": [],
                                  "designation_type": row.get("Designation Type", ""),
                                  "regime": row.get("Regime Name", ""),
                                  "sanctions": row.get("Sanctions Imposed", ""),
                                  "date_designated": row.get("Date Designated", ""),
                                  "last_updated": row.get("Last Updated", ""),
                                  "un_ref": row.get("UN Reference Number", ""),
                                  "ofsi_group_id": row.get("OFSI Group ID", ""),
                                  "designation_source": row.get("Designation source", ""),
                                  "statement_of_reasons": (row.get("UK Statement of Reasons") or "")[:4000],
                                  "report_date": report_date})
        name = " ".join(x for x in (row.get(c, "").strip() for c in NAME_COLS) if x)
        bucket = "names" if (row.get("Name type") or "").lower().startswith("primary") else "aliases"
        for k, v in ((bucket, name), ("non_latin", row.get("Name non-latin script", "")),
                     ("dobs", row.get("D.O.B", "")), ("nationalities", row.get("Nationality(/ies)", ""))):
            v = (v or "").strip()
            if v and v not in r[k]: r[k].append(v)
        addr = ", ".join(x for x in (row.get(f"Address Line {i}", "").strip() for i in range(1, 7)) if x)
        cty = (row.get("Address Country") or "").strip()
        a = ", ".join(x for x in (addr, cty) if x)
        if a and a not in r["addresses"]: r["addresses"].append(a)
    for r in recs.values():
        r["record_sha256"] = hashlib.sha256(json.dumps(r, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return recs


def diff(old: Dict[str, Dict], new: Dict[str, Dict]) -> Dict[str, List[str]]:
    o, n = set(old), set(new)
    return {"added": sorted(n - o), "removed": sorted(o - n),
            "changed": sorted(u for u in o & n if old[u]["record_sha256"] != new[u]["record_sha256"])}


def check(f: Optional[PoliteFetcher] = None) -> Dict:
    f = f or PoliteFetcher(); st = _load_state()
    h = f.head(URL).headers
    changed = (h.get("etag"), h.get("last-modified")) != (st.get("etag"), st.get("last_modified"))
    return {"status": "CHANGED" if changed else "UNCHANGED", "etag": h.get("etag"),
            "last_modified": h.get("last-modified"), "previous": st.get("last_modified")}


def sync(f: Optional[PoliteFetcher] = None, write_db: bool = False, force: bool = False) -> Dict:
    f = f or PoliteFetcher(); st = _load_state()
    c = check(f)
    if c["status"] == "UNCHANGED" and not force:
        if write_db and st.get("snapshot") and st.get("db_snapshot") != st["snapshot"]:
            # list unchanged but DB never loaded from the current snapshot
            recs = json.load(open(os.path.join(STORE, "snapshots", st["snapshot"], "records.json")))
            from ..jobs.db import upsert_uk_sanctions
            res = upsert_uk_sanctions(recs, {"added": [], "removed": [], "changed": []},
                                      {"snapshot": st["snapshot"], "raw_sha256": st.get("raw_sha256", "")})
            st["db_snapshot"] = st["snapshot"]; _save_state(st)
            return {**c, "db": res}
        return c
    r = f.get(URL)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snap = os.path.join(STORE, "snapshots", stamp); os.makedirs(snap, exist_ok=False)
    open(os.path.join(snap, "UK-Sanctions-List.csv"), "wb").write(r.content)
    recs = parse_csv(r.content)
    json.dump(recs, open(os.path.join(snap, "records.json"), "w"), ensure_ascii=False)
    old = {}
    if st.get("snapshot"):
        p = os.path.join(STORE, "snapshots", st["snapshot"], "records.json")
        if os.path.exists(p): old = json.load(open(p))
    d = diff(old, recs)
    summary = {"status": "UPDATED", "snapshot": stamp, "raw_sha256": r.sha256,
               "fetched_at_utc": r.fetched_at_utc, "records": len(recs),
               "report_date": next(iter(recs.values()))["report_date"] if recs else "",
               "added": len(d["added"]), "removed": len(d["removed"]), "changed": len(d["changed"]),
               "db": "SKIPPED (dry run)"}
    json.dump({**summary, **d}, open(os.path.join(snap, "diff.json"), "w"), indent=1)
    if write_db:
        from ..jobs.db import upsert_uk_sanctions
        summary["db"] = upsert_uk_sanctions(recs, d, summary)
    _save_state({"etag": c["etag"], "last_modified": c["last_modified"], "snapshot": stamp,
                 "raw_sha256": r.sha256, "records": len(recs),
                 "db_snapshot": stamp if write_db else st.get("db_snapshot")})
    return summary
