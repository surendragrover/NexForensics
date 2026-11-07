"""
engines/hybrid_rules.py — rule layer that runs AFTER the fine-tuned NER model.

The model's entities are kept. Rules only:
  1. map label aliases (PER -> PERSON) so downstream code sees one name;
  2. validate pattern-type labels the model emits (EMAIL, PHONE, IP, URL,
     UPI, HASH, ACCOUNT ...) and drop values that fail the pattern;
  3. ADD entities that deterministic patterns and lexicons find
     (Indian phone, UPI, IFSC, PAN, Aadhaar, account no., vehicle plate,
     money, crypto wallet, hash, IP, URL, email, weapon/drug/crime/threat
     words in English, Hinglish and Hindi);
  4. de-duplicate (case-insensitive, order kept).

Every value keeps where it came from in `provenance` (MODEL / RULE / BOTH).
Rules never change a model decision about PERSON/ORG/LOC except dropping
obvious junk (stop words, all-lowercase single words).

Rule file: models/hybrid_rules/hybrid_rules_v*.json — highest version wins.
No network, no DB.
"""
import json
import re
from pathlib import Path

RULES_VERSION_FALLBACK = "4.0.0"

# ── helpers ──────────────────────────────────────────────────────────────────
_VERHOEFF_D = [
    [0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],
    [3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],[5,9,8,7,6,0,4,3,2,1],
    [6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],
    [9,8,7,6,5,4,3,2,1,0]]
