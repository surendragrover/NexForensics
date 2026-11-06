"""Offline tests for evidence/narrative_split (fictional data)."""
import os, tempfile
os.environ["DOA_AUDIT"] = "off"
from journalist_research.evidence.narrative_split import split_narrative, narrative_contradictions, classify_clause
from journalist_research.ui.gradio_doa import parse_documents, SubjectProfile
from journalist_research.runtime.doa_pipeline import DOAPipeline

BLOB = ("Meera Kaalpanik (Test) says she was never a director of Sahyadri Agro Exports Pvt Ltd (fictional). "
        "A fictional MCA-style record dated 14/06/2017 lists her as director of Sahyadri Agro Exports from 2015 to 2019. "
        "She also says she took no loan from Konkan Co-operative Bank (fictional), but a fictional bank notice dated "
        "02/09/2021 claims an outstanding loan of Rs 48,00,000 in her name. All data is fictional for testing.")
ok = fail = 0
def check(name, cond):
    global ok, fail
    print(("PASS " if cond else "FAIL ") + name); ok += bool(cond); fail += (not cond)

check("record clause", classify_clause("a bank notice dated 02/09/2021 claims an outstanding loan") == "RECORD")
check("self clause", classify_clause("She also says she took no loan from Konkan Bank") == "SELF")
check("self before record", classify_clause("She says the court record is wrong") == "SELF")
check("plain", classify_clause("All data is fictional for testing.") == "REPORT")
cl = split_narrative(BLOB)
check("clauses split on 'but'", len(cl) >= 5)
fc, asr = narrative_contradictions(BLOB, "SUBJ")
classes = sorted((c.doa_class, c.severity) for c in fc)
print("   ", classes)
check("director contradiction found", any(c.doa_class.startswith("ROLE") for c in fc))
check("loan contradiction found", any(c.attribute.startswith("loan") for c in fc))
check("no fact established", all(not c.fact_established and not c.guilt_established for c in fc))
fc2, _ = narrative_contradictions("Ravi said he lives in Pune. He was a teacher.", "S")
check("no false positive on plain text", fc2 == [])
P = SubjectProfile(subject_id="SUBJ-x", name="Meera Kaalpanik (Test)", aliases=[], dob="1979-03-12", city="Pune", organizations=[])
docs = parse_documents(BLOB, P)
check("blob auto-split into sub-documents", len(docs) >= 3)
r = DOAPipeline("T-NS", "q", P, docs, artifact_root=tempfile.mkdtemp()).run()
dec = [i["decision"] for i in r["identity"]]
check("investigator-supplied attributed", all(d == "SAME_SUBJECT_PROBABLE" for d in dec))
check("identity never established", all(not i["identity_established"] for i in r["identity"]))
st = (r.get("contradictions") or {}).get("structured", [])
print("   ", [(c["doa_class"], c["severity"]) for c in st])
check("DOA finds director contradiction", any(c["doa_class"].startswith("ROLE") for c in st))
check("DOA finds loan contradiction", any("loan" in (c.get("attribute") or c.get("explanation", "")).lower() for c in st))
# DOB conflict still wins over investigator attribution
P2 = SubjectProfile(subject_id="SUBJ-y", name="Meera Kaalpanik (Test)", aliases=[], dob="1985-01-01", city=None, organizations=[])
d2 = parse_documents("Meera Kaalpanik (Test), born 12/03/1979, was a director of X Ltd from 2015.", P2)
r2 = DOAPipeline("T-NS2", "q", P2, d2, artifact_root=tempfile.mkdtemp()).run()
check("DOB conflict still rejects", [i["decision"] for i in r2["identity"]] == ["NAMESAKE_REJECTED"])
print(f"\n{ok}/{ok+fail} PASS")
raise SystemExit(1 if fail else 0)
