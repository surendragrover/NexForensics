"""Offline tests: role / directorship / address contradictions (fictional data)."""
from journalist_research.evidence.role_contradiction import (
    extract_role_assertions as X, detect_role_contradictions as D, org_key, city_key, role_family)

R = []
def t(name, cond): R.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), name)
def A(text, sid, kind="REPORT"): return X(text, subject_id="S", source_id=sid, document_id="d-" + sid, lineage=sid, source_kind=kind)

t("org key strips suffixes", org_key("M/s Kalpnik Traders Pvt. Ltd.") == org_key("Kalpnik Traders Private Limited") == "kalpnik traders")
t("role family", role_family("Managing Director") == "director" and role_family("CEO") == "ceo" and role_family("निदेशक") == "director")
t("city key", city_key("12 MG Road, Pune 411001") == "pune" and city_key("Sector 15, Gurugram") == "gurugram")

deny = A("In an interview on 20 June 2024, Ravi Kalpnik said he was never a director of Kalpnik Traders Pvt Ltd.", "int")
mca = A("MCA master data dated 01/03/2024 shows Ravi Kalpnik is a director of Kalpnik Traders Private Limited since 2019.", "mca", "RECORD")
c = D(deny + mca)
t("never-director vs MCA record -> ROLE_EXISTENCE HIGH", len(c) == 1 and c[0].doa_class == "ROLE_EXISTENCE" and c[0].severity == "HIGH")
t("never fact / guilt; human review", c and not c[0].fact_established and not c[0].guilt_established and c[0].human_review_required)
t("same-span duplicates collapsed", len([a for a in mca if a.attribute == "role.held"]) == 1)
news = A("Ravi Kalpnik was a director of Kalpnik Traders Ltd, the paper reported on 2 May 2023.", "news")
c2 = D(deny + news)
t("vs news report -> MODERATE", len(c2) == 1 and c2[0].severity == "MODERATE")
t("other company not compared", D(deny + A("He is a director of Shree Ganesh Exports Ltd as of 01/01/2024.", "x", "RECORD")) == [])
t("wire copy (same lineage) not compared", D(deny + X("MCA data dated 01/03/2024: he is a director of Kalpnik Traders Ltd.",
  subject_id="S", source_id="int-copy", document_id="d9", lineage="int", source_kind="RECORD")) == [])
t("other subject not compared", D(deny + X("He is a director of Kalpnik Traders Ltd as of 01/03/2024.", subject_id="OTHER",
  source_id="m2", document_id="d10", lineage="m2", source_kind="RECORD")) == [])
notnow = A("In 2020 he was not a director of Kalpnik Traders Pvt Ltd, the company said.", "co")
t("'not a director in 2020' vs record dated 2024 -> no contradiction (change over time)", D(notnow + mca) == [])
same_time = A("On 01/03/2024 he was not a director of Kalpnik Traders Pvt Ltd, the company said.", "co2")
t("'not a director' on the record's date -> contradiction", len(D(same_time + mca)) == 1)

left = A("Ravi Kalpnik resigned as director of Shree Ganesh Exports Ltd in 2018, he told reporters.", "int2")
roc = A("The ROC record of 05/01/2021 shows he was a director of Shree Ganesh Exports Ltd.", "roc", "RECORD")
c3 = D(left + roc)
t("left 2018 vs record 2021 -> ROLE_TEMPORAL MODERATE", len(c3) == 1 and c3[0].doa_class == "ROLE_TEMPORAL" and c3[0].severity == "MODERATE")
t("filing-delay alternative offered", c3 and any("late" in x for x in c3[0].alternative_explanations))
roc_same_year = A("The ROC record of 05/09/2018 shows he was a director of Shree Ganesh Exports Ltd.", "roc2", "RECORD")
t("record inside the same year (overlap) -> no contradiction", D(left + roc_same_year) == [])

p1 = A("In March 2024 he was residing at 12 MG Road, Pune 411001.", "n1")
p2 = A("A court notice of 10 March 2024 lists him as r/o Sector 15, Gurugram.", "n2")
c4 = D(p1 + p2)
t("two cities same period -> ADDRESS LOW", len(c4) == 1 and c4[0].doa_class == "ADDRESS" and c4[0].severity == "LOW")
t("different periods -> no address contradiction", D(p1 + A("In 2019 he lived in Jaipur.", "n3")) == [])
t("Hindi निवासी extracted", any(a.attribute == "address.city" for a in A("रवि कल्पनिक दिल्ली के निवासी हैं, 2024 में।", "hi")))
t("no-connection denial", any(a.metadata.get("never") for a in A("He said he has no connection with Kalpnik Traders Ltd.", "nc")))

p = sum(1 for _, ok in R if ok)
print(f"\nROLE CONTRADICTION: {p}/{len(R)} PASS")
raise SystemExit(0 if p == len(R) else 1)
