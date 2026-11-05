"""DB writes for source refresh. Used ONLY with --write-db (owner-approved).
Creates new doa_* tables only; never touches existing tables."""
from __future__ import annotations
import json, os
from typing import Dict

APP = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DDL = [
"""CREATE TABLE IF NOT EXISTS doa_uk_sanctions (
  unique_id VARCHAR(32) PRIMARY KEY,
  primary_name VARCHAR(512), aliases JSON, dobs JSON, nationalities JSON,
  designation_type VARCHAR(64), regime VARCHAR(255), date_designated VARCHAR(32),
  last_updated VARCHAR(32), record_sha256 CHAR(64), snapshot VARCHAR(32),
  data JSON, removed_at DATETIME NULL, updated_at DATETIME NOT NULL,
  KEY k_name (primary_name(100))) CHARACTER SET utf8mb4""",
"""CREATE TABLE IF NOT EXISTS doa_source_refresh_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY, source VARCHAR(64), snapshot VARCHAR(32),
  raw_sha256 CHAR(64), summary JSON, created_at DATETIME NOT NULL) CHARACTER SET utf8mb4""",
]


def _conn():
    import pymysql
    env = {}
    for l in open(os.path.join(APP, ".env")):
        if "=" in l and not l.lstrip().startswith("#"):
            k, v = l.strip().split("=", 1); env[k.strip()] = v.strip().strip("\"'")
    return pymysql.connect(host=env.get("DB_HOST", "localhost"), user=env["DB_USER"],
                           password=env["DB_PASSWORD"], database=env["DB_NAME"], charset="utf8mb4", local_infile=True)


def upsert_uk_sanctions(recs: Dict[str, Dict], d: Dict, summary: Dict) -> str:
    c = _conn(); cur = c.cursor()
    for q in DDL: cur.execute(q)
    sql = """INSERT INTO doa_uk_sanctions VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,UTC_TIMESTAMP())
             ON DUPLICATE KEY UPDATE primary_name=VALUES(primary_name), aliases=VALUES(aliases),
             dobs=VALUES(dobs), nationalities=VALUES(nationalities), designation_type=VALUES(designation_type),
             regime=VALUES(regime), date_designated=VALUES(date_designated), last_updated=VALUES(last_updated),
             record_sha256=VALUES(record_sha256), snapshot=VALUES(snapshot), data=VALUES(data),
             removed_at=NULL, updated_at=UTC_TIMESTAMP()"""
    rows = [(u, (r["names"] or r["aliases"] or [""])[0][:512], json.dumps(r["aliases"], ensure_ascii=False),
             json.dumps(r["dobs"]), json.dumps(r["nationalities"], ensure_ascii=False), r["designation_type"][:64],
             r["regime"][:255], r["date_designated"][:32], r["last_updated"][:32], r["record_sha256"],
             summary["snapshot"], json.dumps(r, ensure_ascii=False)) for u, r in recs.items()]
    for i in range(0, len(rows), 500):
        cur.executemany(sql, rows[i:i+500])
    if d["removed"]:
        cur.executemany("UPDATE doa_uk_sanctions SET removed_at=UTC_TIMESTAMP() WHERE unique_id=%s AND removed_at IS NULL",
                        [(u,) for u in d["removed"]])
    cur.execute("INSERT INTO doa_source_refresh_log (source,snapshot,raw_sha256,summary,created_at) VALUES (%s,%s,%s,%s,UTC_TIMESTAMP())",
                ("uk_sanctions", summary["snapshot"], summary["raw_sha256"], json.dumps(summary)))
    c.commit(); c.close()
    return f"UPSERTED {len(rows)}, marked removed {len(d['removed'])}"
