"""Offline tests: global sanctions parsers + SEC EDGAR parser + collect bridge (no network, no DB)."""
import json
from journalist_research.sources import global_sanctions as G, sec_edgar as E, collect as C
from journalist_research.runtime.doa_pipeline import SubjectProfile

R = []
def t(name, cond): R.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), name)

SDN = (b'36,"AEROCARIBBEAN AIRLINES",-0- ,"CUBA",-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0- \n'
       b'9001,"KALPNIK, Ravi","individual","SDGT",-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,"DOB 01 Jan 1970; nationality India."\n')
ALT = b'9001,1,"aka","KALPNIK, R.",-0- \n'
ADD = b'9001,5,-0- ,"Mumbai",-0- ,"India",-0- \n'
o = G.parse_ofac(SDN, ALT, ADD)
t("ofac 2 records", len(o) == 2)
r = o["OFAC_SDN:9001"]
t("ofac name + alias", r["names"] == ["KALPNIK, Ravi"] and r["aliases"] == ["KALPNIK, R."])
t("ofac dob + nationality from remarks", r["dobs"] == ["01 Jan 1970"] and r["nationalities"] == ["India"])
t("ofac address joined", r["addresses"] and "Mumbai" in r["addresses"][0])
t("ofac -0- nulls removed", o["OFAC_SDN:36"]["remarks"] == "")

UN = b"""<?xml version="1.0"?><CONSOLIDATED_LIST><INDIVIDUALS><INDIVIDUAL><DATAID>1</DATAID>
<FIRST_NAME>RAVI</FIRST_NAME><SECOND_NAME>KALPNIK</SECOND_NAME><UN_LIST_TYPE>Al-Qaida</UN_LIST_TYPE>
<REFERENCE_NUMBER>QDi.999</REFERENCE_NUMBER><LISTED_ON>2001-01-25</LISTED_ON><COMMENTS1>x</COMMENTS1>
<NATIONALITY><VALUE>India</VALUE></NATIONALITY><INDIVIDUAL_ALIAS><ALIAS_NAME>R. Kalp</ALIAS_NAME></INDIVIDUAL_ALIAS>
<INDIVIDUAL_ADDRESS><CITY>Delhi</CITY><COUNTRY>India</COUNTRY></INDIVIDUAL_ADDRESS>
<INDIVIDUAL_DATE_OF_BIRTH><DATE>1970-01-01</DATE></INDIVIDUAL_DATE_OF_BIRTH></INDIVIDUAL></INDIVIDUALS>
<ENTITIES><ENTITY><DATAID>2</DATAID><FIRST_NAME>ACME FRONT LTD</FIRST_NAME><REFERENCE_NUMBER>QDe.1</REFERENCE_NUMBER>
<UN_LIST_TYPE>Al-Qaida</UN_LIST_TYPE></ENTITY></ENTITIES></CONSOLIDATED_LIST>"""
u = G.parse_un(UN)
t("un individual + entity", set(u) == {"UN_SC:QDi.999", "UN_SC:QDe.1"})
t("un fields", u["UN_SC:QDi.999"]["names"] == ["RAVI KALPNIK"] and u["UN_SC:QDi.999"]["dobs"] == ["1970-01-01"]
  and u["UN_SC:QDi.999"]["aliases"] == ["R. Kalp"] and u["UN_SC:QDe.1"]["type"] == "entity")

EU = ("\ufefffileGenerationDate;Entity_LogicalId;Entity_EU_ReferenceNumber;Entity_SubjectType;Entity_DesignationDate;"
      "Entity_Remark;Entity_Regulation_Programme;NameAlias_WholeName;BirthDate_BirthDate;Citizenship_CountryDescription;"
      "Address_Street;Address_City;Address_CountryDescription\n"
      "01/11/2026;13;EU.1.2;P;2014-03-17;r;UKR;Ravi Kalpnik;1970-01-01;INDIA;;Pune;INDIA\n"
      "01/11/2026;13;EU.1.2;P;2014-03-17;r;UKR;Ravi K. Kalpnik;;;;;\n").encode()
e = G.parse_eu(EU)
t("eu grouped by logical id", list(e) == ["EU_FSF:13"])
t("eu names/aliases/dob", e["EU_FSF:13"]["names"] == ["Ravi Kalpnik"] and e["EU_FSF:13"]["aliases"] == ["Ravi K. Kalpnik"]
  and e["EU_FSF:13"]["dobs"] == ["1970-01-01"] and e["EU_FSF:13"]["type"] == "individual")

