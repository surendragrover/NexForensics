"""Per-user file storage on the owner's Google Drive (approved 2026-11-06).

Rule: every uploaded file (documents, subject photo) and every DOA dossier is kept on
Google Drive, encrypted (rclone crypt remote ``doa_crypt:``), under users/<user_id>/<run>/.
Nothing stays on the server: files are staged in an outbox and *moved* to Drive
(rclone move deletes the local copy only after a successful upload). Files are kept
while the user's account exists; ``delete_user`` removes the user's whole folder.

CLI:
  python -m journalist_research.storage.drive_store flush            # retry the outbox
  python -m journalist_research.storage.drive_store delete-user <id> # account deleted
  python -m journalist_research.storage.drive_store ls <id>
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone

REMOTE = os.environ.get("DOA_DRIVE_REMOTE", "doa_crypt:")
APP = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTBOX = os.path.join(APP, "runtime", "drive_outbox")
LOG = os.path.join(APP, "logs", "doa_drive_store.log")
_LOCK = threading.Lock()


def _log(msg: str) -> None:
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")


def safe_id(x) -> str:
    s = re.sub(r"[^A-Za-z0-9_.@-]", "_", str(x or "unknown"))[:80]
    return s or "unknown"


def user_from_request(request) -> str:
    """user_id from the signed Gradio auth cookie (same secret as gradio_app)."""
    try:
        import jwt as _pyjwt
        tok = request.cookies.get("nxf_gradio_auth") if request is not None else None
        if not tok:
            return "unknown"
        p = _pyjwt.decode(tok, os.environ.get("JWT_SECRET_KEY", "jwt-secret-key-change-in-production"),
                          algorithms=["HS256"])
        return safe_id(p.get("user_id") or p.get("email"))
    except Exception:  # noqa: BLE001
        return "unknown"


def stage(paths, user_id: str, run_id: str, kind: str) -> list[str]:
    """Copy files into the outbox (users/<uid>/<run>/<kind>/). Returns staged names."""
    out = []
    if os.environ.get("DOA_DRIVE") == "off" or os.environ.get("DOA_AUDIT") == "off":  # offline tests
        return out
    dest = os.path.join(OUTBOX, "users", safe_id(user_id), safe_id(run_id), kind)
    for p in paths or []:
        p = getattr(p, "name", p)
        if not p or not os.path.isfile(p):
            continue
        os.makedirs(dest, exist_ok=True)
        tgt = os.path.join(dest, safe_id(os.path.basename(p)))
        shutil.copy2(p, tgt)
        out.append(os.path.relpath(tgt, OUTBOX))
    return out


def flush(timeout: int = 900) -> bool:
    """Move everything in the outbox to Drive. Local copies go only after upload succeeds."""
    if not os.path.isdir(os.path.join(OUTBOX, "users")):
        return True
    with _LOCK:
        r = subprocess.run(["rclone", "move", OUTBOX, REMOTE, "--delete-empty-src-dirs",
                            "--transfers", "2", "--retries", "3"],
                           capture_output=True, text=True, timeout=timeout)
    _log(f"flush rc={r.returncode} {r.stderr.strip()[-400:]}")
    return r.returncode == 0


def flush_async() -> None:
    threading.Thread(target=lambda: _safe(flush), daemon=True).start()


def _safe(fn):
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        _log(f"flush error {type(e).__name__}: {e}")


def delete_user(user_id: str) -> bool:
    uid = safe_id(user_id)
    if uid in ("", "unknown", ".", ".."):
        raise ValueError("refusing to delete without a real user id")
    shutil.rmtree(os.path.join(OUTBOX, "users", uid), ignore_errors=True)
    r = subprocess.run(["rclone", "purge", f"{REMOTE}users/{uid}"], capture_output=True, text=True, timeout=900)
    ok = r.returncode == 0 or "directory not found" in r.stderr.lower()
    _log(f"delete_user {uid} rc={r.returncode} ok={ok}")
    return ok


def ls(user_id: str) -> str:
    r = subprocess.run(["rclone", "lsl", f"{REMOTE}users/{safe_id(user_id)}"], capture_output=True, text=True, timeout=300)
    return r.stdout or r.stderr


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["flush"]:
        sys.exit(0 if flush() else 1)
    if a[:1] == ["delete-user"] and len(a) == 2:
        sys.exit(0 if delete_user(a[1]) else 1)
    if a[:1] == ["ls"] and len(a) == 2:
        print(ls(a[1])); sys.exit(0)
    print(__doc__); sys.exit(2)
