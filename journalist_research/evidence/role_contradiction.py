"""
Structured role / directorship and address contradictions (extends fact_contradiction, loans).

Assertions
  role.held        value "<role> @ <org>"  metadata {role, org, held: True|False, ceased: bool}
  address.city     value "<city key>"       metadata {raw}

Contradictions (all human_review_required, never fact/guilt):
  ROLE_EXISTENCE  "never a director of X" vs a record/report that he was a director of X
                  -> HIGH when the other side is a RECORD (MCA/regulator), else MODERATE
  ROLE_TEMPORAL   "resigned from X in 2018" vs a record showing the role at X later than that
                  -> MODERATE (precision-aware: overlapping periods are not a contradiction)
  ADDRESS         two different cities for the same period from different lineages -> LOW
Guards: same subject only (caller passes resolved docs), wire copies of one lineage are
not compared with each other, uncertain date order is not a contradiction.
"""
from __future__ import annotations
import re
from typing import Dict, List, Optional

from journalist_research.common.dates import parse_dates
from journalist_research.evidence.fact_contradiction import (
    Assertion, FactContradiction, _aid, _cid, _dv, _dv_from, split_sentences, _STATEMENT)

ROLES = {
    "director": r"(?:managing|whole[- ]time|independent|additional|executive|non[- ]executive|nominee)?\s*director|निदेशक|प्रबंध\s+निदेशक",
    "ceo": r"chief\s+executive(?:\s+officer)?|ceo",
    "chairman": r"chair(?:man|person|woman)",
    "partner": r"(?:designated\s+)?partner|साझेदार",
    "promoter": r"promoter|प्रमोटर",
    "founder": r"(?:co-?)?founder|संस्थापक",
    "proprietor": r"proprietor|मालिक",
    "signatory": r"authori[sz]ed\s+signatory",
}
ROLE_ANY = "|".join(f"(?:{v})" for v in ROLES.values())
# organisation names are case-sensitive (capitalised words), even inside re.I patterns
_ORG = (r"((?-i:(?:M/s\.?\s+)?[A-Z][\w&'.\-]*(?:\s+(?:&\s+)?[A-Z][\w&'.\-]*){0,6}))")
_POS = re.compile(rf"\b(?:is|was|has\s+been|had\s+been|served\s+as|serves\s+as|appointed\s+(?:as\s+)?|became|named)\s+"
                  rf"(?:an?\s+|the\s+)?({ROLE_ANY})\s+(?:of|at|in|on\s+the\s+board\s+of)\s+{_ORG}", re.I)
_REC = re.compile(rf"\b({ROLE_ANY})\s+(?:of|in)\s+{_ORG}\s+(?:since|from|w\.e\.f\.?|with\s+effect\s+from)\b", re.I)
_NEG = re.compile(rf"\b(?:never|not|wasn't|isn't|was\s+not|is\s+not|has\s+not\s+been|had\s+never\s+been)\b[^.;]{{0,30}}?"
                  rf"\b({ROLE_ANY})\b[^.;]{{0,15}}?\b(?:of|at|in|with)\s+{_ORG}", re.I)
_NOLINK = re.compile(rf"\bno\s+(?:connection|association|link|relationship|role)\s+(?:whatsoever\s+)?(?:with|in)\s+{_ORG}", re.I)
_CEASE = re.compile(rf"\b(?:resigned|stepped\s+down|ceased|quit|left)\b(?:\s+as\s+(?:an?\s+|the\s+)?({ROLE_ANY}))?"
                    rf"[^.;]{{0,20}}?\b(?:of|from|at)\s+{_ORG}", re.I)
_ADDR = re.compile(r"\b(?:resid(?:es|ing|ent)\s+(?:at|of|in)|r/o|lives?\s+(?:at|in)|living\s+in|"
                   r"(?:residential\s+)?address\s*(?:is|:))\s+([^.;\n]{3,140})", re.I)
_ADDR_HI = re.compile(r"([\u0900-\u097F]+)\s+(?:के\s+)?निवासी")
_ORG_SUFFIX = re.compile(r"\b(?:m/s|pvt|private|ltd|limited|llp|inc|corp|corporation|company|co|the)\b\.?", re.I)
_STOP_CITY = {"india", "the", "and", "near", "opp", "road", "street"}


