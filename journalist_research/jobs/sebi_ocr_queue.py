"""
Deferred OCR for SEBI orders stored as NEEDS_OCR by the text-only backfill.
Re-downloads the PDF (verifies raw SHA-256 against the stored one), OCRs scanned pages
(nice 19, 1 thread), writes <id>/text_ocr.txt.gz, appends an updated line to index.jsonl
(latest line wins), never deletes the original text. PDF is not kept.
Runs at night only (cron 0 1 * * *), capped by --max-orders and --max-hours.
"""
from __future__ import annotations
import argparse, fcntl, gzip, json, os, sys, time
from datetime import datetime, timezone

from ..sources import sebi_orders as S
from ..extraction.pdf_text import extract_pdf_bytes

LOCK = "/tmp/doa_sebi_ocr.lock"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-orders", type=int, default=40)
    ap.add_argument("--max-hours", type=float, default=5)
    a = ap.parse_args(argv)
    lf = open(LOCK, "w")
    try:
        fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0
    os.nice(15)
    so = S.SebiOrders(text_only=True, ocr=True)
    if not os.path.exists(so.index_path):
        return 0
    latest = {}
    with open(so.index_path, encoding="utf-8") as fh:
        for l in fh:
            if l.strip():
                m = json.loads(l); latest[m["order_id"]] = m
    todo = [m for m in latest.values() if m.get("status") == "NEEDS_OCR" and m.get("pdf_url")]
    todo.sort(key=lambda m: m.get("order_date", ""), reverse=True)
    t0, done = time.time(), {"ok": 0, "hash_mismatch": 0, "failed": 0, "queued": len(todo)}
    for m in todo[:a.max_orders]:
        if time.time() - t0 > a.max_hours * 3600:
            break
        try:
            pdf = so.f.get(m["pdf_url"])
            ex = extract_pdf_bytes(pdf.content, ocr=True)
        except Exception as e:  # noqa: BLE001
            done["failed"] += 1; continue
        if m.get("raw_sha256") and ex.raw_sha256 != m["raw_sha256"]:
            m["pdf_changed_since_index"] = True; done["hash_mismatch"] += 1
        odir = os.path.join(so.store, m["order_id"])
        with gzip.open(os.path.join(odir, "text_ocr.txt.gz"), "wt", encoding="utf-8", compresslevel=9) as fh:
            fh.write(ex.text)
        m.update(ocr_status=ex.ocr_status, text_sha256_ocr=ex.text_sha256, extractor_version=ex.extractor_version,
                 status="EXTRACTED" if ex.ocr_status == "OCR_DONE" else "NEEDS_OCR",
                 ocr_at_utc=datetime.now(timezone.utc).isoformat())
        with open(os.path.join(so.store, ".write.lock"), "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            with open(so.index_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(m, ensure_ascii=False) + "\n")
        done["ok"] += 1
    print(json.dumps(done))
    return 0


if __name__ == "__main__":
    sys.exit(main())
