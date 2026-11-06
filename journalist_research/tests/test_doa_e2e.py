"""
DOA end-to-end contract test on a FICTIONAL case.  No network, no database.

Fixture: Ravi Kalpnik (fictional) loan case
  D1 bank loan record (PRIMARY_OFFICIAL)     5 Jan 2024, Rs 8,00,000
  D2 news: told bank on 12 Mar 2024 'no outstanding loans'
  D3 wire: on 20 Jun 2024 said took loan in 2023 and repaid it
  D4 reprint of the same wire (same lineage -> counts once)
  D5 NAMESAKE: different DOB, Pune -> must be rejected
  D6 eCourts BLOCKED -> NOT_AVAILABLE (never NOT_FOUND)
  D7 blog: loan statement dated 03/04/2024 -> AMBIGUOUS_DAY_MONTH
  D8 SEBI no result -> NOT_ESTABLISHED with neutral wording
  D9 name-only mention -> UNRESOLVED, excluded from findings
  MCA not searched -> NOT_ASSESSED
Run:  cd /home/nexforensics/app && venv/bin/python -m journalist_research.tests.test_doa_e2e
"""
from __future__ import annotations
import sys, json, tempfile
from datetime import datetime, timezone

from journalist_research.runtime.doa_pipeline import DOAPipeline, SubjectProfile, InputDocument, DOSSIER_SECTIONS
from journalist_research.common.dates import parse_dates
from journalist_research.common import independence as ind
from journalist_research.common.status import determine_status, SourceTier, EvidenceStatus, to_canonical
from journalist_research.common.safety import find_banned, redact, assert_no_automatic_conclusion

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))


def unit_tests():
    d = parse_dates("Loan agreement dated 5 January 2024.")
    check("dates: '5 January 2024' -> DAY 2024-01-05", d and d[0].precision == "DAY" and str(d[0].start) == "2024-01-05", d)
    d = parse_dates("statement dated 03/04/2024")
    check("dates: 03/04/2024 flagged AMBIGUOUS_DAY_MONTH", d and "AMBIGUOUS_DAY_MONTH" in d[0].flags, d)
    d = parse_dates("dated 25/04/2024")
    check("dates: 25/04/2024 unambiguous DD/MM", d and not d[0].flags and str(d[0].start) == "2024-04-25", d)
    d = parse_dates("took the loan in 2023")
    check("dates: '2023' -> YEAR precision", d and d[0].precision == "YEAR", d)
    d = parse_dates("12 मार्च 2024 को")
    check("dates: Hindi month name parsed", d and str(d[0].start) == "2024-03-12", d)
    d = parse_dates("Rs 2,000 and 2023")
    check("dates: amount '2,000' not read as a year", len(d) == 1 and d[0].raw == "2023", d)

    one = [{"url": "https://a.test/x", "publisher": "A", "tier": "HIGH"}]
    check("independence: single source = 1 lineage", ind.independent_count(one) == 1)
    wire = [{"url": "https://a.test/1", "publisher": "A", "lineage_id": "W1", "tier": "MEDIUM"},
            {"url": "https://b.test/2", "publisher": "B", "lineage_id": "W1", "tier": "MEDIUM"}]
    check("independence: wire copies = 1 lineage", ind.independent_count(wire) == 1)
    arch = [{"url": "https://web.archive.org/x", "archive_of": "https://a.test/x", "tier": "HIGH"},
            {"url": "https://a.test/x", "tier": "HIGH"}]
    check("independence: archive capture = same lineage as origin", ind.independent_count(arch) == 1)
    ai = [{"url": "https://c.test", "tier": "NOT_EVIDENCE"}]
    check("independence: NOT_EVIDENCE contributes 0", ind.independent_count(ai) == 0)

    weak3 = determine_status(assessed=True, independent_lineages=3, best_tier=SourceTier.LOW, adequate_lineages=0)
    check("status: 3 weak sources capped at UNVERIFIED", weak3 == EvidenceStatus.UNVERIFIED, weak3)
    prim = determine_status(assessed=True, independent_lineages=1, best_tier=SourceTier.PRIMARY_OFFICIAL, adequate_lineages=1)
    check("status: primary official record -> ESTABLISHED", prim == EvidenceStatus.ESTABLISHED, prim)
    disp = determine_status(assessed=True, independent_lineages=2, best_tier=SourceTier.PRIMARY_OFFICIAL,
                            adequate_lineages=2, material_contradiction=True)
    check("status: material contradiction caps at DISPUTED", disp == EvidenceStatus.DISPUTED, disp)
    check("status: legacy CONFIRMED maps to STRONGLY_CORROBORATED",
          to_canonical("CONFIRMED") == EvidenceStatus.STRONGLY_CORROBORATED)
    check("status: blocked -> NOT_AVAILABLE",
          determine_status(assessed=True, independent_lineages=0, best_tier=None, unavailable=True) == EvidenceStatus.NOT_AVAILABLE)

    check("safety: banned phrase detected", find_banned("Subject has a clean record") == ["clean record"])
    r = redact("Call 9876543210, Aadhaar 1234 5678 9012, PAN ABCDE1234F")
    check("safety: phone/Aadhaar/PAN redacted", "9876543210" not in r and "1234 5678 9012" not in r and "ABCDE1234F" not in r, r)
    try:
        assert_no_automatic_conclusion({"guilt_established": True})
        check("safety: guilt flag raises", False)
    except RuntimeError:
        check("safety: guilt flag raises", True)


