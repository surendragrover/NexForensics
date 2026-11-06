"""
Structured fact-level contradiction detection for DOA.

The legacy contradiction_engine only detects direct negation pairs in
text.  This module extracts structured assertions
(subject, attribute, value, as_of, precision, source) and compares them
per subject + attribute, with:

  * EXISTENCE contradictions  (said "no loan" while a record shows one)
  * TEMPORAL contradictions   (precision-aware: '2023' vs '5 Jan 2024')
  * NUMERIC contradictions    (amount tolerance, default 5%)
  * temporal-change guard     (a state that changed over time is not a contradiction)
  * namesake guard            (only assertions about the same resolved subject are compared)

Rules are pattern-based and deliberately conservative.  Extend RULES for
new attributes.  Nothing here establishes fact or guilt.
"""
from __future__ import annotations
import hashlib
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from journalist_research.common.dates import parse_dates, DateValue

_AMOUNT = re.compile(
    r"(?:rs\.?|inr|₹|रु\.?|रुपये)\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|crore|cr|करोड़|लाख)?", re.I)
_MULT = {"lakh": 1e5, "lac": 1e5, "लाख": 1e5, "crore": 1e7, "cr": 1e7, "करोड़": 1e7}

_NO_LOAN = re.compile(
    r"\b(?:no|not\s+(?:have|had)\s+any|without\s+any|never\s+(?:took|taken|had))\s+(?:outstanding\s+|active\s+|existing\s+)?loans?\b"
    r"|कोई\s+(?:भी\s+)?(?:लोन|ऋण|क़र्ज़|कर्ज)\s+नहीं", re.I)
_LOAN_RECORD = re.compile(
    r"\bloan\s+(?:record|agreement|account|sanction(?:\s+letter)?|statement)\b|\b(?:personal|home|business|car|gold)\s+loan\b"
    r"|\boutstanding\s+loan\b|\bloan\s+of\s+(?:rs\.?|₹|inr)|\bloan\s+(?:notice|default|demand|recovery|outstanding|dues?)\b"
    r"|\b(?:bank|recovery|demand|default)\s+notice\b[^.]{0,80}\bloan\b"
    r"|(?:लोन|ऋण)\s+(?:रिकॉर्ड|खाता)", re.I)
_TOOK_LOAN = re.compile(
    r"\b(?:took|taken|availed|obtained|borrowed)\s+(?:the|a|this|that)?\s*loan\b|(?:लोन|ऋण)\s+लिया", re.I)
_REPAID = re.compile(r"\b(?:repaid|paid\s+(?:it\s+)?(?:off|back)|closed|settled|foreclosed)\b|चुका\s+दिया", re.I)
_STATEMENT = re.compile(r"\b(?:told|said|says|stated|states|declared|claimed|informed|affidavit|denies|denied|maintains|insists)\b|ने\s+कहा|बताया", re.I)


@dataclass
class Assertion:
    assertion_id: str
    subject_id: str
    attribute: str             # loan.exists | loan.start | loan.amount | loan.repaid
    value: Any
    as_of: Optional[Dict[str, Any]]   # date the assertion speaks for
    kind: str                  # SELF_STATEMENT | RECORD | REPORT
    source_id: str
    document_id: str
    lineage: str
    text: str
    precision: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FactContradiction:
    contradiction_id: str
    doa_class: str             # EXISTENCE | TEMPORAL | NUMERIC
    severity: str              # LOW | MODERATE | HIGH | CRITICAL
    subject_id: str
    attribute: str
    assertion_a: str
    assertion_b: str
    explanation: str
    alternative_explanations: List[str] = field(default_factory=list)
    source_ids: List[str] = field(default_factory=list)
    fact_established: bool = False
    guilt_established: bool = False
    human_review_required: bool = True


def _dv(d: Optional[DateValue]):
    return None if d is None else {"raw": d.raw, "start": d.start.isoformat(),
                                   "end": d.end.isoformat(), "precision": d.precision, "flags": d.flags}


def _dv_from(d: Optional[Dict[str, Any]]) -> Optional[DateValue]:
    if not d:
        return None
    from datetime import date
    return DateValue(d["raw"], date.fromisoformat(d["start"]), date.fromisoformat(d["end"]),
                     d["precision"], list(d.get("flags", [])))


def _aid(*parts) -> str:
    return "AS-" + hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12]


