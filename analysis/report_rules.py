"""
analysis/report_rules.py — p23 (2026-11-07) rule helpers for the main
investigation report. Values live in analysis/report_rules.json.

Pure functions: no DB, no network, no model. Used by gradio_app.run_analysis,
analysis/evidence_analysis.py, analysis/reasoning.py, engines/matching_engines.py
and reports/pdf_export.py.

Covers:
  - MO link threshold / category filter and score-derived confidence
  - Indian-name transliteration keys -> POSSIBLE (spelling-variant) tier
  - country detection (India) from location + narrative + entities
  - crime taxonomy (crime TYPES only; names are never crimes)
  - country-aware law suggestion (IPC before 2024-07-01, BNS on/after; PMLA)
  - crime-type aware next-evidence list
  - risk band for heuristic fallback
  - intake-date timeline event + dated statements
  - Case ID validation / NXF id generation
  - IST timestamps
"""
from __future__ import annotations

import json
import random
import re
from datetime import datetime, timedelta, timezone, date
from difflib import SequenceMatcher
from pathlib import Path

_RULES_PATH = Path(__file__).resolve().with_name("report_rules.json")


def load_rules(path: Path | None = None) -> dict:
    try:
        return json.loads(Path(path or _RULES_PATH).read_text(encoding="utf-8"))
    except Exception:
        return {}


RULES = load_rules()


# ── time ─────────────────────────────────────────────────────────────────────
def _tz():
    t = RULES.get("timezone", {}) or {}
    return timezone(timedelta(minutes=int(t.get("offset_minutes", 330))), t.get("name", "IST"))


def now_ist() -> datetime:
    return datetime.now(_tz())


def fmt_ist(dt: datetime | None = None) -> str:
    dt = dt or now_ist()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz())
    dt = dt.astimezone(_tz())
    return dt.strftime("%Y-%m-%d %H:%M:%S") + " " + (RULES.get("timezone", {}) or {}).get("label", "IST (+05:30)")


# ── Case ID ──────────────────────────────────────────────────────────────────
def resolve_case_id(user_value: str | None, suspect_name: str | None = None, now: datetime | None = None):
    """Returns (case_id, user_reference_or_None, note).
    Keeps a typed value only when it looks like a case/FIR reference (has a digit,
    no spaces) and is not the suspect's name."""
    cfg = RULES.get("case_id", {}) or {}
    v = (user_value or "").strip()
    rx = re.compile(cfg.get("valid_regex", r"^(?=.*\d)[A-Za-z0-9][A-Za-z0-9/_.:#-]{2,59}$"))
    same_as_suspect = bool(v and suspect_name and _squash(v) == _squash(suspect_name))
    if v and rx.match(v) and not same_as_suspect:
        return v, None, ""
    now = now or now_ist()
    cid = cfg.get("format", "NXF-{year}-{num:04d}").format(year=now.year, num=random.randint(1, 9999))
    if not v:
        return cid, None, "Case ID was empty: auto-generated."
    why = "matches the suspect name" if same_as_suspect else "does not look like a case reference (needs a digit, no spaces)"
    return cid, v, f"Typed Case ID '{v}' {why}: kept as user reference; auto-generated {cid}."


