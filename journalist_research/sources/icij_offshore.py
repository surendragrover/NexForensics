"""
ICIJ Offshore Leaks bulk data (ODbL 1.0 database licence, attribution required:
"ICIJ Offshore Leaks Database"). Rarely updated, so we only check the
static LATEST zip with a HEAD request; when ETag/Last-Modified change we
download to a new staging snapshot and verify the zip.  Importing into the
existing offshore_* tables is a separate, owner-approved step.
Presence in the database does not mean wrongdoing (ICIJ's own caveat).
"""
from __future__ import annotations
import json, os, zipfile
from datetime import datetime, timezone
from typing import Dict, Optional

from .http_polite import PoliteFetcher

URL = "https://offshoreleaks-data.icij.org/offshoreleaks/csv/full-oldb.LATEST.zip"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(HERE, "runtime", "artifacts", "sources", "icij")
STATE = os.path.join(STORE, "state.json")
DB_IMPORTED_AT = "2026-07-15"   # offshore_entities create_time seen 2026-11-05


def check(f: Optional[PoliteFetcher] = None) -> Dict:
    f = f or PoliteFetcher()
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    h = f.head(URL).headers
    lm = h.get("last-modified", "")
    changed = (h.get("etag"), lm) != (st.get("etag"), st.get("last_modified"))
    return {"status": "CHANGED" if changed else "UNCHANGED", "etag": h.get("etag"), "last_modified": lm,
            "size_bytes": int(h.get("content-length") or 0), "previous": st.get("last_modified"),
            "db_imported_at": DB_IMPORTED_AT}


def sync(f: Optional[PoliteFetcher] = None, download: bool = False) -> Dict:
    f = f or PoliteFetcher(); c = check(f)
    if c["status"] == "UNCHANGED" or not download:
        return c
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snap = os.path.join(STORE, "snapshots", stamp); os.makedirs(snap, exist_ok=False)
    zp = os.path.join(snap, "full-oldb.zip")
    r = f.get(URL, stream_to=zp)
    with zipfile.ZipFile(zp) as z:
        bad = z.testzip(); names = z.namelist()
    out = {**c, "status": "DOWNLOADED" if bad is None else "CORRUPT", "snapshot": stamp,
           "raw_sha256": r.sha256, "files": names, "db": "NOT_IMPORTED (needs owner approval)"}
    json.dump(out, open(os.path.join(snap, "meta.json"), "w"), indent=1)
    if bad is None:
        os.makedirs(STORE, exist_ok=True)
        json.dump({"etag": c["etag"], "last_modified": c["last_modified"], "snapshot": stamp},
                  open(STATE, "w"), indent=1)
    return out
