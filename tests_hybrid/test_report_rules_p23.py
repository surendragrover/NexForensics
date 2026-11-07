"""p23 (2026-11-07) offline tests for the main-report fixes (no model, no DB, no network).
Run: cd /home/nexforensics/app && venv/bin/python tests_hybrid/test_report_rules_p23.py
"""
import json
import sys, pathlib
APP = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from analysis import report_rules as RR
from analysis.evidence_analysis import (
    _classify_crime_from_evidence, _analyze_facial_evidence, _compute_fraud_from_evidence,
    _assess_threat_from_evidence, _generate_actions_from_evidence, _lookup_suspect_background,
    _analyze_voice_evidence, _analyze_document_evidence,
)
from analysis.reasoning import _build_reasoning_engine, _build_intelligence_summary

ok = fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("FAIL", name)


NAR = ("Public-agency record describes allegations concerning consortium loans to Kingfisher Airlines Ltd. "
       "ED states that CBI FIRs concerned bank fraud and criminal conspiracy, and that its PMLA investigation "
       "examined alleged diversion/siphoning of loan funds through associated entities.")
ENTS = {"ORG": ["Kingfisher Airlines Ltd"], "PERSON": ["Vijay Maliya"], "AGENCY": ["ED", "CBI"], "LAW": ["PMLA"],
        "CRIME": ["bank fraud", "criminal conspiracy", "siphoning"]}

# 1. MO links
keep, drop = RR.filter_mo_links([
    {"case_id": "NXF-2024-0089", "crime_type": "Robbery", "fingerprint_score": 0, "category_match": False},
    {"case_id": "NXF-2024-0100", "crime_type": "Financial Crime", "fingerprint_score": 35, "category_match": True},
    {"case_id": "NXF-2024-0200", "crime_type": "Financial Crime", "fingerprint_score": 62, "category_match": True},
])
check("MO 0% different-category suppressed", any(d["case_id"] == "NXF-2024-0089" for d in drop))
check("MO below threshold suppressed", any(d["case_id"] == "NXF-2024-0100" for d in drop))
check("MO qualifying kept", [k["case_id"] for k in keep] == ["NXF-2024-0200"])
check("MO confidence from score", keep[0]["link_confidence"] == "medium" and RR.mo_confidence_from_score(80) == "high")
mo_none = {"query_used": NAR[:50], "linked_cases": [], "suppressed_links": drop[:1], "confirmed_links": [],
           "note": RR.mo_none_text()}
wl_empty = {"dataset_matches": {"count": 0}, "match_confidence": "WEAK", "status": "UNKNOWN"}
reas = _build_reasoning_engine("NXF-2026-0001", NAR, "", "Vijay Maliya", ENTS, "", object(), None, None,
                               [], [], [], mo_none, {"possible_leads": []}, wl_empty)
check("no MO hypothesis from suppressed link", not any("NXF-2024-0089" in h["hypothesis"] for h in reas["hypotheses"]))
crime = _classify_crime_from_evidence(ENTS, NAR, "Vijay Maliya", "", {}, {}, "", incident_date="2015-07-29",
                                      crime_category="Financial Crime")
summ = _build_intelligence_summary({"photo": True}, crime, wl_empty, mo_none, {"possible_leads": []}, reas, 5, "HIGH", 0, 50)
check("strongest lead says no MO link", "No MO link found" in summ["summary_points"]["strongest_lead"])
check("strongest lead not robbery", "NXF-2024-0089" not in summ["summary_points"]["strongest_lead"])
mo_ok = {"linked_cases": keep, "suppressed_links": [], "confirmed_links": []}
reas2 = _build_reasoning_engine("NXF-2026-0001", NAR, "", "x", {}, "", None, None, None, [], [], [], mo_ok,
                                {"possible_leads": []}, wl_empty)
check("MO hypothesis confidence from score", reas2["hypotheses"][0]["confidence"] == "medium")

# 2. Name matching
v = RR.spelling_variant_match("Vijay Maliya", "Vijay Mallya")
check("Maliya ~ Mallya POSSIBLE", v and v["tier"] == "POSSIBLE")
check("middle name allowed", RR.spelling_variant_match("Vijay Maliya", "Vijay Vittal Mallya") is not None)
check("Sid Mallya not a match", RR.spelling_variant_match("Vijay Maliya", "Sid Mallya") is None)
check("Vijay Malhotra not a match", RR.spelling_variant_match("Vijay Maliya", "Vijay Malhotra") is None)
check("Neerav ~ Nirav", RR.spelling_variant_match("Nirav Modi", "Neerav Modi") is not None)
check("Sharma ~ Sarma (sh/s)", RR.spelling_variant_match("Sunil Sharma", "Sunil Sarma") is not None)
check("exact equal is not 'variant'", RR.spelling_variant_match("Vijay Mallya", "vijay mallya") is None)
check("single token too ambiguous", RR.spelling_variant_match("Maliya", "Mallya") is None)
check("variants include mallya", "mallya" in RR.spelling_variants("maliya"))