def _squash(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# ── MO links ─────────────────────────────────────────────────────────────────
def mo_confidence_from_score(score) -> str:
    try:
        s = float(score or 0)
    except (TypeError, ValueError):
        s = 0.0
    for thr, label in (RULES.get("mo_links", {}) or {}).get("confidence_bands", [[75, "high"], [55, "medium"], [40, "low-medium"]]):
        if s >= thr:
            return label
    return "below threshold"


def filter_mo_links(rows: list) -> tuple[list, list]:
    """Split MO candidate rows into (qualifying, suppressed).
    Qualifying = fingerprint score >= threshold AND same crime category."""
    cfg = RULES.get("mo_links", {}) or {}
    thr = float(cfg.get("min_fingerprint_score", 40))
    need_cat = bool(cfg.get("require_same_category", True))
    keep, drop = [], []
    for r in rows or []:
        try:
            sc = float(r.get("fingerprint_score", 0) or 0)
        except (TypeError, ValueError):
            sc = 0.0
        reasons = []
        if sc < thr:
            reasons.append(f"MO score {sc:g}% < {thr:g}% threshold")
        if need_cat and not r.get("category_match", True):
            reasons.append("different crime category")
        if reasons:
            drop.append({**r, "suppressed_reason": "; ".join(reasons)})
        else:
            keep.append({**r, "link_confidence": mo_confidence_from_score(sc)})
    return keep, drop


def mo_none_text() -> str:
    cfg = RULES.get("mo_links", {}) or {}
    return cfg.get("none_text", "No MO link found.").format(min=cfg.get("min_fingerprint_score", 40))


# ── Indian name transliteration ──────────────────────────────────────────────
_HONORIFICS = {"mr", "mrs", "ms", "dr", "shri", "sri", "smt", "kumari", "late", "adv", "sh", "prof", "capt", "col"}


def name_tokens(name: str) -> list[str]:
    toks = [t for t in re.findall(r"[a-z]+", (name or "").lower()) if t not in _HONORIFICS]
    return [t for t in toks if len(t) > 1]


def phonetic_key(token: str) -> str:
    cfg = RULES.get("name_matching", {}) or {}
    t = (token or "").lower()
    for a, b in cfg.get("digraph_map", []):
        t = t.replace(a, b)
    for _ in range(2):                       # long vowels first (ee->i), then doubles, then again
        for a, b in cfg.get("vowel_map", []):
            t = t.replace(a, b)
        t = re.sub(r"(.)\1+", r"\1", t)      # double consonants / vowels -> single
    t = re.sub(r"h$", "", t) if len(t) > 3 else t   # trailing aspirate: Krishnah
    return t


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def spelling_variant_match(query: str, candidate: str) -> dict | None:
    """POSSIBLE tier: every query token matches a candidate token by transliteration
    key (or key similarity >= threshold, same first letter); at most N extra
    candidate tokens (middle name). Returns None for exact (case-insensitive)
    equality — that is handled by the normal strong-match logic."""
    cfg = RULES.get("name_matching", {}) or {}
    q, c = name_tokens(query), name_tokens(candidate)
    if not q or not c or len(q) < 2:
        return None              # one-word queries are too ambiguous for a variant tier
    if " ".join(q) == " ".join(c):
        return None
    thr = float(cfg.get("min_token_similarity", 0.84))
    used, pairs, changed = set(), [], False
    for qt in q:
        qk = phonetic_key(qt)
        best, best_s = None, 0.0
        for i, ct in enumerate(c):
            if i in used:
                continue
            ck = phonetic_key(ct)
            s = 1.0 if qk == ck else (_sim(qk, ck) if qk[:1] == ck[:1] else 0.0)
            if s > best_s:
                best, best_s = i, s
        if best is None or best_s < thr:
            return None
        used.add(best)
        if qt != c[best]:
            changed = True
        pairs.append((qt, c[best], round(best_s, 2)))
    extra = len(c) - len(used)
    if extra > int(cfg.get("max_extra_candidate_tokens", 1)):
        return None
    if not changed and extra == 0:
        return None
    return {"tier": "POSSIBLE", "label": cfg.get("tier_label", "POSSIBLE (spelling variant, verify identity)"),
            "pairs": pairs, "extra_tokens": extra,
            "score": round(sum(p[2] for p in pairs) / len(pairs), 2)}


def spelling_variants(token: str, limit: int = 12) -> list[str]:
    """Generate search spellings for one token (for a supplementary DB search)."""
    t = (token or "").lower()
    out = {t}
    swaps = [("iya", "ya"), ("ya", "iya"), ("ia", "ya"), ("ya", "ia"), ("aa", "a"), ("ee", "i"), ("i", "ee"),
             ("oo", "u"), ("u", "oo"), ("v", "w"), ("w", "v"), ("sh", "s"), ("ph", "f"), ("th", "t"), ("ai", "ay"), ("ay", "ai")]
    for a, b in swaps:
        if a in t:
            out.add(t.replace(a, b, 1))
    for v in list(out):
        out.add(re.sub(r"([bcdfgjklmnprstvz])\1", r"\1", v))                  # ll -> l
        for m in re.finditer(r"(?<=[aeiou])([bcdfgjklmnprstvz])(?=[aeiouy])", v):
            out.add(v[:m.start()] + m.group(1) * 2 + v[m.end():])              # l -> ll
    for v in list(out):
        for a, b in swaps[:4]:
            if a in v:
                out.add(v.replace(a, b, 1))
    out = sorted(out, key=lambda x: (x != t, len(x)))
    return out[:limit]


# ── country / jurisdiction ───────────────────────────────────────────────────
def detect_country(location: str = "", narrative: str = "", entities: dict | None = None) -> dict:
    """Returns {'code': 'IN'|None, 'label': ..., 'basis': [...]}."""
    ent_text = " ".join(" ".join(map(str, v)) for k, v in (entities or {}).items()
                        if k in ("ORG", "BANK", "AGENCY", "LAW", "LOC", "MONEY"))
    for code, cfg in (RULES.get("country_detection", {}) or {}).items():
        basis = []
        loc = f" {(location or '').lower()} "
        for m in cfg.get("markers", []):
            if re.search(r"(?<![a-z])" + re.escape(m) + r"(?![a-z])", loc):
                basis.append(f"location '{m}'")
                break
        text = f"{narrative or ''} {ent_text}"
        low = text.lower()
        for m in cfg.get("strong_markers", []):
            if re.search(r"(?<![a-z0-9])" + re.escape(m) + r"(?![a-z0-9])", low):
                basis.append(m)
        for m in cfg.get("case_sensitive_markers", []):
            if re.search(r"(?<![A-Za-z])" + re.escape(m) + r"(?![A-Za-z])", text):
                if m.lower() not in [b.lower() for b in basis]:
                    basis.append(m)
        loc_hit = any(b.startswith("location") for b in basis)
        if loc_hit or len(basis) >= int(cfg.get("min_hits", 2)):
            return {"code": code, "label": cfg.get("label", code), "basis": basis[:8]}
    return {"code": None, "label": None, "basis": []}


# ── crime taxonomy ───────────────────────────────────────────────────────────
_SEV = ["Low", "Medium", "High", "Critical"]


def classify_crimes(text: str, exclude_terms: list[str] | None = None) -> list[dict]:
    """Crime types from the taxonomy, in narrative order of first hit.
    exclude_terms: entity names (ORG/BANK/PERSON) that must never act as crime keywords."""
    low = (text or "").lower()
    excl = {e.lower() for e in (exclude_terms or []) if e}
    hits = []
    for e in (RULES.get("crime_taxonomy", {}) or {}).get("entries", []):
        best = None
        for kw in e.get("keywords", []):
            if kw.lower() in excl:
                continue
            m = re.search(r"(?<![a-z])" + re.escape(kw.lower()) + r"(?![a-z])", low)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), kw)
        if best:
            hits.append({"crime": e["crime"], "severity": e.get("severity", "Medium"), "keyword": best[1],
                         "pos": best[0], "ipc": e.get("ipc", []), "special": e.get("special", [])})
    hits.sort(key=lambda h: h["pos"])
    return hits


