"""
Continuous dark-web refresh job (cron, every 6 h):

  1. discovery: ransomware.live leak-site addresses (every run) + Ahmia onion list (once a day)
  2. probe:     classify up to --probe-limit new onions by their home page (safety-filtered)
  3. watchlist: rebuild runtime/config/onion_watchlist.json (manual entries kept)
  4. monitor:   re-fetch watchlist pages older than 20 h (cap --monitor-limit)

Guards: single instance (flock), disk guard (skips fetching when / is >= 85% full),
Tor must be reachable, report JSON per run under runtime/artifacts/sources/refresh_reports/.

  venv/bin/python -m journalist_research.jobs.darkweb_refresh [--probe-limit 60] [--monitor-limit 150]
"""
from __future__ import annotations
import argparse, fcntl, json, os, shutil, socket, sys, traceback
from datetime import datetime, timezone

from ..darkweb_research import onion_discovery as D
from ..darkweb_research.onion_monitor import OnionMonitor

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, "..", "runtime")
REPORTS = os.path.join(RUNTIME, "artifacts", "sources", "refresh_reports")
LOCK = "/tmp/doa_darkweb_refresh.lock"
DISK_LIMIT = 0.85


def disk_used(path: str = "/") -> float:
    u = shutil.disk_usage(path)
    return u.used / u.total


def tor_up(host="127.0.0.1", port=9050) -> bool:
    try:
        socket.create_connection((host, port), timeout=5).close(); return True
    except OSError:
        return False


def step(name, fn):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return {"status": "ERROR", "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1200:]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe-limit", type=int, default=60)
    ap.add_argument("--monitor-limit", type=int, default=150)
    ap.add_argument("--force-ahmia", action="store_true")
    a = ap.parse_args(argv)
    lf = open(LOCK, "w")
    try:
        fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another darkweb_refresh is running; exit"); return 0
    rep = {"job": "darkweb_refresh", "started_utc": datetime.now(timezone.utc).isoformat(),
           "disk_used": round(disk_used(), 3), "tor": tor_up()}
    if rep["disk_used"] >= DISK_LIMIT:
        rep["status"] = "SKIPPED_DISK"
    else:
        reg = D.Registry()
        rep["ransomware_live"] = step("rl", lambda: D.discover_ransomware(reg))
        last_ahmia = max([r.get("last_listed", "") for r in reg.d.values() if "ahmia" in r["sources"]] or [""])
        if a.force_ahmia or not last_ahmia or last_ahmia[:10] != datetime.now(timezone.utc).strftime("%Y-%m-%d"):
            rep["ahmia"] = step("ahmia", lambda: D.discover_ahmia(reg))
        reg.save()
        if rep["tor"]:
            mon = OnionMonitor()
            rep["probe"] = step("probe", lambda: D.probe(reg, mon, limit=a.probe_limit))
            reg.save()
            rep["watchlist"] = step("watch", lambda: D.build_watchlist(reg))
            mon = OnionMonitor()   # reload watchlist
            rep["monitor"] = step("monitor", lambda: mon.refresh_watchlist(limit=a.monitor_limit))
        else:
            rep["watchlist"] = step("watch", lambda: D.build_watchlist(reg))
            rep["probe"] = rep["monitor"] = {"status": "NOT_AVAILABLE", "reason": "Tor SOCKS 9050 down"}
        cats = {}
        for r in reg.d.values():
            cats[r["category"]] = cats.get(r["category"], 0) + 1
        rep["registry"] = {"total": len(reg.d), "by_category": cats}
        rep["status"] = "OK"
    rep["finished_utc"] = datetime.now(timezone.utc).isoformat()
    os.makedirs(REPORTS, exist_ok=True)
    p = os.path.join(REPORTS, "darkweb_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    json.dump(rep, open(p, "w"), indent=1, default=str)
    print(json.dumps({k: v for k, v in rep.items() if k != "trace"}, indent=1, default=str)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