class FakeDS:
    ready = True
    ROWS = [
        {"entity_name": "C. Joseph Vijay", "entity_type": "Person", "dataset": "targets_sanctions", "source_table": "targets_sanctions",
         "data": json.dumps({"id": "Q528496", "sanctions": "", "dataset": "Wikidata"})},
        {"entity_name": "Vijay Mallya", "entity_type": "Person", "dataset": "targets_sanctions", "source_table": "targets_sanctions",
         "data": json.dumps({"id": "Q173118", "sanctions": "", "dataset": "Wikidata;Wikidata Politically Exposed Persons", "countries": "in"})},
        {"entity_name": "Dr. Vijay Mallya", "entity_type": "LegalEntity", "dataset": "targets_sanctions", "source_table": "targets_sanctions",
         "data": json.dumps({"id": "NK-x", "sanctions": ";2021-06-01", "dataset": "India National Stock Exchange Debarred Entities"})},
        {"entity_name": "Vijay Mallya", "entity_type": "Wanted Criminal", "dataset": "wanted_list", "source_table": "public",
         "data": json.dumps({"alias": "Mallya", "crime": "Bank Fraud, Money Laundering", "location": "UK", "status": "WANTED"})},
        {"entity_name": "Sid Mallya", "entity_type": "Person", "dataset": "targets_sanctions", "source_table": "targets_sanctions",
         "data": json.dumps({"sanctions": ""})},
    ]
    def search(self, q, limit=25):
        return [dict(r) for r in self.ROWS]
    def summarize(self, rows):
        ds = {}
        for r in rows:
            ds[r["dataset"]] = ds.get(r["dataset"], 0) + 1
        return {"count": len(rows), "datasets": ds, "top": []}


wl = _lookup_suspect_background(FakeDS(), "Vijay Maliya", ENTS)
check("POSSIBLE tier", wl["match_confidence"].startswith("POSSIBLE"))
check("never CONFIRMED", "CONFIRMED" not in wl["criminal_history"])
check("namesake caution kept", "NAMESAKE CAUTION" in wl["criminal_history"])
check("variant list present", any(m["name"] == "Vijay Mallya" for m in wl.get("possible_variant_matches", [])))
check("Sid Mallya not in variants", not any(m["name"] == "Sid Mallya" for m in wl.get("possible_variant_matches", [])))
check("database match count > 0", wl["dataset_matches"]["count"] > 0)
check("wanted charge parsed from JSON", any(c.startswith("Bank Fraud, Money Laundering") for c in wl["charges"]))
check("status is POSSIBLE, not FUGITIVE", wl["status"].startswith("POSSIBLE"))
check("PEP from PEP list", wl["pep_status"].startswith("YES"))
check("sanction only from non-empty sanctions field", "Debarred" in wl["sanctions"])
check("identity confidence capped", wl.get("identity_confidence", "").startswith("0%"))

# 3. Face
fe = _analyze_facial_evidence({"anomaly_score": 67.3, "embedding_norm": 8.17, "label": "Anomalous"}, {})
check("no disguise claim", not any("disguise" in x.lower() or "deepfake" in x.lower() for x in fe["risk_indicators"] + fe["findings"]))
check("no anomaly % finding", not any("anomaly" in x.lower() for x in fe["findings"]))
check("norm shown as non-evidentiary", any("non-evidentiary" in x for x in fe["findings"]))
ve, de = _analyze_voice_evidence({}, {}), _analyze_document_evidence("", {}, {})
fr = _compute_fraud_from_evidence(ENTS, fe, ve, de, "", object(), None, "Vijay Maliya")
check("face does not raise identity fraud", fr["identity_fraud"] == 15.0)
check("face not a behavioural flag", not any("disguise" in f.lower() for f in fr["behavioral_flags"]))

# 4. Risk display
check("fallback shows band", RR.risk_display(88.0, False, "High").startswith("High (heuristic estimate") and "%" not in RR.risk_display(88.0, False, "High"))
check("model shows %", RR.risk_display(88.0, True) == "88.0%")

# 5. Crime classification
check("no Kingfisher crime", not any("kingfisher" in c.lower() for c in crime["all_crimes"]))
check("no 'Crime-Related Entities Detected'", "Crime-Related Entities Detected" not in crime["all_crimes"])
check("no keyword 'kingfisher' evidence", not any("kingfisher" in e.lower() for e in crime["evidence_found"]))
check("primary Bank Fraud", crime["primary"] == "Bank Fraud")
check("secondary from taxonomy", {"Criminal Conspiracy", "Money Laundering"} <= set(crime["all_crimes"]))
c_name = _classify_crime_from_evidence({}, "met at the office", "Vijay Mallya", "", {}, {}, "")
check("person name never a crime", not any("fugitive" in c.lower() for c in c_name["all_crimes"]))

