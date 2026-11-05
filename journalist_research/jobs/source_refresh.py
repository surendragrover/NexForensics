"""
DOA source refresh job.
  venv/bin/python -m journalist_research.jobs.source_refresh            # dry run: SEBI sync + UK diff + ICIJ check
  venv/bin/python -m journalist_research.jobs.source_refresh --write-db # also upsert UK list (approved only)
  ... --sebi-limit 25  --icij-download
Exit code 0 even when a source is NOT_AVAILABLE; status is in the JSON report.
"""
from __future__ import annotations
import argparse, json, os, sys, traceback
from datetime import datetime, timezone

from ..sources.http_polite import PoliteFetcher, SourceBlocked
from ..sources import sebi_orders, uk_sanctions, icij_offshore, global_sanctions
import shutil

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(HERE, "runtime", "artifacts", "sources", "refresh_reports")


def _safe(name, fn):
    try:
        return fn()
    except SourceBlocked as e:
        return {"status": "NOT_AVAILABLE", "error": str(e)}
    except Exception as e:
        return {"status": "ERROR", "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-db", action="store_true")
    ap.add_argument("--sebi-limit", type=int, default=25)
    ap.add_argument("--icij-download", action="store_true")
    ap.add_argument("--only", choices=["sebi", "uk", "icij", "global"])
    a = ap.parse_args(argv)
    f = PoliteFetcher()
    rep = {"started_utc": datetime.now(timezone.utc).isoformat()}
    du = shutil.disk_usage("/"); rep["disk_used"] = round(du.used / du.total, 3)
    if rep["disk_used"] >= 0.80:
        rep["sebi"] = {"status": "SKIPPED_DISK", "warning": f"/ is {rep['disk_used']:.0%} full"}
    elif a.only in (None, "sebi"):
        rep["sebi"] = _safe("sebi", lambda: sebi_orders.SebiOrders(f).sync(limit=a.sebi_limit))
    if a.only in (None, "uk"):
        rep["uk_sanctions"] = _safe("uk", lambda: uk_sanctions.sync(f, write_db=a.write_db))
    if a.only in (None, "global"):
        rep["global_sanctions"] = _safe("global", lambda: global_sanctions.sync_all(f, write_db=a.write_db))
    if a.only in (None, "icij"):
        rep["icij"] = _safe("icij", lambda: icij_offshore.sync(f, download=a.icij_download))
    rep["finished_utc"] = datetime.now(timezone.utc).isoformat()
    os.makedirs(REPORTS, exist_ok=True)
    p = os.path.join(REPORTS, datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    json.dump(rep, open(p, "w"), indent=1, ensure_ascii=False)
    print(json.dumps(rep, indent=1, ensure_ascii=False)); print("REPORT", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
