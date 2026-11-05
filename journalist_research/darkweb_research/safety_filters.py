"""
Dark-web content safety for DOA.

Rules (non-negotiable, see project principles):
  * Abuse tripwire: a page that carries child-abuse indicators is DISCARDED — nothing
    from it is stored, only the SHA-256 of its URL and the reason.
  * Credentials are never stored: email:password pairs, password fields, password
    hashes next to an identifier, API tokens and card numbers are redacted before
    any text touches disk.
  * Only text. Media, archives and executables are refused by content-type and URL
    extension before download.
"""
from __future__ import annotations
import re
from typing import Tuple

ABUSE_TRIPWIRE = [
    r"\bpthc\b", r"\bhussyfan\b", r"\bpreteen\b", r"\bjail ?bait\b", r"\blolita\b",
    r"\bchild ?porn", r"\bcsam\b", r"\bpedo(phile)?s?\b", r"\bunderage\b.{0,30}\b(sex|nude|porn)",
]
_TRIP = re.compile("|".join(ABUSE_TRIPWIRE), re.I)

ALLOWED_CONTENT_TYPES = ("text/html", "text/plain", "application/xhtml+xml")
BLOCKED_EXT = re.compile(
    r"\.(jpe?g|png|gif|webp|bmp|svg|mp4|mkv|avi|mov|webm|mp3|wav|zip|rar|7z|tar|gz|bz2|xz|"
    r"exe|dll|apk|msi|iso|bin|sql|csv|xlsx?|db|sqlite|txt\.gz|torrent)(\?|$)", re.I)

_EMAIL = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
REDACTIONS = [
    # email:password / email;password / email|password combo-list lines
    (re.compile(rf"({_EMAIL})\s*[:;|,]\s*\S+"), r"\1:[REDACTED-CREDENTIAL]"),
    # user:hash (md5/sha1/sha256/bcrypt)
    (re.compile(r"(\b[\w.@-]{3,}\b)\s*[:;|]\s*(\$2[aby]\$\d\d\$[./A-Za-z0-9]{53}|[a-fA-F0-9]{32,64})\b"),
     r"\1:[REDACTED-HASH]"),
    # password=..., pass: ..., pwd ...
    (re.compile(r"(?i)\b(pass(word)?|passwd|pwd|pin|otp)\b\s*[:=]\s*\S+"), r"\1: [REDACTED-CREDENTIAL]"),
    # API keys / bearer tokens / private keys
    (re.compile(r"(?i)\b(api[_-]?key|token|secret|bearer)\b\s*[:=]?\s*[A-Za-z0-9_\-\.=]{16,}"),
     r"\1 [REDACTED-TOKEN]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
     "[REDACTED-PRIVATE-KEY]"),
    # payment card numbers (13-19 digits, optional separators)
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[REDACTED-NUMBER]"),
]


def abuse_tripwire(text: str) -> bool:
    return bool(_TRIP.search(text or ""))


def redact_credentials(text: str) -> Tuple[str, int]:
    n = 0
    for rx, rep in REDACTIONS:
        text, k = rx.subn(rep, text)
        n += k
    return text, n


def content_type_ok(ct: str) -> bool:
    ct = (ct or "").split(";")[0].strip().lower()
    return ct in ALLOWED_CONTENT_TYPES


def url_ext_blocked(url: str) -> bool:
    return bool(BLOCKED_EXT.search(url or ""))