def role_family(raw: str) -> str:
    for fam, rx in ROLES.items():
        if re.fullmatch(rf"\s*(?:{rx})\s*", raw or "", re.I):
            return fam
    return (raw or "").strip().lower()


def org_key(raw: str) -> str:
    s = _ORG_SUFFIX.sub(" ", (raw or "").lower())
    s = re.sub(r"[^a-z0-9\u0900-\u097F ]", " ", s)
    return " ".join(s.split())


def city_key(raw: str) -> str:
    s = re.sub(r"\b\d{6}\b|\b\d+\b", " ", raw or "")
    parts = [p.strip() for p in re.split(r",|-", s) if p.strip()]
    for p in reversed(parts):
        w = re.sub(r"[^a-z\u0900-\u097F ]", " ", p.lower()).split()
        w = [x for x in w if x not in _STOP_CITY]
        if w:
            return " ".join(w[-2:]) if len(w) > 1 and len(w[-1]) <= 3 else w[-1]
    return ""


def extract_role_assertions(text: str, *, subject_id: str, source_id: str, document_id: str,
                            lineage: str, source_kind: str = "REPORT") -> List[Assertion]:
    out: List[Assertion] = []
    seen = set()
    for idx, s in enumerate(split_sentences(text)):
        dates = parse_dates(s)
        first = dates[0] if dates else None
        stmt = bool(_STATEMENT.search(s))
        kind = "RECORD" if source_kind == "RECORD" else ("SELF_STATEMENT" if stmt else source_kind)
        neg_spans = []
        for m in list(_NEG.finditer(s)) + list(_NOLINK.finditer(s)):
            neg_spans.append(m.span())
            fam = role_family(m.group(1)) if m.re is _NEG else "any"
            org = m.group(2) if m.re is _NEG else m.group(1)
            ok = org_key(org)
            if not ok: continue
            never = bool(re.search(r"\bnever\b|\bno\s+(?:connection|association|link|relationship|role)", m.group(0), re.I))
            out.append(Assertion(_aid(document_id, idx, "role-neg", fam, ok), subject_id, "role.held",
                                 f"NOT {fam} @ {ok}", _dv(first), kind, source_id, document_id, lineage, s,
                                 first.precision if first else None,
                                 {"role": fam, "org": ok, "org_raw": org.strip(), "held": False, "never": never}))
        for rx in (_POS, _REC):
            for m in rx.finditer(s):
                if any(a <= m.start() < b for a, b in neg_spans):
                    continue
                fam, ok = role_family(m.group(1)), org_key(m.group(2))
                if not ok or (idx, fam, ok) in seen: continue
                seen.add((idx, fam, ok))
                out.append(Assertion(_aid(document_id, idx, "role", fam, ok), subject_id, "role.held",
                                     f"{fam} @ {ok}", _dv(first), kind, source_id, document_id, lineage, s,
                                     first.precision if first else None,
                                     {"role": fam, "org": ok, "org_raw": m.group(2).strip(), "held": True}))
        for m in _CEASE.finditer(s):
            fam = role_family(m.group(1)) if m.group(1) else "any"
            ok = org_key(m.group(2))
            if not ok or not first: continue
            out.append(Assertion(_aid(document_id, idx, "role-cease", fam, ok), subject_id, "role.ceased",
                                 f"ceased {fam} @ {ok}", _dv(first), kind, source_id, document_id, lineage, s,
                                 first.precision, {"role": fam, "org": ok, "org_raw": m.group(2).strip()}))
        for rx in (_ADDR, _ADDR_HI):
            for m in rx.finditer(s):
                ck = city_key(m.group(1))
                if not ck: continue
                out.append(Assertion(_aid(document_id, idx, "addr", ck), subject_id, "address.city", ck,
                                     _dv(first), kind, source_id, document_id, lineage, s,
                                     first.precision if first else None, {"raw": m.group(1).strip()[:140]}))
    return out