def _amount(sentence: str) -> Optional[float]:
    m = _AMOUNT.search(sentence)
    if not m:
        return None
    val = float(m.group(1).replace(",", ""))
    return val * _MULT.get((m.group(2) or "").lower(), 1)


def split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?।])\s+(?=[A-Z0-9\u0900-\u097F\"'])", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def extract_assertions(text: str, *, subject_id: str, source_id: str, document_id: str,
                       lineage: str, source_kind: str = "REPORT") -> List[Assertion]:
    out: List[Assertion] = []
    for idx, s in enumerate(split_sentences(text)):
        dates = parse_dates(s)
        is_statement = bool(_STATEMENT.search(s))
        kind = "RECORD" if source_kind == "RECORD" else (
            "SELF_STATEMENT" if is_statement else ("RECORD" if _LOAN_RECORD.search(s) else source_kind))
        first = dates[0] if dates else None

        if _NO_LOAN.search(s):
            out.append(Assertion(_aid(document_id, idx, "exists", False), subject_id, "loan.exists", False,
                                 _dv(first), "SELF_STATEMENT" if is_statement else kind,
                                 source_id, document_id, lineage, s, first.precision if first else None))
            continue

        took = _TOOK_LOAN.search(s)
        record = _LOAN_RECORD.search(s) and not took
        if record:
            # the date attached to the record is its start date
            out.append(Assertion(_aid(document_id, idx, "exists", True), subject_id, "loan.exists", True,
                                 _dv(first), "RECORD", source_id, document_id, lineage, s,
                                 first.precision if first else None))
            if first:
                out.append(Assertion(_aid(document_id, idx, "start"), subject_id, "loan.start", _dv(first),
                                     _dv(first), "RECORD", source_id, document_id, lineage, s, first.precision))
            amt = _amount(s)
            if amt:
                out.append(Assertion(_aid(document_id, idx, "amount"), subject_id, "loan.amount", amt,
                                     _dv(first), "RECORD", source_id, document_id, lineage, s))
        if took:
            # statement date (e.g. 'on 20 June 2024') vs claimed start ('in 2023')
            claimed = None
            m_in = re.search(r"\bloan\s+in\s+", s, re.I)
            for d in dates:
                if m_in and d.span[0] >= m_in.end() - 1:
                    claimed = d
                    break
            stated_on = next((d for d in dates if d is not claimed), None)
            if claimed is None and len(dates) == 1 and not re.search(r"\bon\s+" + re.escape(dates[0].raw), s):
                claimed, stated_on = dates[0], None
            out.append(Assertion(_aid(document_id, idx, "exists", True, "self"), subject_id, "loan.exists", True,
                                 _dv(stated_on), "SELF_STATEMENT", source_id, document_id, lineage, s))
            if claimed:
                out.append(Assertion(_aid(document_id, idx, "start", "self"), subject_id, "loan.start", _dv(claimed),
                                     _dv(stated_on), "SELF_STATEMENT", source_id, document_id, lineage, s,
                                     claimed.precision))
        if _REPAID.search(s) and (took or "loan" in s.lower() or "लोन" in s):
            out.append(Assertion(_aid(document_id, idx, "repaid"), subject_id, "loan.repaid", True,
                                 None, "SELF_STATEMENT" if is_statement or took else kind,
                                 source_id, document_id, lineage, s,
                                 metadata={"repayment_date_stated": False}))
    return out


def _cid(cls: str, *parts) -> str:
    """Keyed on lineage + values, so wire copies of one origin yield ONE contradiction."""
    return "FC-" + hashlib.sha256("|".join([cls, *map(str, parts)]).encode()).hexdigest()[:12]


def detect_fact_contradictions(assertions: List[Assertion], *, amount_tolerance: float = 0.05
                               ) -> List[FactContradiction]:
    found: Dict[str, FactContradiction] = {}
    by_subject: Dict[str, List[Assertion]] = {}
    for a in assertions:
        by_subject.setdefault(a.subject_id, []).append(a)

    for subject, items in by_subject.items():
        denials = [a for a in items if a.attribute == "loan.exists" and a.value is False]
        exists_records = [a for a in items if a.attribute == "loan.exists" and a.value is True and a.kind == "RECORD"]
        records = [a for a in items if a.attribute == "loan.start" and a.kind == "RECORD"]
        self_starts = [a for a in items if a.attribute == "loan.start" and a.kind == "SELF_STATEMENT"]
        repaid = [a for a in items if a.attribute == "loan.repaid"]
        amounts = [a for a in items if a.attribute == "loan.amount"]

        # EXISTENCE: denial at time T while a record shows a loan starting before T
        for d in denials:
            t = _dv_from(d.as_of)
            # An undated denial (e.g. "she says she took no loan") is read as made now, at the time of the case.
            # Past-tense / never-type denials then conflict with any earlier recorded loan (HIGH); a present-tense
            # "no outstanding loan" may be true if the loan was repaid since (MODERATE).
            past = bool(re.search(r"\b(?:never|took|taken|had|availed|borrowed)\b|लिया", d.text or "", re.I))
            for r in records:
                start = _dv_from(r.value)
                if start is None:
                    continue
                if t is not None:
                    order = start.before(t)
                    if order is not True:
                        continue   # loan started after the denial, or ordering uncertain -> temporal change
                if r.kind != "RECORD":
                    continue
                alts = ["The record and the statement may refer to different loans; obtain the loan account number."]
                severity = "HIGH"
                if t is None:
                    alts.insert(0, "The denial carries no date; it is read as made at the time of the case narrative.")
                    if not past:
                        severity = "MODERATE"
                        alts.insert(1, "A present-tense denial may be accurate if the loan was repaid after the record date.")
                if repaid:
                    alts.insert(0, "A later self-statement claims the loan was repaid; the repayment date is not stated "
                                   "and is unverified. If repaid before the denial date, the denial may be accurate.")
                    severity = "MODERATE" if any(x.metadata.get("repayment_date_stated") for x in repaid) else "HIGH"
                if d.lineage == r.lineage:
                    alts.append("Both assertions come from the same source lineage.")
                cid = _cid("EXISTENCE", d.lineage, r.lineage, t.raw if t else "undated", start.raw)
                if cid in found:
                    continue
                # link to the same document's loan.exists=True assertion (same attribute), not its start date
                side_b = next((x for x in exists_records if x.document_id == r.document_id), r)
                found[cid] = FactContradiction(
                    cid, "EXISTENCE", severity, subject, "loan.exists", d.assertion_id, side_b.assertion_id,
                    (f"Statement dated {t.raw} denies outstanding loans, but a loan record dated {start.raw} "
                     f"shows a loan beginning before that date.") if t else
                    (f"The subject's undated statement denies a loan, but a record dated {start.raw} shows a loan "
                     f"in the subject's name."),
                    alts, sorted({d.source_id, r.source_id}))

        # TEMPORAL: self-stated start vs recorded start, compared at the coarser precision
        for s in self_starts:
            sv = _dv_from(s.value)
            for r in records:
                rv = _dv_from(r.value)
                if sv is None or rv is None or sv.overlaps(rv):
                    continue
                cid = _cid("TEMPORAL", s.lineage, r.lineage, sv.raw, rv.raw)
                if cid in found:
                    continue
                found[cid] = FactContradiction(
                    cid, "TEMPORAL", "MODERATE", subject, "loan.start", s.assertion_id, r.assertion_id,
                    f"Subject says the loan was taken in {sv.raw} ({sv.precision}); the record dates it "
                    f"{rv.raw} ({rv.precision}). The two periods do not overlap.",
                    ["The statement may refer to a different (earlier) loan.",
                     "Sanction date and disbursal date can differ; check which date the record uses."],
                    sorted({s.source_id, r.source_id}))

        # NUMERIC: differing amounts beyond tolerance
        for i, a in enumerate(amounts):
            for b in amounts[i + 1:]:
                hi, lo = max(a.value, b.value), min(a.value, b.value)
                if hi and (hi - lo) / hi > amount_tolerance and a.lineage != b.lineage:
                    cid = _cid("NUMERIC", *sorted([a.lineage, b.lineage]), hi, lo)
                    found[cid] = FactContradiction(
                        cid, "NUMERIC", "MODERATE", subject, "loan.amount", a.assertion_id, b.assertion_id,
                        f"Loan amounts differ: {a.value:,.0f} vs {b.value:,.0f} (tolerance {amount_tolerance:.0%}).",
                        ["Sanctioned vs disbursed amount", "Principal vs outstanding balance"],
                        sorted({a.source_id, b.source_id}))
    return list(found.values())


def serialize(obj) -> Dict[str, Any]:
    return asdict(obj)