def max_severity(*sevs) -> str:
    sevs = [s for s in sevs if s in _SEV]
    return max(sevs, key=_SEV.index) if sevs else "Low"


def _parse_date(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def suggest_laws(country: dict, crimes: list[dict], incident_date: str = "") -> dict:
    """Country-aware statute suggestion. Returns {'statutes': str, 'items': [...], 'code_used': 'IPC'|'BNS'|None,
    'label': str, 'jurisdiction': str, 'action': str}."""
    lm = RULES.get("law_mapping", {}) or {}
    code = (country or {}).get("code")
    cfg = lm.get(code) if code in lm else lm.get("default", {})
    financial = any(c["crime"] in (RULES.get("threat", {}) or {}).get("financial_basis_crimes", []) for c in crimes)
    _acts = cfg.get("actions", {}) or {}
    action = (_acts.get("accounting") if (is_accounting_case(crimes) and _acts.get("accounting")) else
              _acts.get("financial" if financial else "general", ""))
    if code != "IN":
        return {"statutes": "None suggested: jurisdiction not confidently detected", "items": [], "code_used": None,
                "label": cfg.get("label", ""), "jurisdiction": cfg.get("jurisdiction_label", "Not detected"), "action": action}
    d = _parse_date(incident_date)
    eff = _parse_date(cfg.get("bns_effective_date", "2024-07-01"))
    if d is None:
        code_used, date_note = "IPC/BNS", "incident date unknown: both IPC (before 2024-07-01) and BNS (on/after) shown"
    elif d < eff:
        code_used, date_note = "IPC", f"incident date {d.isoformat()} is before {eff.isoformat()}: IPC applies (BNS equivalent shown for reference)"
    else:
        code_used, date_note = "BNS", f"incident date {d.isoformat()} is on/after {eff.isoformat()}: BNS applies"
    m, titles = cfg.get("ipc_to_bns", {}), cfg.get("ipc_titles", {})
    items, seen = [], set()
    for c in crimes:
        for sec in c.get("ipc", []):
            if sec in seen:
                continue
            seen.add(sec)
            bns = m.get(sec)
            t = titles.get(sec, "")
            if code_used == "IPC":
                items.append(f"IPC {sec} ({t})" + (f" [BNS {bns} after 2024-07-01]" if bns else " [BNS equivalent: verify]"))
            elif code_used == "BNS":
                items.append(f"BNS {bns} ({t}) [was IPC {sec}]" if bns else f"IPC {sec} ({t}) [BNS equivalent not in table: verify]")
            else:
                items.append(f"IPC {sec} / BNS {bns or '?'} ({t})")
        for sp in c.get("special", []):
            if sp not in seen:
                seen.add(sp)
                items.append(sp)
    statutes = "; ".join(items) if items else "None suggested from the narrative"
    basis = ", ".join((country or {}).get("basis", [])[:5])
    return {"statutes": statutes, "items": items, "code_used": code_used, "date_note": date_note,
            "label": cfg.get("label", ""), "source": cfg.get("ipc_to_bns_source", ""),
            "jurisdiction": cfg.get("jurisdiction_label", "India ({basis})").format(basis=basis), "action": action}


# ── next evidence ────────────────────────────────────────────────────────────
def is_financial_case(crime_category: str, crimes: list[dict]) -> bool:
    ne = RULES.get("next_evidence", {}) or {}
    cat = (crime_category or "").strip().lower()
    if cat and any(c in cat for c in ne.get("financial_categories", [])):
        return True
    fin = set((RULES.get("threat", {}) or {}).get("financial_basis_crimes", []))
    return sum(1 for c in crimes if c["crime"] in fin) >= 2


def next_evidence_for(crime_category: str, crimes: list[dict], evidence_provided: dict | None = None) -> list[dict] | None:
    """Crime-type aware list; None means 'use the generic checklist'."""
    _bc0 = (RULES.get("next_evidence", {}) or {}).get("by_crime", {}) or {}
    _typed_hit = any((c.get("crime") if isinstance(c, dict) else c) in _bc0 for c in (crimes or []))
    if not _typed_hit and not is_financial_case(crime_category, crimes):
        return None
    ev = evidence_provided or {}
    out = []
    _key = "financial"
    _bc = (RULES.get("next_evidence", {}) or {}).get("by_crime", {}) or {}
    for _c in crimes or []:
        _n = _c.get("crime") if isinstance(_c, dict) else _c
        if _n in _bc:
            _key = _bc[_n]
            break
    for pr, rec, why in (RULES.get("next_evidence", {}) or {}).get(_key, []):
        if rec.lower().startswith("photo") and ev.get("photo") and ev.get("document"):
            continue
        out.append({"priority": pr, "recommendation": rec, "reason": why})
    return out


# ── risk band ────────────────────────────────────────────────────────────────
def risk_band(score) -> str:
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "Unknown"
    for thr, label in (RULES.get("risk_display", {}) or {}).get("bands", [[70, "High"], [40, "Medium"], [0, "Low"]]):
        if s >= thr:
            return label
    return "Low"


def risk_display(score, model_used: bool, severity: str = "n/a") -> str:
    if model_used:
        try:
            return f"{float(score):.1f}%"
        except (TypeError, ValueError):
            return "N/A"
    tmpl = (RULES.get("risk_display", {}) or {}).get("fallback_label", "{band} (heuristic estimate)")
    return tmpl.format(band=risk_band(score), severity=severity or "n/a")


# ── timeline ─────────────────────────────────────────────────────────────────
_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_DATE_RX = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-](?:19|20)\d{2}"
    r"|\d{1,2}(?:st|nd|rd|th)?\s+(?:" + _MONTHS + r")[a-z]*\.?,?\s+(?:19|20)\d{2}"
    r"|(?:" + _MONTHS + r")[a-z]*\.?\s+\d{1,2},?\s+(?:19|20)\d{2}"
    r"|(?:between|from)\s+(?:about\s+)?(?:19|20)\d{2}\s+(?:and|to|-)\s+(?:19|20)\d{2}"
    r"|(?:in|since|during|from|by|of|until|till)\s+(?:(?:" + _MONTHS + r")[a-z]*\s+)?(?:19|20)\d{2})\b", re.I)