def fixture():
    profile = SubjectProfile("SUBJ-RAVI", "Ravi Kalpnik", dob="1980-02-14", city="Lucknow",
                             organizations=["Kalpnik Traders"])
    M = lambda **k: {"name": "Ravi Kalpnik", **k}
    docs = [
        InputDocument("D1", "S1", "https://records.example.test/loan/RK-001", "Loan record", tier="PRIMARY_OFFICIAL",
                      publisher="Sample Finance Ltd (loan record)", source_kind="RECORD", checklist_item="bank_record",
                      text="Loan record: A personal loan of Rs 8,00,000 was sanctioned to Ravi Kalpnik by Sample Finance Ltd. "
                           "Loan agreement dated 5 January 2024.", mention=M(dob="1980-02-14")),
        InputDocument("D2", "S2", "https://times.example.test/ravi-bank", "Bank declaration", tier="HIGH",
                      publisher="Example Times", published_at="2024-03-15", checklist_item="general_web",
                      text="Ravi Kalpnik told the bank on 12 March 2024 that he had no outstanding loans.",
                      mention=M(city="Lucknow")),
        InputDocument("D3", "S3", "https://wire.example.test/w1", "Statement", tier="MEDIUM",
                      publisher="Sample News Wire", lineage_id="WIRE-W1", published_at="2024-06-21", checklist_item="general_web",
                      text="In a statement on 20 June 2024, Ravi Kalpnik said he took the loan in 2023 and repaid it.",
                      mention=M(organizations=["Kalpnik Traders"])),
        InputDocument("D4", "S4", "https://paper.example.test/reprint", "Statement (reprint)", tier="MEDIUM",
                      publisher="Another Paper", lineage_id="WIRE-W1", published_at="2024-06-22", checklist_item="general_web",
                      text="In a statement on 20 June 2024, Ravi Kalpnik said he took the loan in 2023 and repaid it.",
                      mention=M(organizations=["Kalpnik Traders"])),
        InputDocument("D5", "S5", "https://sports.example.test/coach", "Coach profile", tier="MEDIUM",
                      publisher="Sample Sports", checklist_item="general_web",
                      text="Ravi Kalpnik, a cricket coach in Pune, said on 1 February 2024 that he had no loans.",
                      mention=M(dob="1991-07-30", city="Pune")),
        InputDocument("D6", "S6", "https://ecourts.example.test/search", "eCourts search", tier="PRIMARY_OFFICIAL",
                      publisher="eCourts", status="BLOCKED", checklist_item="eCourts", text=""),
        InputDocument("D7", "S7", "https://blog.example.test/ravi", "Blog post", tier="LOW", publisher="Sample Blog",
                      checklist_item="general_web",
                      text="A loan statement dated 03/04/2024 lists a personal loan of Rs 8,00,000 for Ravi Kalpnik.",
                      mention=M(city="Lucknow")),
        InputDocument("D8", "S8", "https://sebi.example.test/orders", "SEBI orders search", tier="PRIMARY_OFFICIAL",
                      publisher="SEBI", status="NO_RESULT", checklist_item="SEBI", text=""),
        InputDocument("D9", "S9", "https://fair.example.test/visitors", "Trade fair", tier="LOW", publisher="Fair list",
                      checklist_item="general_web", text="Ravi Kalpnik attended a trade fair.", mention=M()),
    ]
    return profile, docs


