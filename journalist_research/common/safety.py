"""
DOA safety layer: banned conclusions, neutral negative phrasing,
third-party privacy redaction, and the no-automatic-conclusion guard.
"""
from __future__ import annotations
import re
from typing import Any, Iterable, List

BANNED_PHRASES = [
    "clean record", "clean chit", "no criminal record", "verified clear",
    "is guilty", "proven fraud", "confirmed fraudster", "confirmed criminal",
    "definitely", "beyond doubt", "does not exist", "never existed",
    "साफ़ रिकॉर्ड", "साफ रिकॉर्ड", "कोई आपराधिक रिकॉर्ड नहीं", "दोषी है", "पक्का धोखेबाज़",
]

_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")
_AADHAAR = re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")

FLAGS = ("fact_established", "identity_established", "guilt_established",
         "non_existence_established", "truth_established", "automatic_conclusion")


def find_banned(text: str) -> List[str]:
    low = (text or "").lower()
    return [p for p in BANNED_PHRASES if p.lower() in low]


def redact(text: str, *, keep_emails: bool = False) -> str:
    """Redact personal identifiers of third parties by default."""
    t = _AADHAAR.sub("[AADHAAR-REDACTED]", text or "")
    t = _PHONE.sub("[PHONE-REDACTED]", t)
    t = _PAN.sub("[PAN-REDACTED]", t)
    if not keep_emails:
        t = _EMAIL.sub("[EMAIL-REDACTED]", t)
    return t


def negative_statement(target: str, sources_searched: Iterable[str]) -> str:
    srcs = ", ".join(sources_searched) or "no sources"
    return (f"Not found in the sources searched ({srcs}): {target}. "
            f"Absence from these sources is not proof of absence.")


def _get(obj: Any, key: str):
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def assert_no_automatic_conclusion(*objs: Any) -> bool:
    for o in objs:
        if o is None:
            continue
        for f in FLAGS:
            if _get(o, f):
                raise RuntimeError(f"Safety violation: {type(o).__name__}.{f} is True")
    return True


def validate_render(texts: Iterable[str]) -> List[str]:
    issues = []
    for t in texts:
        for p in find_banned(t):
            issues.append(f"banned phrase '{p}' in: {t[:80]}")
    return issues