def dated_statements(modus: str, limit: int = 12) -> list[dict]:
    out = []
    for sent in re.split(r"(?<=[.!?;])\s+", modus or ""):
        for m in _DATE_RX.finditer(sent):
            out.append({"time": m.group(0).strip(), "event": sent.strip()[:200],
                        "source": "narrative (dated statement, as written)"})
            break
        if len(out) >= limit:
            break
    return out


def intake_timeline(incident_date: str, modus: str, existing: list | None = None) -> list[dict]:
    """Intake incident date as the first event (labelled as reported at intake),
    then dated statements from the narrative, then the existing clock-time events."""
    events = []
    d = _parse_date(incident_date)
    if (incident_date or "").strip():
        events.append({"time": d.isoformat() if d else incident_date.strip(),
                       "event": "Incident date as reported at case intake (may be FIR/intake date; verify against records)",
                       "source": "intake form"})
    events += dated_statements(modus)
    events += [dict(e, source=e.get("source", "narrative (clock time)")) for e in (existing or [])]
    return events


# ── threat basis ─────────────────────────────────────────────────────────────
def financial_crimes_in(crimes_all: list[str]) -> list[str]:
    fin = set((RULES.get("threat", {}) or {}).get("financial_basis_crimes", []))
    return [c for c in crimes_all if c in fin]


