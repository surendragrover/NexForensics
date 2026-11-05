"""
Precision-aware date parsing for Indian and international text.

Handles: '5 January 2024', '5th Jan, 2024', 'January 5, 2024',
'05/01/2024' (DD/MM in India; flagged AMBIGUOUS_DAY_MONTH when both
parts <= 12), 'March 2024', '2023', and Hindi month names.
Publication date and event date are separate concepts: this module only
parses expressions; callers decide which role a date plays.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional
import calendar

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS.update({"sept": 9})
HINDI_MONTHS = {"जनवरी": 1, "फ़रवरी": 2, "फरवरी": 2, "मार्च": 3, "अप्रैल": 4, "मई": 5, "जून": 6,
                "जुलाई": 7, "अगस्त": 8, "सितंबर": 9, "सितम्बर": 9, "अक्टूबर": 10, "अक्तूबर": 10,
                "नवंबर": 11, "नवम्बर": 11, "दिसंबर": 12, "दिसम्बर": 12}
ALL_MONTHS = {**MONTHS, **HINDI_MONTHS}
_MON = "|".join(sorted((re.escape(k) for k in ALL_MONTHS), key=len, reverse=True))


@dataclass
class DateValue:
    raw: str
    start: date
    end: date
    precision: str            # DAY | MONTH | YEAR
    flags: List[str] = field(default_factory=list)
    span: tuple = (0, 0)

    def overlaps(self, other: "DateValue") -> bool:
        return not (self.end < other.start or other.end < self.start)

    def before(self, other: "DateValue") -> Optional[bool]:
        """True/False when ordering is certain at both precisions; None when they overlap."""
        if self.end < other.start:
            return True
        if other.end < self.start:
            return False
        return None


def _day(y, m, d, raw, span, flags=None):
    try:
        dt = date(y, m, d)
    except ValueError:
        return None
    return DateValue(raw, dt, dt, "DAY", flags or [], span)


def _month(y, m, raw, span):
    last = calendar.monthrange(y, m)[1]
    return DateValue(raw, date(y, m, 1), date(y, m, last), "MONTH", [], span)


def parse_dates(text: str, *, locale: str = "IN") -> List[DateValue]:
    text = text or ""
    out: List[DateValue] = []
    taken = []

    def free(a, b):
        return all(b <= s or a >= e for s, e in taken)

    pats = [
        (rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MON})\.?,?\s+(\d{{4}})", "DMY"),
        (rf"({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})", "MDY"),
        (r"(?<!\d)(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})(?!\d)", "NUM"),
        (rf"({_MON})\.?,?\s+(\d{{4}})", "MY"),
        (r"(?<![\d,₹.])((?:19|20)\d{2})(?![\d,])", "Y"),
    ]
    for pat, kind in pats:
        for m in re.finditer(pat, text, re.I):
            a, b = m.span()
            if not free(a, b):
                continue
            g = m.groups()
            dv = None
            if kind == "DMY":
                dv = _day(int(g[2]), ALL_MONTHS[g[1].lower()], int(g[0]), m.group(0), (a, b))
            elif kind == "MDY":
                dv = _day(int(g[2]), ALL_MONTHS[g[0].lower()], int(g[1]), m.group(0), (a, b))
            elif kind == "NUM":
                p1, p2, y = int(g[0]), int(g[1]), int(g[2])
                flags = []
                if p1 <= 12 and p2 <= 12 and p1 != p2:
                    flags.append("AMBIGUOUS_DAY_MONTH")
                d, mo = (p1, p2) if locale == "IN" else (p2, p1)
                if mo > 12:
                    d, mo = mo, d
                    flags = []
                dv = _day(y, mo, d, m.group(0), (a, b), flags)
                if dv is not None and flags:
                    # widen to cover both readings
                    alt = _day(y, d, mo, m.group(0), (a, b))
                    if alt:
                        dv.start, dv.end = min(dv.start, alt.start), max(dv.end, alt.end)
            elif kind == "MY":
                dv = _month(int(g[1]), ALL_MONTHS[g[0].lower()], m.group(0), (a, b))
            else:
                y = int(g[0])
                dv = DateValue(m.group(0), date(y, 1, 1), date(y, 12, 31), "YEAR", [], (a, b))
            if dv:
                out.append(dv)
                taken.append((a, b))
    out.sort(key=lambda d: d.span[0])
    return out