def e2e_tests(artifact_root):
    profile, docs = fixture()
    inv = "DOA-E2E-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    r = DOAPipeline(inv, "Did Ravi Kalpnik misstate his loans to the bank?", profile, docs,
                    checklist=["general_web", "bank_record", "eCourts", "SEBI", "MCA"],
                    artifact_root=artifact_root).run()
    idd = {i["document_id"]: i["decision"] for i in r["identity"]}
    check("identity: namesake D5 rejected on DOB conflict", idd.get("D5") == "NAMESAKE_REJECTED", idd)
    check("identity: name-only D9 UNRESOLVED", idd.get("D9") == "UNRESOLVED", idd)
    check("identity: D1-D4, D7 attributed on anchors",
          all(idd.get(k) == "SAME_SUBJECT_PROBABLE" for k in ("D1", "D2", "D3", "D4", "D7")), idd)
    check("namesake guard: no assertion from D5 or D9",
          not any(a["document_id"] in ("D5", "D9") for a in r["assertions"]))

    sc = r["contradictions"]["structured"]
    ex = [c for c in sc if c["doa_class"] == "EXISTENCE"]
    tm = [c for c in sc if c["doa_class"] == "TEMPORAL"]
    check("contradiction: EXISTENCE detected (12 Mar denial vs 5 Jan record)", len(ex) == 1, [c["explanation"] for c in ex])
    check("contradiction: EXISTENCE severity HIGH (repayment date not stated)", ex and ex[0]["severity"] == "HIGH")
    check("contradiction: alternative explanation recorded (repayment claim)",
          ex and any("repaid" in a for a in ex[0]["alternative_explanations"]))
    check("contradiction: TEMPORAL detected ('2023' vs 5 Jan 2024)", len(tm) >= 1, [c["explanation"] for c in tm])
    sigs = [(c["doa_class"], c["explanation"]) for c in sc]
    check("contradiction: wire reprint (D4) not double counted", len(sigs) == len(set(sigs)), sigs)
    check("contradiction: ambiguous 03/04/2024 record does NOT trigger EXISTENCE",
          not any("03/04/2024" in c["explanation"] for c in ex))
    check("contradiction: never establishes fact or guilt",
          all(not c["fact_established"] and not c["guilt_established"] and c["human_review_required"] for c in sc))
    check("legacy text engine result recorded for comparison", isinstance(r["contradictions"]["legacy_text"], list))

    amb = [e for e in r["timeline"] if "AMBIGUOUS_DAY_MONTH" in e["flags"]]
    check("timeline: ambiguous date carried with flag", len(amb) >= 1)
    check("timeline: publication dates kept separate from event dates",
          any(e["date_role"] == "PUBLICATION_DATE" for e in r["timeline"]) and
          any(e["date_role"] == "EVENT_DATE" for e in r["timeline"]))

    # Quality-weighted cap (revised rule): a self-statement must not demote a primary official record.
    f_exist = [f for f in r["findings"] if f["attribute"] == "loan.exists" and f["kind"] == "RECORD"]
    check("finding: primary loan record stays ESTABLISHED but is flagged as contested",
          f_exist and f_exist[0]["status"] == "ESTABLISHED" and f_exist[0]["contested_by_lower_quality"]
          and f_exist[0]["contradiction_ids"], [(f["value"], f["status"], f["contradiction_ids"]) for f in f_exist])
    f_deny = [f for f in r["findings"] if f["attribute"] == "loan.exists" and f["kind"] == "SELF_STATEMENT" and f["value"] == "False"]
    check("finding: 'no outstanding loans' denial is DISPUTED (contradicted by primary record)",
          f_deny and f_deny[0]["status"] == "DISPUTED", [(f["value"], f["status"]) for f in f_deny])
    f_blog = [f for f in r["findings"] if f["attribute"] == "loan.start" and f["kind"] == "RECORD" and "S7" in f["source_ids"]]
    check("finding: weak blog record date is DISPUTED (comparable-quality contest)",
          f_blog and f_blog[0]["status"] == "DISPUTED", [(f["value"], f["status"]) for f in f_blog])
    f_prim_start = [f for f in r["findings"] if f["attribute"] == "loan.start" and f["kind"] == "RECORD" and "S1" in f["source_ids"]]
    check("finding: primary record start date ESTABLISHED, contested flag set",
          f_prim_start and f_prim_start[0]["status"] == "ESTABLISHED" and f_prim_start[0]["contested_by_lower_quality"],
          [(f["value"], f["status"]) for f in f_prim_start])
    check("render: contested ESTABLISHED finding says review before publishing",
          f_exist and "review before publishing" in f_exist[0]["statement"])
    f_self = [f for f in r["findings"] if f["kind"] == "SELF_STATEMENT" and f["attribute"] == "loan.repaid"]
    check("finding: repayment claim is UNVERIFIED self-statement", f_self and f_self[0]["status"] == "UNVERIFIED",
          [(f["attribute"], f["status"]) for f in f_self])
    wire_f = [f for f in r["findings"] if "S3" in f["source_ids"] and "S4" in f["source_ids"]]
    check("finding: wire copies count as 1 independent lineage", wire_f and all(f["independent_lineages"] == 1 for f in wire_f))

    cov = {row["checklist_item"]: row["status"] for row in r["coverage"]}
    check("coverage: blocked eCourts -> NOT_AVAILABLE (not NOT_FOUND)", cov.get("eCourts") == "NOT_AVAILABLE", cov)
    check("coverage: SEBI no result -> NOT_ESTABLISHED", cov.get("SEBI") == "NOT_ESTABLISHED", cov)
    check("coverage: MCA not searched -> NOT_ASSESSED", cov.get("MCA") == "NOT_ASSESSED", cov)
    sebi = next(row for row in r["coverage"] if row["checklist_item"] == "SEBI")
    check("coverage: negative wording neutral", "not proof of absence" in sebi["reason"])

    secs = r["dossier"]["sections"]
    check("dossier: all sections present in spec order", [s["title"] for s in secs] == DOSSIER_SECTIONS)
    check("dossier: empty sections rendered as NOT_ASSESSED with reason",
          all(s["body"].startswith("NOT_ASSESSED:") for s in secs if s["status"] == "NOT_ASSESSED"))
    check("dossier: dark-web marked not performed",
          next(s for s in secs if s["title"] == "Dark-Web Intelligence")["body"].startswith("NOT_ASSESSED"))
    check("dossier: next steps cite contradiction IDs",
          any(s.get("related_contradiction_ids") for s in r["dossier"]["next_steps"]))
    check("safety: no banned phrases in rendered text", r["safety"]["banned_phrase_issues"] == [], r["safety"]["banned_phrase_issues"])
    check("safety: all conclusion flags false, human review required",
          not any(r["safety"][k] for k in ("fact_established", "identity_established", "guilt_established",
                                            "non_existence_established", "automatic_conclusion"))
          and r["safety"]["human_review_required"])
    check("artifact: written with SHA-256, unique per run", r.get("artifact_path") and len(r.get("sha256", "")) == 64)
    check("question layer ran (existing modules)", "error" not in r["question_layer"], r["question_layer"])
    check("synthesis ran (existing module)", "error" not in r["synthesis"], r["synthesis"])
    return r


def main():
    import os
    root = os.environ.get("DOA_ARTIFACT_ROOT") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runtime", "artifacts", "doa_e2e")
    os.makedirs(root, exist_ok=True)
    unit_tests()
    r = e2e_tests(root)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    for name, ok, detail in RESULTS:
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -> {str(detail)[:400]}"))
    print(f"\nDOA E2E: {passed}/{len(RESULTS)} PASS")
    print("artifact:", r.get("artifact_path"), "sha256:", r.get("sha256"))
    print("contradictions:", json.dumps([(c['doa_class'], c['severity'], c['explanation']) for c in r['contradictions']['structured']], ensure_ascii=False, indent=1))
    print("legacy_text_contradictions:", len(r["contradictions"]["legacy_text"]))
    print("legacy_vs_canonical:", json.dumps([(f["attribute"], f["kind"], f["status"], f["legacy_confidence"]) for f in r["findings"]], ensure_ascii=False))
    print("synthesis:", r["synthesis"], "| dossier:", r["dossier"]["legacy_status"], "->", r["dossier"]["canonical_status"])
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