NOT_ASSESSED = (RULES.get("threat", {}) or {}).get("not_assessed", "NOT ASSESSED")


# ── p38 (2026-11-08): accounting fraud, white-collar, sanctions kind, entities, network names ──
ACCOUNTING_CRIME = "Accounting / Financial Statement Fraud"


def is_accounting_case(crimes) -> bool:
    for c in crimes or []:
        name = c.get("crime") if isinstance(c, dict) else c
        if name == ACCOUNTING_CRIME:
            return True
    return False


def is_violent(crimes_all) -> bool:
    marks = (RULES.get("threat", {}) or {}).get("violent_markers", [])
    return any(m.lower() in str(c).lower() for c in (crimes_all or []) for m in marks)


def is_white_collar(crimes_all) -> bool:
    """Financial-offence crimes present and no violent crime."""
    return bool(financial_crimes_in([c.get("crime") if isinstance(c, dict) else c for c in (crimes_all or [])])) \
        and not is_violent([c.get("crime") if isinstance(c, dict) else c for c in (crimes_all or [])])


def is_white_collar_text(text: str) -> bool:
    return is_white_collar(classify_crimes(text or ""))


def sanction_kind(value: str) -> str:
    """'regulatory' (exchange/SEBI debarment etc.), 'international' (UN/OFAC/EU), or 'unknown'."""
    cfg = RULES.get("sanctions_kinds", {}) or {}
    v = str(value or "")
    suf = cfg.get("strip_suffix", "")
    if suf:
        v = v.replace(suf, "")
    low = v.lower()
    if any(m in low for m in cfg.get("interpol_markers", [])) and not any(
            m in low for m in cfg.get("international_markers", []) if m not in ("consolidated list",)):
        return "interpol"
    if any(m in low for m in cfg.get("international_markers", [])):
        return "international"
    if any(re.search(r"(?<![a-z])" + re.escape(m) + r"(?![a-z])", low) for m in cfg.get("regulatory_markers", [])):
        return "regulatory"
    return "unknown"


def sanction_list_name(value: str) -> str:
    v = str(value or "")
    m = re.search(r"listed:\s*(.+?)(?:\s*\(regulatory/sanction list|$)", v)
    return (m.group(1).strip() if m else v.replace("YES", "").strip(" —-")) or "a regulatory list"


