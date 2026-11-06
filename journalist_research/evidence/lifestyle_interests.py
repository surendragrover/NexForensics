"""
Public lifestyle & interests (DOA, 2026-11-06).

Surfaces a subject's hobbies and lifestyle ONLY from what public sources already say:
news reports, encyclopaedia pages, interviews and documents the investigator supplied.

Hard boundaries (anti-stalking / DPDP):
  * no health, religion, caste, sexuality, political affiliation, family/children, or daily routine
    and whereabouts: a sentence touching any of these is skipped whole;
  * every item carries its quote and source; a name-only document gives a LEAD, never a finding;
  * nothing here establishes a fact. High-cost lifestyle is a reporting lead to compare with
    declared income, never an inference of wrongdoing.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List, Optional

from journalist_research.common import independence as ind
from journalist_research.common.safety import redact

# interest term -> category (English + Hindi). Regex fragments, matched case-insensitively.
CATEGORIES: Dict[str, List[str]] = {
    "Sports & fitness": [r"golf(?:er|ing)?", r"cricket", r"tennis", r"squash", r"badminton", r"football", r"marathons?",
                         r"cycling", r"swimming", r"trekking", r"mountaineering", r"skiing", r"scuba", r"boxing",
                         r"chess", r"shooting \(sport\)", r"sport shooting", r"gym", r"bodybuilding",
                         r"गोल्फ", r"क्रिकेट", r"टेनिस", r"शतरंज", r"पर्वतारोहण"],
    "Horses & racing": [r"horse ?racing", r"race ?horses?", r"equestrian", r"polo", r"stud farm", r"घुड़सवारी", r"घोड़ों"],
    "Cars, bikes & aviation": [r"vintage cars?", r"classic cars?", r"supercars?", r"ferrari", r"lamborghini", r"rolls[- ]royce",
                               r"bentley", r"porsche", r"bugatti", r"formula (?:one|1)", r"motor ?racing", r"harley[- ]davidson",
                               r"private jets?", r"helicopters?", r"pilot'?s licen[cs]e", r"flying lessons",
                               r"विंटेज कार", r"निजी विमान"],
    "Boats": [r"super ?yachts?", r"yachts?", r"yachting", r"sailing", r"नौका", r"याट"],
    "Collecting": [r"art collect(?:or|ion)", r"collects? (?:art|paintings|watches|cars|wine|coins|stamps|antiques)",
                   r"rolex", r"patek philippe", r"watch collect(?:or|ion)", r"wine collect(?:or|ion)", r"fine wines?",
                   r"single malts?", r"antiques", r"संग्रह"],
    "Arts & culture": [r"music", r"singing", r"guitar", r"piano", r"painting", r"photography", r"poetry", r"theatre",
                       r"film ?making", r"dancing", r"reading", r"books", r"writing", r"संगीत", r"गायन", r"फोटोग्राफी",
                       r"कविता", r"पढ़ना", r"चित्रकारी"],
    "Travel & wildlife": [r"travel(?:ling|ing|s)?", r"safaris?", r"wildlife", r"bird ?watching", r"यात्रा", r"घूमना"],
    "Clubs & society": [r"gymkhana", r"golf club", r"country club", r"polo club", r"yacht club", r"rotary", r"lions club",
                        r"club member(?:ship)?", r"member of the [A-Z][\w ]{2,40}club"],
    "Gaming & betting": [r"casinos?", r"gambling", r"betting", r"poker", r"कैसीनो", r"जुआ", r"सट्टा"],
    "Philanthropy": [r"philanthrop\w*", r"charit(?:y|ies|able)", r"donat\w+", r"दान"],
    "Food & entertaining": [r"parties", r"partying", r"fine dining", r"cooking", r"chef", r"खाना बनाना"],
}
HIGH_COST = re.compile(r"race ?horse|stud farm|polo|super ?yacht|yacht|private jet|helicopter|ferrari|lamborghini|"
                       r"rolls[- ]royce|bentley|bugatti|porsche|supercar|vintage car|classic car|rolex|patek|art collect|"
                       r"casino|golf club|country club|polo club|yacht club|gymkhana|formula|fine wine|निजी विमान|याट|कैसीनो",
                       re.I)
# a word that says the sentence is about a pastime, not just a passing mention
CUES = re.compile(r"\b(hobby|hobbies|passion(?:ate)?|avid|keen|fond of|enjoys?|enjoyed|loves?|loved|interest(?:ed)? in|"
                  r"plays?|played|owns?|owned|bought|member of|collector|collects?|spends? (?:his|her|their) "
                  r"(?:weekends|free time|holidays)|took up|pastime|lavish|splurge\w*|known for)\b|शौक|शौकीन|पसंद|रुचि",
                  re.I)
# whole term counts on its own (unambiguous lifestyle words)
STRONG = re.compile(r"hobby|hobbies|pastime|race ?horse|polo|yacht|private jet|casino|gymkhana|golf|art collect|"
                    r"शौक|शौकीन", re.I)
# sentences touching protected areas are skipped entirely
SENSITIVE = re.compile(
    r"\b(health|illness|ill|hospital\w*|disease|diabet\w*|cancer|hiv|aids|surgery|disabilit\w*|mental|depress\w*|"
    r"rehab\w*|pregnan\w*|religio\w*|faith|temple|mosque|church|gurdwara|pilgrimage|puja|namaz|prayer|caste|dalit|"
    r"brahmin|sexual\w*|gay|lesbian|bisexual|transgender|dating|girlfriend|boyfriend|affair|mistress|wife|husband|"
    r"son|daughter|children|kids|grandchild\w*|school|party member|joined the (?:bjp|congress|aap)|"
    r"every (?:morning|evening|day|weekend) at|daily at|usually at|home address|lives at|resides at)\b|"
    r"बीमार|अस्पताल|मधुमेह|धर्म|मंदिर|मस्जिद|गुरुद्वारा|जाति|पत्नी|पति|बेटा|बेटी|बच्चे|हर सुबह|रोज़",
    re.I)
SELF_CUE = re.compile(r"\b(said|says|told|interview|tweeted|posted|wrote|according to (?:him|her))\b|कहा|बताया|इंटरव्यू", re.I)
PRONOUN_START = re.compile(r"^\s*(he|she|his|her|they|their|वह|वे|उन्होंने|उनका|उनकी|उन्हें)\b", re.I)
def _canon(t: str, cat: str) -> str:
    c = re.sub(r"\(\?:[^)]*\)\??", "", t)
    c = re.sub(r"s\?", "", c).replace("[- ]", " ").replace(" ?", " ").replace("?", "").replace("\\", "").replace("'", "")
    if "pilot" in t:
        return "pilot licence"
    c = cat.lower() if ("[" in c or "{" in c) else " ".join(c.split()).lower()
    fix = {"charit": "charity", "donatw+": "donation", "philanthropw*": "philanthropy", "collect": "collecting",
           "art collect": "art collecting", "watch collect": "watch collecting", "wine collect": "wine collecting",
           "club member": "club membership", "formula": "formula one", "shooting (sport)": "sport shooting",
           "travel": "travel", "super yacht": "yacht", "race horse": "racehorse"}
    return fix.get(c, c)


_TERMS = [(cat, _canon(t, cat), re.compile(r"(?<![\w])(" + t + r")(?![\w])", re.I))
          for cat, ts in CATEGORIES.items() for t in ts]


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?।])\s+|\n+", text or "") if len(s.strip()) > 12]


def _name_res(names: List[str]) -> List[re.Pattern]:
    out = []
    for n in names:
        n = (n or "").strip()
        if not n:
            continue
        out.append(re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, n.split())) + r"(?!\w)", re.I))
        parts = n.split()
        if len(parts) > 1 and len(parts[-1]) >= 4:          # surname alone, e.g. "Mallya"
            out.append(re.compile(r"(?<!\w)" + re.escape(parts[-1]) + r"(?!\w)", re.I))
    return out


def extract_interests(doc: Dict[str, Any], names: List[str]) -> List[Dict[str, Any]]:
    """Interest mentions about the subject in one document (dict form of InputDocument)."""
    nres = _name_res(names)
    self_auth = bool((doc.get("mention") or {}).get("self_authored"))   # the subject's own posts: every line is theirs
    out, prev_named = [], False
    for s in _sentences(doc.get("text", "")):
        named = any(r.search(s) for r in nres)
        about = self_auth or named or (prev_named and PRONOUN_START.search(s))
        prev_named = named
        if not about or SENSITIVE.search(s):
            continue
        cue = bool(CUES.search(s))
        seen = set()
        for cat, canon, rx in _TERMS:
            m = rx.search(s)
            if not m:
                continue
            term = canon
            if term in seen or not (cue or STRONG.search(m.group(1))):
                continue
            seen.add(term)
            out.append({"category": cat, "interest": term, "high_cost": bool(HIGH_COST.search(m.group(1))),
                        "basis": "SELF_REPORTED" if (self_auth or doc.get("source_kind") == "SELF" or SELF_CUE.search(s)) else "REPORTED",
                        "quote": redact(s[:260] + ("…" if len(s) > 260 else "")),
                        "document_id": doc.get("document_id"), "url": doc.get("url"),
                        "publisher": doc.get("publisher") or "", "published_at": doc.get("published_at"),
                        "lineage": ind.lineage_key(doc)})
    return out


def build_profile(docs: List[Dict[str, Any]], decisions: Dict[str, str], names: List[str]) -> Dict[str, Any]:
    """Aggregate per interest. decisions: document_id -> identity decision."""
    items: Dict[tuple, Dict[str, Any]] = {}
    for d in docs:
        dec = decisions.get(d.get("document_id"), "NOT_SUBJECT")
        if dec in ("NOT_SUBJECT", "NAMESAKE_REJECTED") or d.get("status", "OK") != "OK":
            continue
        for h in extract_interests(d, names):
            key = (h["category"], h["interest"])
            it = items.setdefault(key, {"category": h["category"], "interest": h["interest"], "high_cost": h["high_cost"],
                                        "attributed_lineages": set(), "lead_lineages": set(), "mentions": []})
            (it["attributed_lineages"] if dec == "SAME_SUBJECT_PROBABLE" else it["lead_lineages"]).add(h["lineage"])
            if len(it["mentions"]) < 3:
                it["mentions"].append({**h, "identity": dec})
    rows = []
    for it in items.values():
        a = len(it["attributed_lineages"])
        status = "CORROBORATED" if a >= 2 else "REPORTED" if a == 1 else "NAME_ONLY_LEAD"
        basis = "SELF_REPORTED" if all(m["basis"] == "SELF_REPORTED" for m in it["mentions"]) else "REPORTED"
        rows.append({"category": it["category"], "interest": it["interest"], "high_cost": it["high_cost"],
                     "status": status, "basis": basis, "independent_sources": a,
                     "lead_sources": len(it["lead_lineages"]), "mentions": it["mentions"]})
    order = {"CORROBORATED": 0, "REPORTED": 1, "NAME_ONLY_LEAD": 2}
    rows.sort(key=lambda r: (order[r["status"]], not r["high_cost"], -r["independent_sources"], r["category"], r["interest"]))
    costly = sorted({r["interest"] for r in rows if r["high_cost"] and r["status"] != "NAME_ONLY_LEAD"})
    next_paths = []
    if costly:
        next_paths.append("Compare the reported high-cost lifestyle (" + ", ".join(costly[:6]) + ") with declared income: "
                          "income-tax filings, election affidavit, company accounts, loan or insolvency records.")
    if any(r["status"] == "NAME_ONLY_LEAD" for r in rows):
        next_paths.append("Confirm name-only interest leads with a non-name anchor (DOB, city, organisation) before use.")
    return {"items": rows, "high_cost_reported": costly, "next_paths": next_paths,
            "excluded_areas": ["health", "religion", "caste", "sexuality", "political affiliation",
                               "family and children", "daily routine and whereabouts"],
            "fact_established": False}


def section_text(p: Dict[str, Any]) -> str:
    if not p or not p.get("items"):
        return ""
    parts = []
    for r in p["items"][:25]:
        m = r["mentions"][0]
        parts.append(f"{r['interest']} [{r['category']}] -> {r['status']}, {r['basis']}, sources={r['independent_sources']}"
                     f"{' HIGH-COST' if r['high_cost'] else ''}: \"{m['quote']}\" ({m['publisher'] or m['url']})")
    s = "; ".join(parts)
    if p.get("next_paths"):
        s += ". Next: " + " ".join(p["next_paths"])
    s += " Excluded by design: " + ", ".join(p["excluded_areas"]) + "."
    return s
