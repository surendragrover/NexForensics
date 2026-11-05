"""Runs DOAPipeline over the REAL local corpora (no network). Read-only."""
import json, tempfile
from journalist_research.runtime.doa_pipeline import DOAPipeline, SubjectProfile
from journalist_research.sources.collect import collect, CHECK_SEBI, CHECK_UK

R = []
def t(n, c): R.append(c); print("PASS" if c else "FAIL", n)

# 1) company that IS in the synced SEBI corpus
p1 = SubjectProfile(subject_id="LIVE-1", name="Swastika Investmart Limited")
d1 = collect(p1)
sebi = [d for d in d1 if d.checklist_item == CHECK_SEBI and d.status == "OK"]
t("SEBI corpus hit for Swastika Investmart", len(sebi) >= 1)
t("hit carries page+offsets+sha", sebi and "page" in sebi[0].mention and len(sebi[0].mention["raw_sha256"]) == 64)
out = DOAPipeline("DOA-LIVE-1", "Has SEBI acted against this entity?", p1, d1,
                  checklist=[CHECK_SEBI, CHECK_UK], artifact_root=tempfile.mkdtemp()).run()
cov = {c["checklist_item"]: c["status"] for c in out["coverage"]}
t("coverage SEBI = REPORTED", cov.get(CHECK_SEBI) == "REPORTED")
t("coverage UK = NOT_ESTABLISHED (not found in sources searched)", cov.get(CHECK_UK) == "NOT_ESTABLISHED")

# 2) fictional person: nothing anywhere
p2 = SubjectProfile(subject_id="LIVE-2", name="Ravi Kalpnik Testperson")
out2 = DOAPipeline("DOA-LIVE-2", "Any regulatory action?", p2, collect(p2),
                   checklist=[CHECK_SEBI, CHECK_UK], artifact_root=tempfile.mkdtemp()).run()
cov2 = {c["checklist_item"]: (c["status"], c["reason"]) for c in out2["coverage"]}
t("no-hit SEBI -> NOT_ESTABLISHED", cov2[CHECK_SEBI][0] == "NOT_ESTABLISHED")
t("negative wording is scoped", "not proof of absence" in cov2[CHECK_SEBI][1].lower() or "sources searched" in cov2[CHECK_SEBI][1].lower())

# 3) a real UK-listed name (first primary-name individual in snapshot) -> lead, identity not auto-confirmed
import os
from journalist_research.sources import uk_sanctions as U
st = json.load(open(U.STATE)); recs = json.load(open(os.path.join(U.STORE, "snapshots", st["snapshot"], "records.json")))
uid, rec = next((u, r) for u, r in recs.items() if r["designation_type"] == "Individual" and r["names"])
p3 = SubjectProfile(subject_id="LIVE-3", name=rec["names"][0])
d3 = collect(p3)
uk = [d for d in d3 if d.checklist_item == CHECK_UK and d.status == "OK"]
t(f"UK hit for listed individual {uid}", any(d.source_id == f"uk-{uid}" for d in uk))
t("UK hit marked NAME_ONLY_LEAD", uk and uk[0].mention["match_kind"] == "NAME_ONLY_LEAD")
out3 = DOAPipeline("DOA-LIVE-3", "Is this person sanctioned?", p3, d3,
                   checklist=[CHECK_SEBI, CHECK_UK], artifact_root=tempfile.mkdtemp()).run()
dec = [i["decision"] for i in out3["identity"] if i["document_id"].startswith("uk-")]
t("name-only UK hit stays UNRESOLVED (no anchors)", dec and set(dec) == {"UNRESOLVED"})
t("identity_established never True", all(i["identity_established"] is False for i in out3["identity"]))
from journalist_research.sources.collect import _iso_dob
t("UK dob dd/mm/yyyy -> ISO", _iso_dob("07/11/1960") == "1960-11-07")
t("UK partial dob not an anchor", _iso_dob("00/00/1970") is None)
print(f"\n{sum(R)}/{len(R)} PASS"); raise SystemExit(0 if all(R) else 1)