def supplement_entities(text: str, entities: dict | None) -> dict:
    """Rule-based additions to model NER: agencies, company names, money amounts.
    Never adds CRIME terms. Existing values are kept."""
    ents = {k: list(v) for k, v in (entities or {}).items()}
    cfg = RULES.get("entity_supplement", {}) or {}
    t = text or ""

    def _add(key, val):
        val = (val or "").strip(" ,.;:")
        if not val:
            return
        cur = ents.setdefault(key, [])
        if not any(val.lower() == c.lower() or val.lower() in c.lower() for c in cur):
            cur.append(val)

    for pat, label in (cfg.get("agencies", {}) or {}).items():
        flags = 0 if (pat.isupper() and len(pat) <= 5) else re.I
        if re.search(r"(?<![A-Za-z])" + re.escape(pat) + r"(?![A-Za-z])", t, flags):
            _add("AGENCY", label)
    suf = "|".join(re.escape(s) for s in sorted(cfg.get("org_suffixes", []), key=len, reverse=True))
    stop = set(cfg.get("org_stopwords", []))
    for m in re.finditer(r"((?:[A-Z][A-Za-z&.'-]+[ \t]+){0,3}(?:" + suf + r"))(?![A-Za-z])", t):
        words = m.group(1).split()
        while words and words[0] in stop:
            words = words[1:]
        if len(words) >= 2:
            _add("ORG", " ".join(words))
    for m in re.finditer(r"(?:(?:Rs\.?|INR|USD|US\$|\$|₹)\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:crore|lakh|million|billion|bn|mn))?"
                         r"|\d[\d,]*(?:\.\d+)?\s?(?:crore|lakh|million|billion)\s?(?:dollars|rupees|usd|inr)?)", t, re.I):
        _add("MONEY", m.group(0))
    return ents


def parse_network_names(network_text: str) -> list[dict]:
    """'Name - role' / 'Name (role)' / 'A and B - role' per line or comma -> [{'name','role'}]."""
    out = []
    _agencies = {a.lower() for a in ((RULES.get("entity_supplement", {}) or {}).get("agencies", {}) or {})}
    for line in re.split(r"[\n;]+", network_text or ""):
        line = line.strip(" -•*\t")
        if not line or re.match(r"(?i)^(investigated|probed|charged|prosecuted|examined|raided|case registered)\b", line):
            continue
        role = ""
        m = re.match(r"^(.*?)\s+[-–—:]\s+(.+)$", line)
        if m:
            line, role = m.group(1), m.group(2)
        m = re.match(r"^(.*?)\s*\((.+)\)\s*$", line)
        if m:
            line, role = m.group(1), role or m.group(2)
        for part in re.split(r",|\s+and\s+|\s*&\s*|/", line):
            part = part.strip(" .")
            if part and part.lower() not in _agencies and part[:1].isupper():
                out.append({"name": part, "role": role.strip()})
    return out


# ── p40 (2026-11-08): rule-based financial risk ──────────────────────────────
def _amount_crore(text: str) -> float:
    cfg = RULES.get("financial_risk_rules", {}) or {}
    usd = float(cfg.get("usd_crore_per_million", 8))
    best = 0.0
    for m in re.finditer(r"(?:rs\.?|inr|₹)?\s?(\d[\d,]*(?:\.\d+)?)\s?(crore|cr|lakh|billion|bn|million|mn)\b\s*(dollars|usd)?", (text or "").lower()):
        n = float(m.group(1).replace(",", ""))
        unit, cur = m.group(2), m.group(3)
        pre = (text or "").lower()[max(0, m.start() - 4):m.start() + 1]
        dollar = bool(cur) or "$" in pre
        if unit in ("crore", "cr"):
            v = n
        elif unit == "lakh":
            v = n / 100
        elif unit in ("billion", "bn"):
            v = n * 1000 * usd if dollar else n * 100
        else:
            v = n * usd if dollar else n / 10
        best = max(best, v)
    return best


