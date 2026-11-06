"""DOA Gradio tab + PDF: offline smoke test with a fictional subject (no network: SEC/dark-web off)."""
import os, subprocess
os.environ["DOA_AUDIT"] = "off"   # never write test runs into the real audit chain
from journalist_research.ui import gradio_doa as U
from journalist_research.runtime.doa_pipeline import SubjectProfile

R = []
def t(name, cond): R.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), name)

p = SubjectProfile(subject_id="S", name="Ravi Kalpnik", aliases=[], dob="1970-01-01", city="Delhi",
                   organizations=["Kalpnik Traders Pvt Ltd"])
m = U.detect_mention("Ravi Kalpnik (born 01/01/1970) of Delhi, director of Kalpnik Traders Pvt Ltd.", p)
t("anchors detected from text only", m.get("dob") == "1970-01-01" and m.get("city") == "Delhi" and m.get("organizations"))
t("no anchors invented", "dob" not in U.detect_mention("Ravi Kalpnik spoke today.", p))
t("namesake text has no name", U.detect_mention("Ravindra Kalp spoke.", p)["name"] == "")

DOCS = """URL: https://example.org/interview
TITLE: Interview (fictional)
TIER: HIGH
PUBLISHED: 2024-06-21
On 20 June 2024 Ravi Kalpnik of Delhi told reporters he has no outstanding loans. He said he was never a director of Kalpnik Traders Pvt Ltd.
---
URL: https://example.org/bank-record
TITLE: Loan record (fictional)
TIER: PRIMARY_OFFICIAL
KIND: RECORD
A bank loan record of Ravi Kalpnik, Delhi, shows a personal loan of Rs 12,00,000 sanctioned on 5 January 2024.
---
TITLE: MCA extract (fictional)
TIER: PRIMARY_OFFICIAL
KIND: RECORD
MCA master data dated 20/06/2024 shows Ravi Kalpnik of Delhi is a director of Kalpnik Traders Private Limited since 2019.
---
TITLE: Namesake (fictional)
Ravi Kalpnik, born 03/03/1985 in Pune, won a chess prize."""
docs = U.parse_documents(DOCS, p)
t("4 documents parsed with headers", len(docs) == 4 and docs[1].source_kind == "RECORD" and docs[0].tier == "HIGH")
t("unofficial URL cannot claim PRIMARY_OFFICIAL (capped HIGH)", docs[1].tier == "HIGH" and docs[1].mention["tier_claimed"] == "PRIMARY_OFFICIAL")
t("official domain keeps PRIMARY_OFFICIAL", U.parse_documents("URL: https://www.sebi.gov.in/x.html\nTIER: PRIMARY_OFFICIAL\nRavi Kalpnik order.", p)[0].tier == "PRIMARY_OFFICIAL")
t("published date kept", docs[0].published_at == "2024-06-21")

out = U.run_doa("Ravi Kalpnik", "", "1970-01-01", "Delhi", "Kalpnik Traders Pvt Ltd",
                "Did he deny a loan he had?", DOCS, False, False, False, use_public=False)
md, cov, fc, fnd, life, dl = out
t("6 outputs incl. lifestyle table", len(out) == 6)
path = dl.get("value") if isinstance(dl, dict) else None
t("no ESTABLISHED from pasted, unofficial documents", not any(r[0] == "ESTABLISHED" for r in (fnd or [])))
t("summary rendered", md.startswith("### DOA: Ravi Kalpnik"))
t("PDF written", path and os.path.exists(path))
t("PDF sidecar sha256", path and os.path.exists(path + ".sha256"))
t("loan EXISTENCE contradiction found", fc and any(r[0] == "EXISTENCE" for r in fc))
t("role contradiction found", fc and any(r[0] == "ROLE_EXISTENCE" for r in fc))
t("namesake rejected or unresolved, not attributed", "**1** rejected" in md or "rejected as namesakes" in md)
txt = subprocess.run(["pdftotext", path, "-"], capture_output=True, text=True).stdout if path else ""
t("PDF has IST time + SHA-256", "IST (UTC+05:30)" in txt and "SHA-256" in txt)
t("PDF states it is not a verdict", "not a verdict" in txt)
t("no banned conclusions in PDF", not any(x in txt.lower() for x in ("is guilty", "confirmed fraud", "does not exist")))
bad = U.run_doa("", "", "", "", "", "", "", False, False, False)
t("empty name refused", "required" in bad[0])
bad2 = U.run_doa("X", "", "01-01-1970", "", "", "", "", False, False, False)
t("bad DOB format refused", "YYYY-MM-DD" in bad2[0])

ok = sum(1 for _, v in R if v)
print(f"\nDOA UI: {ok}/{len(R)} PASS")
raise SystemExit(0 if ok == len(R) else 1)