# 6. Law / jurisdiction
check("India detected from agencies", crime["is_indian_jurisdiction"] and crime["jurisdiction"].startswith("India"))
check("no US code", "U.S.C" not in crime["statutes"])
check("IPC for 2015", "IPC 420" in crime["statutes"] and "IPC 120B" in crime["statutes"])
check("PMLA suggested", "PMLA" in crime["statutes"])
check("BNS mapping shown", "BNS 318(4)" in crime["statutes"] and "BNS 61(2)" in crime["statutes"])
check("not-verified label", "NOT verified" in crime["law_label"])
c25 = _classify_crime_from_evidence(ENTS, NAR, "x", "", {}, {}, "", incident_date="2025-02-01")
check("BNS on/after 2024-07-01", c25["statutes"].startswith("BNS 318(4)") and "BNS 316(2)" in c25["statutes"])
c_us = _classify_crime_from_evidence({}, "wire fraud in Ohio", "x", "", {}, {}, "Ohio")
check("unknown jurisdiction label not Federal/State", "Federal / State" not in c_us["jurisdiction"])
crime["_risk_heuristic"] = True
th = _assess_threat_from_evidence(0.0, 88.0, crime, fr, wl_empty, [], fe, ve, de, case_priority="Critical")
acts, _ = _generate_actions_from_evidence(crime, fr, wl_empty, th, 88.0, 0.0, [], "Critical")
check("no 'federal task force'", not any("federal task force" in a.lower() for a in acts))
check("ED/CBI coordination", any("ED (PMLA)" in a and "CBI" in a for a in acts))
check("no surveillance warrant on heuristic risk", not any("surveillance warrant" in a for a in acts))
acts_p, _ = _generate_actions_from_evidence(crime, fr, wl, th, 20.0, 0.0, [], "Critical")
check("POSSIBLE tier -> verify identity action", any(a.startswith("VERIFY IDENTITY") for a in acts_p))
check("POSSIBLE tier -> no sanctions/prosecution action", not any(a.startswith(("SANCTIONS", "PROSECUTION", "INTERPOL")) for a in acts_p))
summ_p = _build_intelligence_summary({"photo": True}, crime, wl, mo_none, {"possible_leads": []}, reas, 5, "HIGH", 0, 50)
check("known match says POSSIBLE not Yes", summ_p["investigation_status"]["known_criminal_match"].startswith("POSSIBLE"))

# 7. Next evidence
ne = summ["next_evidence"]
recs = " | ".join(n["recommendation"] for n in ne)
check("financial next evidence: loan docs", "Loan sanction" in recs and "Bank statements" in recs)
check("financial next evidence: MCA/ED-CBI/court/SEBI", all(k in recs for k in ("MCA", "ED / CBI", "DRT", "SEBI")))
check("no voice/CCTV/vehicle High", not any(n["priority"] == "High" and any(k in n["recommendation"].lower() for k in ("voice", "cctv", "vehicle")) for n in ne))

# 8. Threat matrix
check("escalation NOT ASSESSED", th["escalation_prob"] is None and th["escalation_display"] == "NOT ASSESSED")
check("cyber NOT ASSESSED", th["cyber"].startswith("NOT ASSESSED"))
check("financial has basis", th["financial"].startswith(("HIGH", "Medium")) and "narrative" in th["basis"]["financial"])
check("escalation basis stated", "cannot be estimated" in th["basis"]["escalation"])

# 10. Timeline
tl = RR.intake_timeline("2015-07-29", NAR, [])
check("intake date in timeline", tl and tl[0]["time"] == "2015-07-29" and "intake" in tl[0]["event"].lower())
tl2 = RR.intake_timeline("", "On 12 March 2016 he left India. In 2019 he was declared a fugitive.", [])
check("dated statements extracted", len(tl2) == 2 and "2016" in tl2[0]["time"])

# 11. Case ID + time
cid, ref, note = RR.resolve_case_id("Vijay Maliya", "Vijay Maliya")
check("person-name case id replaced", cid.startswith("NXF-") and ref == "Vijay Maliya" and note)
check("NXF format", bool(__import__("re").fullmatch(r"NXF-\d{4}-\d{4}", cid)))
check("empty case id generated", RR.resolve_case_id("", "x")[0].startswith("NXF-"))
check("real case id kept", RR.resolve_case_id("FIR-0123/2015", "x") == ("FIR-0123/2015", None, ""))
check("IST label", RR.fmt_ist().endswith("IST (+05:30)"))

print(f"p23 report rules: {ok}/{ok+fail} PASS")
sys.exit(1 if fail else 0)