def financial_risk_from_rules(crimes_all, narrative: str = "", watchlist: dict | None = None,
                              sanction_kind_value: str = "unknown") -> tuple[float, list[str]]:
    cfg = RULES.get("financial_risk_rules", {}) or {}
    pts = cfg.get("crime_points", {}) or {}
    names = [c.get("crime") if isinstance(c, dict) else str(c) for c in (crimes_all or [])]
    score, basis = 0.0, []
    for n in dict.fromkeys(names):
        if n in pts:
            score += pts[n]
            basis.append(f"{n} alleged (+{pts[n]})")
    fin = any(n in pts for n in names)
    amt = _amount_crore(narrative)
    for thr, p in cfg.get("amount_bands_crore", []):
        if amt >= thr:
            score += p
            basis.append(f"amount about Rs {amt:,.0f} crore or more (+{p})")
            break
    low = (narrative or "").lower()
    wl = watchlist or {}
    kw = [k for k in cfg.get("absconding_keywords", []) if k in low]
    if kw or str(wl.get("status", "")).startswith("FUGITIVE"):
        p = int(cfg.get("absconding_points", 15))
        score += p
        basis.append(f"absconding/fugitive indicator: {', '.join(kw[:2]) or 'dataset status'} (+{p})")
    wp = cfg.get("watchlist_points", {}) or {}
    if "YES" in str(wl.get("sanctions", "")):
        k = "regulatory" if sanction_kind_value == "regulatory" else "international"
        score += wp.get(k, 5)
        basis.append(f"{k} list name-match, identity unverified (+{wp.get(k, 5)})")
    if "YES" in str(wl.get("interpol", "")):
        score += wp.get("interpol", 10)
        basis.append(f"Interpol name-match, identity unverified (+{wp.get('interpol', 10)})")
    if fin and score < cfg.get("floor_if_financial_crime", 40):
        score = float(cfg.get("floor_if_financial_crime", 40))
        basis.append(f"floor for an alleged financial offence ({score:g})")
    return round(min(score, float(cfg.get("cap", 95))), 1), basis


# ── p41 (2026-11-08): case risk from crime severity (all crime types) ────────
def crime_risk_from_rules(crimes_all, narrative: str = "", entities: dict | None = None,
                          watchlist: dict | None = None) -> tuple[float, list[str], str]:
    cfg = RULES.get("crime_risk_rules", {}) or {}
    base = cfg.get("base", [])
    names = list(dict.fromkeys(c.get("crime") if isinstance(c, dict) else str(c) for c in (crimes_all or [])))
    scored = []
    for n in names:
        low = n.lower()
        best = max((p for m, p in base if m in low), default=None)
        if best is not None:
            scored.append((best, n))
    scored.sort(reverse=True)
    basis = []
    if scored:
        score = float(scored[0][0])
        basis.append(f"{scored[0][1]} {scored[0][0]}")
        extra = min(len(scored) - 1, 99) * int(cfg.get("extra_crime_points", 5))
        extra = min(extra, int(cfg.get("extra_crime_cap", 15)))
        if extra:
            score += extra
            basis.append(f"{len(scored) - 1} more offence type(s) +{extra}")
    else:
        score = 0.0
    md = cfg.get("modifiers", {}) or {}
    low = (narrative or "").lower()
    ents = entities or {}
    wl = watchlist or {}
    if ents.get("WEAPON"):
        score += md.get("weapon_entities", 10)
        basis.append(f"weapon mentioned +{md.get('weapon_entities', 10)}")
    fr = RULES.get("financial_risk_rules", {}) or {}
    if any(k in low for k in fr.get("absconding_keywords", [])):
        score += md.get("absconding", 10)
        basis.append(f"absconding/fled +{md.get('absconding', 10)}")
    amt = _amount_crore(narrative)
    if amt >= 1000:
        score += md.get("amount_1000_crore", 10)
        basis.append(f"amount Rs {amt:,.0f} crore +{md.get('amount_1000_crore', 10)}")
    elif amt >= 100:
        score += md.get("amount_100_crore", 5)
        basis.append(f"amount Rs {amt:,.0f} crore +{md.get('amount_100_crore', 5)}")
    if any(k in low for k in md.get("organised_keywords", [])):
        score += md.get("organised", 5)
        basis.append(f"organised/shell-entity language +{md.get('organised', 5)}")
    if any(k in low for k in md.get("multiple_victims_keywords", [])):
        score += md.get("multiple_victims", 5)
        basis.append(f"many victims/investors +{md.get('multiple_victims', 5)}")
    if str(wl.get("status", "")).startswith("FUGITIVE") or "YES" in str(wl.get("interpol", "")):
        score += md.get("fugitive_or_interpol_name_match", 5)
        basis.append(f"fugitive/Interpol name-match, unverified +{md.get('fugitive_or_interpol_name_match', 5)}")
    score = round(min(score, float(cfg.get("cap", 95))), 1)
    band = "Low"
    for thr, lab in cfg.get("bands", [[70, "High"], [40, "Medium"], [0, "Low"]]):
        if score >= thr:
            band = lab
            break
    label = cfg.get("label", "{band} ({score:.0f}/100)").format(band=band, score=score,
                                                                basis="; ".join(basis) or "no classified crime")
    return score, basis, label
