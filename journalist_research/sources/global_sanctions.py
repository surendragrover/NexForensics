"""
Global sanctions / debarment lists (free, official, no account):

  OFAC_SDN  US Treasury OFAC SDN (SDN.CSV + ALT.CSV + ADD.CSV), US-gov public domain
  UN_SC     UN Security Council Consolidated List (XML), public
  EU_FSF    EU Financial Sanctions Files, consolidated CSV (public token), EU reuse permitted
  WB_DEBAR  World Bank debarred & cross-debarred firms/individuals (JSON API the public page uses)

Each list: download -> gzip snapshot (never overwritten) -> normalised records keyed by
"<LIST>:<uid>" -> diff vs previous snapshot -> optional DB upsert into doa_sanctions_global.
A hit is a NAME LEAD only; identity needs DOB / nationality / ID anchors downstream.
"""
from __future__ import annotations
import csv, gzip, hashlib, io, json, os, re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from .http_polite import PoliteFetcher

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(HERE, "runtime", "artifacts", "sources", "global_sanctions")

OFAC = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/"
LISTS = {
    "OFAC_SDN": {"publisher": "US Treasury OFAC", "urls": [OFAC + "SDN.CSV", OFAC + "ALT.CSV", OFAC + "ADD.CSV"],
                 "licence": "US Government work, public domain", "page": "https://sanctionssearch.ofac.treas.gov/"},
    "UN_SC": {"publisher": "UN Security Council", "urls": ["https://scsanctions.un.org/resources/xml/en/consolidated.xml"],
              "licence": "UN public information", "page": "https://www.un.org/securitycouncil/content/un-sc-consolidated-list"},
    "EU_FSF": {"publisher": "European Commission (FSF)",
               "urls": ["https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw"],
               "licence": "EU Commission reuse policy (Decision 2011/833/EU)",
               "page": "https://data.europa.eu/data/datasets/consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions"},
    "WB_DEBAR": {"publisher": "World Bank Group",
                 "urls": ["https://apigwext.worldbank.org/dvsvc/v1.0/json/APPLICATION/ADOBE_EXPRNCE_MGR/FIRM/SANCTIONED_FIRM"],
                 # public key embedded in the World Bank's own debarred-firms page (not a private credential)
                 "headers": {"apikey": "z9duUaFUiEUYSHs97CU38fcZO7ipOPvm"},
                 "licence": "World Bank public data (CC BY 4.0)",
                 "page": "https://www.worldbank.org/en/projects-operations/procurement/debarred-firms"},
}


