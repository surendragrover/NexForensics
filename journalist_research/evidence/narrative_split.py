"""
Narrative splitter for investigator-written case text (DOA, 2026-11-06).

A single pasted narrative often mixes what the subject says ("she says she took no loan")
with what a record shows ("a bank notice claims an outstanding loan of Rs 48,00,000").
Treating the whole block as one document hides the conflict, because two assertions from
one lineage are never compared. This module splits the text into clauses and labels each:

  RECORD  the clause reports what a record / notice / filing / order says (cue word first)
  SELF    the clause reports what the subject says, states or denies
  REPORT  anything else

Each clause becomes its own (non-independent) source for the contradiction rules. The output
is a lead for human review: no fact, identity or guilt is established, and a RECORD clause is
only the investigator's summary of a record, not the record itself.
"""
import re
from typing import Dict, List

from journalist_research.evidence.fact_contradiction import split_sentences

_REC_CUE = re.compile(
    r"\b(?:record|records|notice|register|registry|filing|filed|order|judg(?:e)?ment|mca|roc|sebi|rbi|court|"
    r"certificate|bank\s+statement|statement\s+of\s+account|master\s+data|gazette|fir|charge\s*sheet|"
    r"agreement|sanction\s+letter|registrar)\b|रिकॉर्ड|नोटिस|आदेश|अदालत", re.I)
_SELF_CUE = re.compile(
    r"\b(?:says|said|states|stated|denies|denied|claims|claimed|told|tells|maintains|maintained|insists|"
    r"insisted|asserts|asserted|admits|admitted|declares|declared)\b|ने\s+कहा|का\s+कहना|बताया|इनकार", re.I)
_CLAUSE_SPLIT = re.compile(
    r"\s*(?:,\s*but\s+|;\s+|\s+but\s+|,?\s+whereas\s+|,\s*however,?\s+|,\s*while\s+|\s+लेकिन\s+|\s+परंतु\s+|\s+जबकि\s+)",
    re.I)


def classify_clause(c: str) -> str:
    r, s = _REC_CUE.search(c), _SELF_CUE.search(c)
    if r and (not s or r.start() < s.start()):
        return "RECORD"
    if s:
        return "SELF"
    return "REPORT"


def split_narrative(text: str) -> List[Dict]:
    out = []
    for si, sent in enumerate(split_sentences(text or "")):
        for ci, cl in enumerate(p.strip(" ,;") for p in _CLAUSE_SPLIT.split(sent)):
            if len(cl) > 3:
                out.append({"sentence": si, "clause": ci, "text": cl, "kind": classify_clause(cl)})
    return out


def mixed(clauses: List[Dict]) -> bool:
    kinds = {c["kind"] for c in clauses}
    return "RECORD" in kinds and "SELF" in kinds


_KIND_TO_SOURCE = {"RECORD": "RECORD", "SELF": "SELF_STATEMENT", "REPORT": "REPORT"}


def narrative_contradictions(text: str, subject_id: str = "subject"):
    """Structured contradictions (loans, roles, addresses) inside one narrative, clause by clause."""
    from journalist_research.evidence.fact_contradiction import extract_assertions, detect_fact_contradictions
    from journalist_research.evidence.role_contradiction import extract_role_assertions, detect_role_contradictions
    assertions = []
    for c in split_narrative(text):
        tag = f"case-narrative#s{c['sentence'] + 1}c{c['clause'] + 1}"
        kw = dict(subject_id=subject_id, source_id=tag, document_id=tag, lineage=tag,
                  source_kind=_KIND_TO_SOURCE[c["kind"]])
        assertions += extract_assertions(c["text"], **kw) + extract_role_assertions(c["text"], **kw)
    return detect_fact_contradictions(assertions) + detect_role_contradictions(assertions), assertions


def narrative_timeline(text: str) -> List[Dict]:
    """Dated clauses of the narrative in date order (DD/MM read as Indian convention; ambiguity flagged)."""
    from journalist_research.common.dates import parse_dates
    rows = []
    for c in split_narrative(text):
        for d in parse_dates(c["text"]):
            rows.append({"date": d.start.isoformat(), "raw": d.raw, "precision": d.precision,
                         "flags": list(d.flags or []), "kind": c["kind"], "text": c["text"]})
    rows.sort(key=lambda r: r["date"])
    return rows
