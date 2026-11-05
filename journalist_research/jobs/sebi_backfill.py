"""
SEBI enforcement-orders backfill, TEXT-ONLY (Surendra 2026-11-05: "text hi rakho").

Walks every listing page of each category (AO first), ingests orders not yet in the store:
gzip text + PDF SHA-256 + URL + metadata; the PDF itself is never kept.
Resumable: checkpoint per category in runtime/artifacts/sources/sebi/backfill_state.json.
Guards: single instance (flock), stops when / reaches 80% used, stops a category after
3 consecutive failed pages, polite 3 s/host from PoliteFetcher.

Cron (hourly, resumes if killed; exits at once if already running or finished):
  15 * * * * cd /home/nexforensics/app && venv/bin/python -m journalist_research.jobs.sebi_backfill
"""
from __future__ import annotations
import argparse, fcntl, json, os, shutil, signal, socket, sys, time
from datetime import datetime, timezone

from ..sources import sebi_orders as S
from ..sources.http_polite import SourceBlocked

STATE = os.path.join(S.STORE, "backfill_state.json")
LOCK = "/tmp/doa_sebi_backfill.lock"
ORDER = (6, 1, 2, 3, 4, 7, 5)      # 6 = Adjudication Orders first
DISK_STOP = 0.80
STEP_TIMEOUT = 300          # hard cap per listing page / per order (stuck TLS reads seen 2026-11-05)


class StepTimeout(Exception):
    pass


def _alarm(signum, frame):
    raise StepTimeout("step exceeded %ss" % STEP_TIMEOUT)


def guarded(fn, *a):
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(STEP_TIMEOUT)
    try:
        return fn(*a)
    finally:
        signal.alarm(0)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def disk_used(path="/"):
    u = shutil.disk_usage(path); return u.used / u.total


def load_state():
    return json.load(open(STATE)) if os.path.exists(STATE) else {"categories": {}}


def save_state(st):
    st["updated_utc"] = now()
    tmp = STATE + ".tmp"; json.dump(st, open(tmp, "w"), indent=1); os.replace(tmp, STATE)


def log(msg):
    print(f"{now()} {msg}", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--smids", default=",".join(map(str, ORDER)))
    ap.add_argument("--max-hours", type=float, default=0, help="0 = run until done")
    a = ap.parse_args(argv)
    lf = open(LOCK, "w")
    try:
        fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0
    socket.setdefaulttimeout(90)
    os.makedirs(S.STORE, exist_ok=True)
    so = S.SebiOrders(text_only=True, ocr=False)   # OCR deferred: 2 CPUs shared with live app
    os.nice(10)
    st = load_state()
    if st.get("finished_utc"):
        return 0
    t0 = time.time()
    known = so.known_ids()
    for smid in [int(x) for x in a.smids.split(",")]:
        c = st["categories"].setdefault(str(smid), {"next_page": 0, "done": False, "ingested": 0,
                                                     "failed": 0, "skipped_known": 0, "total": None})
        if c["done"]:
            continue
        fails = 0
        while True:
            if disk_used() >= DISK_STOP:
                log(f"STOP disk {disk_used():.0%} >= {DISK_STOP:.0%}"); st["stopped"] = "DISK"; save_state(st); return 0
            if a.max_hours and time.time() - t0 > a.max_hours * 3600:
                log("STOP max-hours"); save_state(st); return 0
            pg = c["next_page"]
            try:
                res = guarded(so.list_page, smid, pg)
            except (SourceBlocked, Exception) as e:  # noqa: BLE001
                fails += 1
                log(f"smid={smid} page={pg} listing error {type(e).__name__}: {e}")
                if fails >= 3:
                    c["last_error"] = f"{type(e).__name__}: {e}"; save_state(st)
                    log(f"smid={smid} 3 failed pages in a row; leaving category for the next run"); break
                time.sleep(60); continue
            fails = 0
            if res.get("total"):
                c["total"] = res["total"]
            orders = res["orders"]
            if not orders:
                c["done"] = True; c["finished_utc"] = now(); save_state(st)
                log(f"smid={smid} DONE ingested={c['ingested']} failed={c['failed']}"); break
            log(f"smid={smid} page={pg} listed {len(orders)}")
            for o in orders:
                if o.order_id in known:
                    c["skipped_known"] += 1; continue
                o.category = o.category or f"smid={smid}"
                try:
                    r = guarded(so.ingest, o)
                except Exception as e:  # noqa: BLE001  (timeouts, broken chunked reads, ...)
                    o.status, o.error = "NOT_AVAILABLE", f"{type(e).__name__}: {e}"[:300]; r = o
                    with open(os.path.join(S.STORE, "failures.jsonl"), "a") as fh:
                        fh.write(json.dumps({"order_id": o.order_id, "page_url": o.page_url, "error": o.error}) + "\n")
                known.add(o.order_id)
                if r.status == "NOT_AVAILABLE":
                    c["failed"] += 1
                else:
                    c["ingested"] += 1
            c["next_page"] = pg + 1
            save_state(st)
            log(f"smid={smid} page={pg} done; ingested={c['ingested']} failed={c['failed']} "
                f"of total={c['total']} disk={disk_used():.0%}")
    if all(st["categories"].get(str(s), {}).get("done") for s in ORDER):
        st["finished_utc"] = now()
    save_state(st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