def _rec(lst, uid, names, aliases=(), typ="", programs=(), dobs=(), nationalities=(), addresses=(),
         listed="", remarks="", extra=None) -> Dict:
    clean = lambda xs: [x for x in dict.fromkeys(" ".join(str(x).split()) for x in xs if x and str(x).strip()) if x]
    r = {"list": lst, "uid": str(uid), "names": clean(names), "aliases": clean(aliases), "type": typ or "",
         "programs": clean(programs), "dobs": clean(dobs), "nationalities": clean(nationalities),
         "addresses": clean(addresses), "listed_date": listed or "", "remarks": (remarks or "")[:3000],
         "extra": extra or {}}
    r["record_sha256"] = hashlib.sha256(json.dumps(r, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return r


def _nil(v):
    v = (v or "").strip()
    return "" if v in ("-0-", "-0- ") else v


# ---------------- parsers ----------------
def parse_ofac(sdn: bytes, alt: bytes = b"", add: bytes = b"") -> Dict[str, Dict]:
    rd = lambda b: list(csv.reader(io.StringIO(b.decode("latin-1"))))
    alts, adds = {}, {}
    for row in rd(alt):
        if len(row) >= 4: alts.setdefault(row[0], []).append(_nil(row[3]))
    for row in rd(add):
        if len(row) >= 5:
            adds.setdefault(row[0], []).append(", ".join(x for x in map(_nil, row[2:6]) if x))
    out = {}
    for row in rd(sdn):
        if len(row) < 12 or not row[0].strip().isdigit(): continue
        uid, name, typ, prog, remarks = row[0], _nil(row[1]), _nil(row[2]), _nil(row[3]), _nil(row[11])
        dobs = re.findall(r"DOB ([^;]+?)(?:;|\.$|$)", remarks)
        nats = re.findall(r"(?:nationality|Nationality) ([^;]+?)(?:;|\.$|$)", remarks)
        out[f"OFAC_SDN:{uid}"] = _rec("OFAC_SDN", uid, [name], alts.get(uid, []), typ or "entity",
                                      prog.split("] [") if prog else [], dobs, nats, adds.get(uid, []), "", remarks)
    return out


def parse_un(xml: bytes) -> Dict[str, Dict]:
    root = ET.fromstring(xml)
    out = {}
    for kind, tag in (("individual", "INDIVIDUAL"), ("entity", "ENTITY")):
        for e in root.iter(tag):
            g = lambda t: (e.findtext(t) or "").strip()
            name = " ".join(x for x in (g("FIRST_NAME"), g("SECOND_NAME"), g("THIRD_NAME"), g("FOURTH_NAME")) if x)
            aliases = [(a.findtext("ALIAS_NAME") or "").strip() for a in e.iter(f"{tag}_ALIAS")]
            dobs = []
            for d in e.iter("INDIVIDUAL_DATE_OF_BIRTH"):
                dobs.append((d.findtext("DATE") or d.findtext("YEAR") or "").strip())
            nats = [(v.text or "").strip() for n in e.iter("NATIONALITY") for v in n.iter("VALUE")]
            addrs = [", ".join(x for x in ((a.findtext(k) or "").strip() for k in ("STREET", "CITY", "STATE_PROVINCE", "COUNTRY")) if x)
                     for a in e.iter(f"{tag}_ADDRESS")]
            uid = g("REFERENCE_NUMBER") or g("DATAID")
            out[f"UN_SC:{uid}"] = _rec("UN_SC", uid, [name], aliases, kind, [g("UN_LIST_TYPE")], dobs, nats, addrs,
                                       g("LISTED_ON"), g("COMMENTS1"))
    return out


def parse_eu(data: bytes) -> Dict[str, Dict]:
    text = data.decode("utf-8-sig", errors="replace")
    out: Dict[str, Dict] = {}
    raw: Dict[str, Dict] = {}
    for row in csv.DictReader(io.StringIO(text), delimiter=";"):
        uid = (row.get("Entity_LogicalId") or "").strip()
        if not uid: continue
        r = raw.setdefault(uid, {"names": [], "type": row.get("Entity_SubjectType", ""), "prog": set(), "dobs": [],
                                 "nat": [], "addr": [], "listed": row.get("Entity_DesignationDate", ""),
                                 "remark": row.get("Entity_Remark", ""), "ref": row.get("Entity_EU_ReferenceNumber", "")})
        nm = (row.get("NameAlias_WholeName") or "").strip()
        if nm and nm not in r["names"]: r["names"].append(nm)
        if row.get("Entity_Regulation_Programme"): r["prog"].add(row["Entity_Regulation_Programme"])
        for k, col in (("dobs", "BirthDate_BirthDate"), ("nat", "Citizenship_CountryDescription")):
            v = (row.get(col) or "").strip()
            if v and v not in r[k]: r[k].append(v)
        a = ", ".join(x for x in ((row.get(c) or "").strip() for c in ("Address_Street", "Address_City", "Address_CountryDescription")) if x)
        if a and a not in r["addr"]: r["addr"].append(a)
    for uid, r in raw.items():
        typ = {"P": "individual", "E": "entity"}.get((r["type"] or "").strip()[:1].upper(), r["type"])
        out[f"EU_FSF:{uid}"] = _rec("EU_FSF", uid, r["names"][:1], r["names"][1:], typ, sorted(r["prog"]), r["dobs"],
                                    r["nat"], r["addr"], r["listed"], r["remark"], {"eu_ref": r["ref"]})
    return out


def parse_wb(data: bytes) -> Dict[str, Dict]:
    j = json.loads(data.decode("utf-8", errors="replace"))
    out = {}
    for x in (j.get("response") or {}).get("ZPROCSUPP", []):
        uid = x.get("SUPP_ID")
        addr = ", ".join(str(v) for v in (x.get("SUPP_ADDR"), x.get("SUPP_CITY"), x.get("COUNTRY_NAME")) if v)
        typ = "individual" if (x.get("SUPP_TYPE_CODE") or "").upper() == "I" else "entity"
        out[f"WB_DEBAR:{uid}"] = _rec("WB_DEBAR", uid, [x.get("SUPP_NAME", "")], [], typ,
                                      [x.get("DEBAR_REASON") or "", "cross-debarment" if x.get("INELIG_FLG") == "Y" else ""],
                                      [], [x.get("COUNTRY_NAME") or ""], [addr],
                                      x.get("DEBAR_FROM_DATE") or "", "",
                                      {"debar_to": x.get("DEBAR_TO_DATE"), "grounds": x.get("DEBAR_REASON")})
    return out


PARSERS: Dict[str, Callable[[List[bytes]], Dict[str, Dict]]] = {
    "OFAC_SDN": lambda bs: parse_ofac(*bs),
    "UN_SC": lambda bs: parse_un(bs[0]),
    "EU_FSF": lambda bs: parse_eu(bs[0]),
    "WB_DEBAR": lambda bs: parse_wb(bs[0]),
}


# ---------------- sync ----------------
def _state_path(lst): return os.path.join(STORE, lst, "state.json")


def load_state(lst) -> Dict:
    p = _state_path(lst)
    return json.load(open(p)) if os.path.exists(p) else {}


def latest_records(lst) -> Dict[str, Dict]:
    st = load_state(lst)
    if not st.get("snapshot"): return {}
    p = os.path.join(STORE, lst, "snapshots", st["snapshot"], "records.json.gz")
    return json.load(gzip.open(p, "rt", encoding="utf-8")) if os.path.exists(p) else {}


def diff(old: Dict, new: Dict) -> Dict[str, List[str]]:
    o, n = set(old), set(new)
    return {"added": sorted(n - o), "removed": sorted(o - n),
            "changed": sorted(u for u in o & n if old[u]["record_sha256"] != new[u]["record_sha256"])}


def sync(lst: str, f: Optional[PoliteFetcher] = None, write_db: bool = False) -> Dict:
    cfg = LISTS[lst]; f = f or PoliteFetcher(timeout=180)
    st = load_state(lst)
    blobs, shas = [], []
    for u in cfg["urls"]:
        r = f.get(u, headers=cfg.get("headers"))
        if r.status != 200:
            return {"status": "NOT_AVAILABLE", "reason": f"HTTP {r.status} {u}"}
        blobs.append(r.content); shas.append(r.sha256)
    combined = hashlib.sha256("".join(shas).encode()).hexdigest()
    if combined == st.get("raw_sha256"):
        res = {"status": "UNCHANGED", "snapshot": st["snapshot"], "records": st.get("records")}
        if write_db and st.get("db_snapshot") != st["snapshot"]:
            from ..jobs.db import upsert_global_sanctions
            res["db"] = upsert_global_sanctions(lst, latest_records(lst), {"added": [], "removed": [], "changed": []},
                                                {"snapshot": st["snapshot"], "raw_sha256": combined})
            st["db_snapshot"] = st["snapshot"]; _save(lst, st)
        return res
    recs = PARSERS[lst](blobs)
    if not recs:
        return {"status": "NOT_AVAILABLE", "reason": "parsed 0 records (format change?)"}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snap = os.path.join(STORE, lst, "snapshots", stamp); os.makedirs(snap, exist_ok=False)
    for u, b in zip(cfg["urls"], blobs):
        name = re.sub(r"[^A-Za-z0-9._-]", "_", u.split("/")[-1].split("?")[0]) or "data"
        with gzip.open(os.path.join(snap, name + ".gz"), "wb") as fh: fh.write(b)
    with gzip.open(os.path.join(snap, "records.json.gz"), "wt", encoding="utf-8") as fh:
        json.dump(recs, fh, ensure_ascii=False)
    old = latest_records(lst)
    d = diff(old, recs)
    summary = {"status": "UPDATED", "list": lst, "snapshot": stamp, "raw_sha256": combined, "records": len(recs),
               "added": len(d["added"]), "removed": len(d["removed"]), "changed": len(d["changed"]),
               "fetched_at_utc": datetime.now(timezone.utc).isoformat(), "db": "SKIPPED (dry run)"}
    json.dump({**summary, **d}, open(os.path.join(snap, "diff.json"), "w"), indent=1)
    if write_db:
        from ..jobs.db import upsert_global_sanctions
        summary["db"] = upsert_global_sanctions(lst, recs, d, summary)
    _save(lst, {"snapshot": stamp, "raw_sha256": combined, "records": len(recs),
                "db_snapshot": stamp if write_db else st.get("db_snapshot")})
    # keep only the 3 newest snapshots on disk (diffs survive in the DB log)
    snaps = sorted(os.listdir(os.path.join(STORE, lst, "snapshots")))
    for old_s in snaps[:-3]:
        import shutil; shutil.rmtree(os.path.join(STORE, lst, "snapshots", old_s), ignore_errors=True)
    return summary


def _save(lst, st):
    os.makedirs(os.path.join(STORE, lst), exist_ok=True)
    p = _state_path(lst); tmp = p + ".tmp"
    json.dump(st, open(tmp, "w"), indent=1); os.replace(tmp, p)


def sync_all(f: Optional[PoliteFetcher] = None, write_db: bool = False) -> Dict:
    out = {}
    for lst in LISTS:
        try:
            out[lst] = sync(lst, f, write_db)
        except Exception as e:  # noqa: BLE001
            out[lst] = {"status": "ERROR", "error": f"{type(e).__name__}: {e}"[:400]}
    return out
