"""
Import an ICIJ Offshore Leaks snapshot into NEW tables doa_icij_* (owner-approved 2026-11-05).
Existing offshore_* tables are never touched.
Load goes to doa_icij_<t>_new, then one atomic RENAME swaps it in (old copy kept as _prev
until the next import). CSVs are unzipped to a temp dir and deleted afterwards; the zip stays.
Licence: ODbL 1.0 - attribute "ICIJ Offshore Leaks Database". Presence != wrongdoing.

  venv/bin/python -m journalist_research.jobs.icij_import [--snapshot <id>]
"""
from __future__ import annotations
import argparse, json, os, shutil, tempfile, time, zipfile
from ..sources import icij_offshore as I
from .db import _conn

TABLES = {
 "entities": ("nodes-entities.csv", ["node_id","name","original_name","former_name","jurisdiction","jurisdiction_description",
              "company_type","address","internal_id","incorporation_date","inactivation_date","struck_off_date","dorm_date",
              "status","service_provider","ibcRUC","country_codes","countries","sourceID","valid_until","note"]),
 "officers": ("nodes-officers.csv", ["node_id","name","countries","country_codes","sourceID","valid_until","note"]),
 "addresses": ("nodes-addresses.csv", ["node_id","address","name","countries","country_codes","sourceID","valid_until","note"]),
 "intermediaries": ("nodes-intermediaries.csv", ["node_id","name","status","internal_id","address","countries","country_codes",
                    "sourceID","valid_until","note"]),
 "others": ("nodes-others.csv", ["node_id","name","type","incorporation_date","struck_off_date","closed_date","jurisdiction",
            "jurisdiction_description","countries","country_codes","sourceID","valid_until","note"]),
 "relationships": ("relationships.csv", ["node_id_start","node_id_end","rel_type","link","status","start_date","end_date","sourceID"]),
}
LONG = {"name","original_name","former_name","address","note","jurisdiction_description","countries","service_provider","link"}


def ddl(t, cols):
    defs = []
    for c in cols:
        if c in ("node_id","node_id_start","node_id_end"): defs.append(f"`{c}` BIGINT")
        elif c in LONG: defs.append(f"`{c}` TEXT")
        else: defs.append(f"`{c}` VARCHAR(255)")
    if t == "relationships":
        keys = "KEY k_s (node_id_start), KEY k_e (node_id_end)"
    else:
        keys = "PRIMARY KEY (node_id), KEY k_name (name(100))"
    return f"CREATE TABLE doa_icij_{t}_new ({', '.join(defs)}, {keys}) CHARACTER SET utf8mb4 ENGINE=InnoDB"


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--snapshot")
    a = ap.parse_args(argv)
    st = json.load(open(I.STATE))
    snap = a.snapshot or st["snapshot"]
    zp = os.path.join(I.STORE, "snapshots", snap, "full-oldb.zip")
    tmp = tempfile.mkdtemp(prefix="doa_icij_", dir=os.path.dirname(zp))
    c = _conn(); c.autocommit(True); cur = c.cursor()
    report = {"snapshot": snap, "tables": {}, "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        with zipfile.ZipFile(zp) as z:
            gen = next((n for n in z.namelist() if n.startswith("GENERATED_ON_")), "")
            report["generated_on"] = gen.replace("GENERATED_ON_", "").replace(".txt", "")
            for t, (fn, cols) in TABLES.items():
                path = z.extract(fn, tmp)
                cur.execute(f"DROP TABLE IF EXISTS doa_icij_{t}_new")
                cur.execute(ddl(t, cols))
                t0 = time.time()
                cur.execute(f"""LOAD DATA LOCAL INFILE %s IGNORE INTO TABLE doa_icij_{t}_new
                    CHARACTER SET utf8mb4 FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY ''
                    LINES TERMINATED BY '\\n' IGNORE 1 LINES ({', '.join('@v'+str(i) for i in range(len(cols)))})
                    SET {', '.join(f"`{c}`=NULLIF(@v{i},'')" for i, c in enumerate(cols))}""", (path,))
                cur.execute(f"SELECT COUNT(*) FROM doa_icij_{t}_new"); n = cur.fetchone()[0]
                report["tables"][t] = {"rows": n, "seconds": round(time.time() - t0, 1)}
                os.remove(path)
                print(t, n, flush=True)
        # atomic swap
        renames = []
        for t in TABLES:
            cur.execute("SHOW TABLES LIKE %s", (f"doa_icij_{t}",))
            if cur.fetchone():
                cur.execute(f"DROP TABLE IF EXISTS doa_icij_{t}_prev")
                renames.append(f"doa_icij_{t} TO doa_icij_{t}_prev")
            renames.append(f"doa_icij_{t}_new TO doa_icij_{t}")
        cur.execute("RENAME TABLE " + ", ".join(renames))
        cur.execute("""CREATE TABLE IF NOT EXISTS doa_source_refresh_log (
          id BIGINT AUTO_INCREMENT PRIMARY KEY, source VARCHAR(64), snapshot VARCHAR(32),
          raw_sha256 CHAR(64), summary JSON, created_at DATETIME NOT NULL) CHARACTER SET utf8mb4""")
        meta = json.load(open(os.path.join(I.STORE, "snapshots", snap, "meta.json")))
        cur.execute("INSERT INTO doa_source_refresh_log (source,snapshot,raw_sha256,summary,created_at) VALUES (%s,%s,%s,%s,UTC_TIMESTAMP())",
                    ("icij_offshore", snap, meta.get("raw_sha256", ""), json.dumps(report)))
        report["status"] = "IMPORTED"
        st["db_snapshot"] = snap; json.dump(st, open(I.STATE, "w"), indent=1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True); c.close()
    json.dump(report, open(os.path.join(I.STORE, "snapshots", snap, "import.json"), "w"), indent=1)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