_VERHOEFF_P = [
    [0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],
    [8,9,1,6,0,4,3,5,2,7],[9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],
    [2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]


def verhoeff_ok(num: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


def _ipv4_ok(s: str) -> bool:
    parts = s.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 and (p == "0" or not p.startswith("0")) for p in parts)


def _luhn_ok(num: str) -> bool:
    total, alt = 0, False
    for ch in reversed(num):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _norm(v: str) -> str:
    return re.sub(r"\s+", " ", (v or "").strip()).strip(",.;:-—'\"() ")


# ── rule set ─────────────────────────────────────────────────────────────────
class HybridRules:
    def __init__(self, rules_dir=None, rules: dict | None = None):
        self.rules = rules or self._load(rules_dir)
        self.version = self.rules.get("version", RULES_VERSION_FALLBACK)
        r = self.rules
        self.alias = r.get("label_aliases", {})
        self.stop = {w.lower() for w in r.get("stopwords", [])}
        self.ignored = set(r.get("ignored_tokens", []))
        self.special = set(r.get("special_tokens", []))
        self.upi_psp = {p.lower() for p in r.get("upi_handles", [])}
        self.state_codes = set(r.get("vehicle_state_codes", []))
        self.account_ctx = re.compile(r.get("account_context_regex", r"(?i)\b(a/?c|acct|account|khata|खाता)\b"), re.I)
        self.lex = {}
        for label, words in r.get("lexicons", {}).items():
            words = sorted({w for w in words if w}, key=len, reverse=True)
            if not words:
                continue
            alt = "|".join(re.escape(w) for w in words)
            # word boundaries for Latin; Devanagari has no \b, so use look-arounds on letters
            self.lex[label] = re.compile(r"(?<![A-Za-z\u0900-\u097F])(" + alt + r")(?![A-Za-z\u0900-\u097F])", re.I)
        # p23 (v4.1): case-sensitive lexicons for short acronyms (ED, CBI, BNS ...),
        # so "ed"/"Ed" in ordinary text is not an agency.
        self.lex_cs = {}
        for label, words in r.get("lexicons_case_sensitive", {}).items():
            words = sorted({w for w in words if w}, key=len, reverse=True)
            if words:
                alt = "|".join(re.escape(w) for w in words)
                self.lex_cs[label] = re.compile(r"(?<![A-Za-z\u0900-\u097F])(" + alt + r")(?![A-Za-z\u0900-\u097F])")
        # labels whose values must not also sit in ORG/PERSON/LOC (an agency or a
        # law is not a person or a place)
        self.exclusive = list(r.get("exclusive_labels", []))
        self.gazetteers = {g["entity"]: {v.lower(): v for v in g["values"]} for g in r.get("context_rules", [])}
        self.risk = r.get("risk_score", {})
        self.sensitive = set(r.get("sensitive_labels", []))

    @staticmethod
    def _load(rules_dir):
        if not rules_dir:
            return {}
        files = list(Path(rules_dir).glob("hybrid_rules_v*.json"))
        def ver(p):
            m = re.search(r"_v(\d+)", p.name)
            return int(m.group(1)) if m else 0
        for p in sorted(files, key=ver, reverse=True):
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
        return {}

    # ── pattern extractors ───────────────────────────────────────────────────
    _RE = {
        "EMAIL": re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}(?![\w-])"),
        "URL": re.compile(r"\b(?:https?://|www\.)[^\s<>\"']+[^\s<>\"'.,;:!?)\]]", re.I),
        "IP": re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"),
        "PHONE_IN": re.compile(r"(?<![\d+])(?:\+91[\s-]?|0091[\s-]?|0)?([6-9]\d{4}[\s-]?\d{5})(?!\d)"),
        "PHONE_INTL": re.compile(r"(?<![\w+])\+(?!91)[1-9]\d{0,3}[\s-]?\d[\d\s-]{6,14}\d(?!\d)"),
        "UPI": re.compile(r"(?<![\w.-])([A-Za-z0-9._-]{2,64})@([A-Za-z][A-Za-z0-9]{1,20})(?![\w.@-])"),
        "IFSC": re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"),
        "PAN": re.compile(r"\b[A-Z]{3}[PCHFATBLJG][A-Z]\d{4}[A-Z]\b"),
        "AADHAAR": re.compile(r"(?<!\d)([2-9]\d{3})[\s-]?(\d{4})[\s-]?(\d{4})(?!\d)"),
        "ACCOUNT": re.compile(r"(?<!\d)\d{9,18}(?!\d)"),
        "VEHICLE": re.compile(r"\b([A-Z]{2})[\s-]?(\d{1,2})[\s-]?([A-Z]{1,3})[\s-]?(\d{4})\b"),
        "VEHICLE_BH": re.compile(r"\b\d{2}[\s-]?BH[\s-]?\d{4}[\s-]?[A-Z]{1,2}\b"),
        "MONEY": re.compile(
            r"(?:(?:₹|Rs\.?|INR|USD|US\$|\$|€|£|रु\.?|रुपये)\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:lakh|lakhs|lac|crore|crores|cr|million|mn|billion|bn|k|हज़ार|हजार|लाख|करोड़))?"
            r"|\d[\d,]*(?:\.\d+)?\s?(?:lakh|lakhs|lac|crore|crores|लाख|करोड़)(?:\s?(?:rupees|rupee|रुपये))?"
            r"|\d[\d,]*(?:\.\d+)?\s?(?:rupees|rupee|रुपये|dollars|USD|INR))", re.I),
        "CRYPTO_BTC": re.compile(r"\b(?:bc1[ac-hj-np-z02-9]{25,59}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b"),
        "CRYPTO_ETH": re.compile(r"\b0x[a-fA-F0-9]{40}\b"),
        "HASH": re.compile(r"\b(?:[a-fA-F0-9]{64}|[a-fA-F0-9]{40}|[a-fA-F0-9]{32})\b"),
        "DATE": re.compile(
            r"\b(?:\d{1,2}[/.-]\d{1,2}[/.-](?:19|20)\d{2}|(?:19|20)\d{2}-\d{2}-\d{2}"
            r"|\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?,?\s+(?:19|20)\d{2}"
            r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+(?:19|20)\d{2})\b", re.I),
    }

    _CAP = r"(?:[A-Z][A-Za-z&.'-]*|[A-Z]{2,})"
    _ORG_SUFFIX = re.compile(
        r"\b(?:" + _CAP + r"\s+){1,5}(?:Bank|Ltd\.?|Limited|LLP|Inc\.?|Corporation|Corp\.?|Pvt\.?\s+Ltd\.?|Private\s+Limited|"
        r"Industries|Enterprises|Holdings|Group|Breweries|Airlines|Infra|Infrastructure|Finance|Securities|Capital|Ventures|"
        r"Trust|Foundation|Society|Cooperative|Co-operative|Exports|Traders|Associates|Solutions|Technologies)\b")
    _PERSON_HON = re.compile(
        r"(?:\b(?:Mr|Mrs|Ms|Dr|Shri|Sri|Smt|Kumari|Sh|Late|Adv|Capt|Col|Justice)\.?\s+|\b[sdw]/o\.?\s+|\b(?:son|daughter|wife) of\s+)"
        r"(?P<name>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})")

    def find_patterns(self, text: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        taken: list[tuple[int, int]] = []

        def add(label, value, span):
            for a, b in taken:
                if span[0] < b and a < span[1]:
                    return
            taken.append(span)
            out.append((label, _norm(value)))

        # most specific first, so a phone inside a URL or a UPI handle is not double counted
        for m in self._RE["URL"].finditer(text):
            add("URL", m.group(0), m.span())
        for m in self._RE["EMAIL"].finditer(text):
            dom = m.group(0).split("@", 1)[1].lower()
            add("EMAIL", m.group(0), m.span())
        for m in self._RE["UPI"].finditer(text):
            if m.group(2).lower() in self.upi_psp:
                add("UPI", m.group(0), m.span())
        for m in self._RE["CRYPTO_ETH"].finditer(text):
            add("CRYPTO_WALLET", m.group(0), m.span())
        for m in self._RE["HASH"].finditer(text):
            add("HASH", m.group(0), m.span())
        for m in self._RE["CRYPTO_BTC"].finditer(text):
            v = m.group(0)
            if v.startswith("bc1") or (any(c.isdigit() for c in v) and any(c.isupper() for c in v) and any(c.islower() for c in v)):
                add("CRYPTO_WALLET", v, m.span())
        for m in self._RE["IP"].finditer(text):
            if _ipv4_ok(m.group(0)):
                add("IP", m.group(0), m.span())
        for m in self._RE["IFSC"].finditer(text):
            add("IFSC", m.group(0), m.span())
        for m in self._RE["PAN"].finditer(text):
            add("PAN", m.group(0), m.span())
        for m in self._RE["VEHICLE_BH"].finditer(text):
            add("VEHICLE", m.group(0), m.span())
        for m in self._RE["VEHICLE"].finditer(text):
            if m.group(1) in self.state_codes:
                add("VEHICLE", m.group(0), m.span())
        for m in self._RE["DATE"].finditer(text):
            add("DATE", m.group(0), m.span())
        for m in self._RE["MONEY"].finditer(text):
            add("MONEY", m.group(0), m.span())
        for m in self._RE["PHONE_IN"].finditer(text):
            add("PHONE", m.group(0), m.span())
        for m in self._RE["PHONE_INTL"].finditer(text):
            digits = re.sub(r"\D", "", m.group(0))
            if 8 <= len(digits) <= 15:
                add("PHONE", m.group(0), m.span())
        for m in self._RE["AADHAAR"].finditer(text):
            num = "".join(m.groups())
            if verhoeff_ok(num):
                add("AADHAAR", m.group(0), m.span())
        for m in self._RE["ACCOUNT"].finditer(text):
            left = text[max(0, m.start() - 30):m.start()]
            if self.account_ctx.search(left) and not _luhn_card_like(m.group(0), left):
                add("ACCOUNT", m.group(0), m.span())
        # p23 (v4.1): all lexicon hits compete; the longest span wins an overlap
        # ("Prevention of Corruption Act" is a LAW, not the CRIME "corruption"),
        # then they are added in text order.
        _lex_hits = []
        for label, rx in list(self.lex.items()) + list(getattr(self, "lex_cs", {}).items()):
            for m in rx.finditer(text):
                _lex_hits.append((m.start(), m.end(), label, m.group(0)))
        _chosen = []
        for a, b, label, val in sorted(_lex_hits, key=lambda h: (-(h[1] - h[0]), h[0])):
            if any(a < y and x < b for x, y, _, _ in _chosen):
                continue
            _chosen.append((a, b, label, val))
        for a, b, label, val in sorted(_chosen):
            add(label, val, (a, b))
        # ORG by legal/business suffix: "Kingfisher Airlines Ltd", "HDFC Bank"
        for m in self._ORG_SUFFIX.finditer(text):
            v = re.sub(r"^(?:The|A|An|At|In|On|Of|To|From|With|By|And)\s+", "", m.group(0))
            add("BANK" if v.endswith("Bank") else "ORG", v, m.span())
        # PERSON after an honorific or relation marker: "Shri Ram Lal", "s/o Mohan Das"
        for m in self._PERSON_HON.finditer(text):
            add("PERSON", m.group("name"), m.span("name"))
        for label, vals in self.gazetteers.items():
            for low, canon in vals.items():
                for m in re.finditer(r"(?<![A-Za-z])" + re.escape(low) + r"(?![A-Za-z])", text, re.I):
                    add(label, canon, m.span())
        return out

    # ── model output checks ──────────────────────────────────────────────────
    def _valid_model_value(self, label: str, v: str) -> bool:
        if not v or v in self.ignored or v in self.special:
            return False
        low = v.lower()
        if low in self.stop:
            return False
        if label in ("PERSON", "ORG", "LOC", "NATL", "BANK"):
            # a proper-noun entity needs a capital letter or Devanagari text,
            # and is not a lone stop word
            if not (any(c.isupper() for c in v) or re.search(r"[\u0900-\u097F]", v)):
                return False
            words = [w for w in re.split(r"\s+", low) if w]
            if words and all(w in self.stop for w in words):
                return False
            return True
        validators = {
            "EMAIL": self._RE["EMAIL"], "URL": self._RE["URL"], "IFSC": self._RE["IFSC"],
            "PAN": self._RE["PAN"], "HASH": self._RE["HASH"], "MONEY": None,
        }
        if label == "IP":
            return _ipv4_ok(v) or ":" in v and len(v) > 6
        if label == "PHONE":
            return 8 <= len(re.sub(r"\D", "", v)) <= 15
        if label in ("ACCOUNT",):
            return 9 <= len(re.sub(r"\D", "", v)) <= 18
        if label == "UPI":
            m = self._RE["UPI"].fullmatch(v)
            return bool(m and m.group(2).lower() in self.upi_psp)
        if label == "DOMAIN":
            return bool(re.fullmatch(r"(?:[A-Za-z0-9-]{1,63}\.)+[A-Za-z]{2,24}", v))
        if label in validators and validators[label] is not None:
            return bool(validators[label].fullmatch(v) or validators[label].search(v))
        return True

    # ── main entry ───────────────────────────────────────────────────────────
    def apply(self, text: str, model_entities: dict) -> tuple[dict, dict]:
        merged: dict[str, list[str]] = {}
        prov: dict[str, dict[str, str]] = {}

        def put(label, value, source):
            label = self.alias.get(label, label)
            v = _norm(value)
            if not v:
                return
            key = v.lower()
            bucket = merged.setdefault(label, [])
            pl = prov.setdefault(label, {})
            existing = next((x for x in bucket if x.lower() == key), None)
            if existing is None:
                bucket.append(v)
                pl[v] = source
            elif pl.get(existing) != source:
                pl[existing] = "BOTH"

        for label, values in (model_entities or {}).items():
            canon = self.alias.get(label, label)
            for v in values or []:
                v = _norm(v)
                if self._valid_model_value(canon, v):
                    put(canon, v, "MODEL")
        for label, v in self.find_patterns(text or ""):
            put(label, v, "RULE")
        # a fragment inside a longer value of the same label ("March" inside
        # "2 March 2016") is dropped; the longer value inherits BOTH
        for label, bucket in merged.items():
            keep = []
            for v in bucket:
                lv = v.lower()
                longer = [w for w in bucket if w is not v and len(w) > len(v) and re.search(r"(?<![\w])" + re.escape(lv) + r"(?![\w])", w.lower())]
                if longer:
                    tgt = longer[0]
                    if prov[label].get(tgt) != prov[label].get(v):
                        prov[label][tgt] = "BOTH"
                    prov[label].pop(v, None)
                else:
                    keep.append(v)
            merged[label] = keep
        # p23: a value found as AGENCY/LAW is removed from ORG/PERSON/LOC/BANK
        for ex in getattr(self, "exclusive", []):
            exv = {v.lower() for v in merged.get(ex, [])}
            if not exv:
                continue
            for other in ("ORG", "PERSON", "LOC", "BANK", "NATL"):
                if other in merged:
                    merged[other] = [v for v in merged[other] if v.lower() not in exv]
                    for v in list(prov.get(other, {})):
                        if v.lower() in exv:
                            prov[other].pop(v, None)
                    if not merged[other]:
                        merged.pop(other)
                        prov.pop(other, None)
        return merged, prov

    def score(self, ents: dict) -> float:
        cfg = self.risk or {}
        s = float(cfg.get("base", 0.0))
        # p23 (v4.1): procedural / status words (FIR, chargesheet, arrested ...) are
        # kept as entities but do not add risk
        non_scoring = {w.lower() for w in cfg.get("non_scoring_values", [])}
        for label, w in (cfg.get("per_entity", {}) or {}).items():
            s += len({x.lower() for x in ents.get(label, []) if x.lower() not in non_scoring}) * float(w)
        return round(min(s, float(cfg.get("cap", 95.0))), 1)


def _luhn_card_like(num: str, left_ctx: str) -> bool:
    """16-digit Luhn-valid number next to card words is a card, not a bank account."""
    return len(num) in (15, 16) and _luhn_ok(num) and bool(re.search(r"(?i)card|debit|credit", left_ctx))