def _same_role(a: Dict, b: Dict) -> bool:
    return a["org"] == b["org"] and ("any" in (a["role"], b["role"]) or a["role"] == b["role"])


def detect_role_contradictions(assertions: List[Assertion]) -> List[FactContradiction]:
    found: Dict[str, FactContradiction] = {}
    by_subject: Dict[str, List[Assertion]] = {}
    for a in assertions:
        by_subject.setdefault(a.subject_id, []).append(a)
    for subject, items in by_subject.items():
        held = [a for a in items if a.attribute == "role.held" and a.metadata.get("held")]
        denied = [a for a in items if a.attribute == "role.held" and a.metadata.get("held") is False]
        ceased = [a for a in items if a.attribute == "role.ceased"]
        addrs = [a for a in items if a.attribute == "address.city"]

        for d in denied:
            for h in held:
                if d.lineage == h.lineage or not _same_role(d.metadata, h.metadata):
                    continue
                if not d.metadata.get("never"):
                    td, th = _dv_from(d.as_of), _dv_from(h.as_of)
                    # "is not a director" today vs "was a director" earlier is a change, not a contradiction
                    if td is None or th is None or not td.overlaps(th):
                        continue
                sev = "HIGH" if h.kind == "RECORD" else "MODERATE"
                cid = _cid("ROLE_EXISTENCE", d.lineage, h.lineage, d.value, h.value)
                if cid in found: continue
                found[cid] = FactContradiction(
                    cid, "ROLE_EXISTENCE", sev, subject, "role.held", d.assertion_id, h.assertion_id,
                    f"One source says the subject was {'never ' if d.metadata.get('never') else 'not '}"
                    f"{d.metadata['role'] if d.metadata['role'] != 'any' else 'connected'} at "
                    f"{d.metadata['org_raw']}; another ({h.kind.lower()}) says the subject was {h.metadata['role']} "
                    f"of {h.metadata['org_raw']}.",
                    ["Different companies with similar names; compare CIN / registration numbers.",
                     "Namesake: confirm DIN or another identifier for the person.",
                     "Nominal or past role the statement did not count; check appointment and cessation dates."],
                    sorted({d.source_id, h.source_id}))
        for c in ceased:
            tc = _dv_from(c.as_of)
            for h in held:
                if c.lineage == h.lineage or not _same_role(c.metadata, h.metadata) or h.kind != "RECORD":
                    continue
                th = _dv_from(h.as_of)
                if tc is None or th is None or tc.before(th) is not True:
                    continue
                cid = _cid("ROLE_TEMPORAL", c.lineage, h.lineage, c.value, th.raw)
                if cid in found: continue
                found[cid] = FactContradiction(
                    cid, "ROLE_TEMPORAL", "MODERATE", subject, "role.held", c.assertion_id, h.assertion_id,
                    f"Said to have left {c.metadata['org_raw']} in {tc.raw}, but a record shows the role "
                    f"({h.metadata['role']}) there as of {th.raw}.",
                    ["Resignation filed late with the registry (e.g. DIR-12 / Form 32 delay).",
                     "Re-appointment after the stated exit.", "The record date may be a filing date, not the tenure date."],
                    sorted({c.source_id, h.source_id}))
        for i, a in enumerate(addrs):
            for b in addrs[i + 1:]:
                if a.lineage == b.lineage or a.value == b.value:
                    continue
                ta, tb = _dv_from(a.as_of), _dv_from(b.as_of)
                if ta is None or tb is None or not ta.overlaps(tb):
                    continue
                cid = _cid("ADDRESS", *sorted([a.lineage, b.lineage]), *sorted([a.value, b.value]))
                if cid in found: continue
                found[cid] = FactContradiction(
                    cid, "ADDRESS", "LOW", subject, "address.city", a.assertion_id, b.assertion_id,
                    f"Two sources place the subject in different cities for the same period: "
                    f"{a.metadata.get('raw')} ({ta.raw}) vs {b.metadata.get('raw')} ({tb.raw}).",
                    ["More than one residence, or a registered vs residential address.",
                     "Move within the period at the dates' precision.", "Namesake."],
                    sorted({a.source_id, b.source_id}))
    return list(found.values())
