"""
Tamper-evident audit chain for DOA (MariaDB table doa_audit_chain).

Each entry stores the SHA-256 of what it records (a dossier result, a PDF, a source snapshot)
plus prev_hash; entry_hash = SHA-256(prev_hash | event_type | ref_id | payload_sha256 | created_at).
BEFORE UPDATE / BEFORE DELETE triggers refuse edits; verify() recomputes the whole chain, so a
change made by anyone who drops the triggers is still detected.

  venv/bin/python -m journalist_research.jobs.audit_chain --verify
  venv/bin/python -m journalist_research.jobs.audit_chain --init
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from datetime import datetime, timezone
from typing import Dict, Optional

GENESIS = "0" * 64
DDL = """CREATE TABLE IF NOT EXISTS doa_audit_chain (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  created_at VARCHAR(32) NOT NULL,
  event_type VARCHAR(48) NOT NULL,
  ref_id VARCHAR(128) NOT NULL,
  payload_sha256 CHAR(64) NOT NULL,
  details JSON NULL,
  prev_hash CHAR(64) NOT NULL,
  entry_hash CHAR(64) NOT NULL UNIQUE,
  KEY k_ref (ref_id)) CHARACTER SET utf8mb4"""
TRIGGERS = [
    ("doa_audit_chain_no_update", "BEFORE UPDATE"),
    ("doa_audit_chain_no_delete", "BEFORE DELETE"),
]


def entry_hash(prev: str, event_type: str, ref_id: str, payload_sha: str, created_at: str) -> str:
    return hashlib.sha256("|".join([prev, event_type, ref_id, payload_sha, created_at]).encode()).hexdigest()


def _conn():
    from .db import _conn as c
    return c()


def _conn_app():
    from .db import _conn_app as c
    return c()


def init(conn=None) -> str:
    c = conn or _conn(); cur = c.cursor()
    cur.execute(DDL)
    for name, when in TRIGGERS:
        cur.execute("SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema=DATABASE() AND trigger_name=%s", (name,))
        if not cur.fetchone()[0]:
            cur.execute(f"CREATE TRIGGER {name} {when} ON doa_audit_chain FOR EACH ROW "
                        "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'doa_audit_chain is append-only'")
    c.commit()
    if conn is None: c.close()
    return "OK"


def append(event_type: str, ref_id: str, payload_sha256: str, details: Optional[Dict] = None, conn=None) -> Dict:
    c = conn or _conn_app(); cur = c.cursor()
    cur.execute("SELECT GET_LOCK('doa_audit_chain', 10)")
    try:
        cur.execute("SELECT entry_hash FROM doa_audit_chain ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        prev = row[0] if row else GENESIS
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        h = entry_hash(prev, event_type, ref_id, payload_sha256, now)
        cur.execute("INSERT INTO doa_audit_chain (created_at,event_type,ref_id,payload_sha256,details,prev_hash,entry_hash) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (now, event_type[:48], ref_id[:128], payload_sha256, json.dumps(details or {}, ensure_ascii=False), prev, h))
        c.commit()
    finally:
        cur.execute("SELECT RELEASE_LOCK('doa_audit_chain')")
        if conn is None: c.close()
    return {"entry_hash": h, "prev_hash": prev, "created_at": now}


def verify(conn=None) -> Dict:
    c = conn or _conn(); cur = c.cursor()
    cur.execute("SELECT id,created_at,event_type,ref_id,payload_sha256,prev_hash,entry_hash FROM doa_audit_chain ORDER BY id")
    prev, n, bad = GENESIS, 0, []
    for (i, ca, et, ref, ps, ph, eh) in cur.fetchall():
        n += 1
        if ph != prev:
            bad.append({"id": i, "problem": "prev_hash does not link to the previous entry"})
        if entry_hash(ph, et, ref, ps, ca) != eh:
            bad.append({"id": i, "problem": "entry_hash does not match its contents"})
        prev = eh
    if conn is None: c.close()
    return {"entries": n, "ok": not bad, "problems": bad[:20], "head": prev}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args(argv)
    if a.init:
        print("init:", init())
    if a.verify or not a.init:
        r = verify(); print(json.dumps(r, indent=1))
        return 0 if r["ok"] else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