WB = json.dumps({"response": {"ZPROCSUPP": [{"SUPP_ID": 5, "SUPP_NAME": "KALPNIK TRADERS PVT LTD", "SUPP_TYPE_CODE": "F",
                 "COUNTRY_NAME": "India", "SUPP_CITY": "Mumbai", "SUPP_ADDR": "X", "DEBAR_FROM_DATE": "2020-01-01",
                 "DEBAR_TO_DATE": "2030-01-01", "DEBAR_REASON": "Fraudulent Practice", "INELIG_FLG": "N"}]}}).encode()
w = G.parse_wb(WB)
t("wb debarred firm parsed", w["WB_DEBAR:5"]["names"] == ["KALPNIK TRADERS PVT LTD"] and w["WB_DEBAR:5"]["type"] == "entity")

d = G.diff(o, {**{k: v for k, v in o.items() if k != "OFAC_SDN:36"}, "OFAC_SDN:1": o["OFAC_SDN:36"]})
t("diff added/removed", d["added"] == ["OFAC_SDN:1"] and d["removed"] == ["OFAC_SDN:36"])
t("record sha256 stable", G.parse_ofac(SDN, ALT, ADD)["OFAC_SDN:9001"]["record_sha256"] == r["record_sha256"])

prof = SubjectProfile(subject_id="S1", name="Ravi Kalpnik", aliases=[], organizations=["Kalpnik Traders Pvt Ltd"])
docs = C.global_documents(prof, records={"OFAC_SDN": o, "UN_SC": u, "EU_FSF": e, "WB_DEBAR": w})
hits = [x for x in docs if x.status == "OK"]
t("hits in OFAC ('LAST, First'), EU, UN and WB (organisation)", {x.checklist_item for x in hits} ==
  {"OFAC SDN (US)", "EU consolidated sanctions", "UN Security Council list", "World Bank debarment"})
t("every hit is NAME_ONLY_LEAD", hits and all(x.mention["match_kind"] == "NAME_ONLY_LEAD" for x in hits))
t("dob anchor carried when ISO", any(x.mention.get("dob") == "1970-01-01" for x in hits))
na = C.global_documents(prof, records={"OFAC_SDN": {}, "UN_SC": {}, "EU_FSF": {}, "WB_DEBAR": {}})
t("missing list -> UNAVAILABLE (never 'clean')", all(x.status == "UNAVAILABLE" for x in na) and len(na) == 4)

EF = json.dumps({"hits": {"total": {"value": 3, "relation": "eq"}, "hits": [
    {"_id": "0001104659-24-104529:tm1_ex99-2.htm", "_source": {"ciks": ["0000879764"], "display_names": ["TotalEnergies SE (CIK 0000879764)"],
     "form": "6-K", "file_date": "2024-10-01", "adsh": "0001104659-24-104529", "file_type": "EX-99.2"}}]}}).encode()
pe = E.parse_efts(EF)
t("efts total + hit", pe["total"] == 3 and len(pe["hits"]) == 1)
t("efts doc url built", pe["hits"][0]["url"] == "https://www.sec.gov/Archives/edgar/data/879764/000110465924104529/tm1_ex99-2.htm")
AT = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>ADANI X (0001234567)</title>
<content type="text/xml"><cik>0001234567</cik><name>ADANI X</name></content></entry></feed>"""
t("browse atom parsed", E.parse_browse(AT) == [{"cik": "0001234567", "name": "ADANI X"}])

class FakeSec:
    def __init__(self, res): self.res = res
    def full_text(self, n, max_hits=10): return dict(self.res, hits=list(self.res["hits"]))
sd = C.sec_documents(prof, FakeSec({**pe, "status": "OK", "sha256": "h"}))
t("sec hits -> MEDIUM leads", sd and all(x.tier == "MEDIUM" and x.mention["match_kind"] == "NAME_ONLY_LEAD" for x in sd))
sn = C.sec_documents(prof, FakeSec({"status": "NOT_AVAILABLE", "hits": []}))
t("sec blocked -> UNAVAILABLE", len(sn) == 1 and sn[0].status == "UNAVAILABLE")
s0 = C.sec_documents(prof, FakeSec({"status": "NO_RESULT", "hits": []}))
t("sec none -> NO_RESULT", s0[0].status == "NO_RESULT")

p = sum(1 for _, ok in R if ok)
print(f"\nGLOBAL SOURCES OFFLINE: {p}/{len(R)} PASS")
raise SystemExit(0 if p == len(R) else 1)
