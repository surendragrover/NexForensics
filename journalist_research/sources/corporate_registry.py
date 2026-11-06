"""
Corporate registries -> people/company network (DOA 1.2).

Free, public sources only:
  ICIJ Offshore Leaks  local tables doa_icij_* (release 20260909): officers, entities,
                       addresses, intermediaries, relationships (Panama/Paradise/Pandora/...)
  UK Companies House   find-and-update.company-information.service.gov.uk (HTML, robots-allowed):
                       officer search -> appointments (DOB month/year) -> co-officers
  GLEIF LEI            api.gleif.org (no key): legal entity, direct and ultimate parent

Every row keeps its source URL / node id. A name hit is a NAME_ONLY_LEAD unless a
non-name anchor matches (UK: date of birth month + year). A DOB conflict marks the
officer NAMESAKE_REJECTED and keeps it out of the network.
Nothing here is a finding: these are leads for a journalist to check.
"""
from __future__ import annotations

import concurrent.futures as cf
import re
import time
import unicodedata
from datetime import date
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

CH = "https://find-and-update.company-information.service.gov.uk"
GLEIF = "https://api.gleif.org/api/v1"
ICIJ_NODE = "https://offshoreleaks.icij.org/nodes/{}"

TITLES = {"dr", "mr", "mrs", "ms", "miss", "sir", "shri", "smt", "prof", "lord", "lady", "hon", "dame", "md"}
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                       "september", "october", "november", "december"], 1)}

# Secrecy / offshore jurisdictions (ICIJ codes and descriptions, GLEIF ISO codes)
SECRECY_CODES = {"BAH", "BS", "BVI", "VG", "VGB", "KNA", "KN", "NEV", "PMA", "PA", "SEY", "SYC", "SC", "SAM", "WS",
                 "NIUE", "NU", "BM", "BMU", "KY", "CYM", "CAYMN", "COOK", "CK", "ANG", "AI", "BLZ", "BZ", "LABUA",
                 "MU", "MUS", "JE", "JEY", "GG", "GGY", "IM", "IMN", "LI", "LIE", "MH", "MHL", "VU", "VUT",
                 "BRB", "BB", "AW", "ABW", "GI", "GIB", "MC", "MCO", "AD", "TC", "TCA", "CW", "LU", "CY", "MT", "MLT"}
SECRECY_WORDS = ("virgin islands", "bahamas", "panama", "seychelles", "samoa", "niue", "bermuda", "cayman",
                 "cook islands", "anguilla", "belize", "labuan", "mauritius", "jersey", "guernsey", "isle of man",
                 "liechtenstein", "marshall islands", "vanuatu", "nevis", "barbados", "aruba", "gibraltar",
                 "monaco", "andorra", "turks", "curacao", "luxembourg", "cyprus", "malta")

MASS_ADDRESS = 50       # companies registered at one address
NOMINEE_ROLES = 50      # appointments held by one officer


# ------------------------------------------------------------------ names
def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()


def tokens(name: str) -> List[str]:
    t = re.sub(r"[^a-z ]", " ", _ascii(name).lower()).split()
    return [x for x in t if x not in TITLES]


def name_match(query: str, candidate: str) -> bool:
    """All query tokens present in the candidate (any order: 'MALLYA VIJAY' == 'Vijay Mallya').
    The candidate may carry one extra token (middle name/initial), never more."""
    q, c = set(tokens(query)), tokens(candidate)
    if len(q) < 2 or not q.issubset(set(c)):
        return False
    return len([x for x in c if x not in q]) <= 1


def is_secrecy(code: Optional[str], desc: Optional[str]) -> bool:
    if code and code.upper() in SECRECY_CODES:
        return True
    d = (desc or "").lower()
    return any(w in d for w in SECRECY_WORDS)


def _year(s) -> Optional[int]:
    m = re.search(r"(19|20)\d{2}", str(s or ""))
    return int(m.group(0)) if m else None


# ------------------------------------------------------------------ ICIJ (local DB)
def icij_network(names: List[str], *, conn=None, max_officers: int = 8, max_entities: int = 40,
                 max_coofficers: int = 12) -> Dict[str, Any]:
    out = {"source": "ICIJ Offshore Leaks (local copy, release 20260909)", "status": "OK",
           "officers": [], "entities": [], "co_officers": [], "intermediaries": [], "addresses": [], "notes": []}
    try:
        if conn is None:
            from journalist_research.jobs import db
            conn = db._conn_app()
        cur = conn.cursor()
    except Exception as e:  # noqa: BLE001
        out.update(status="NOT_AVAILABLE", notes=[f"database not reachable ({type(e).__name__})"])
        return out

    found: Dict[int, Dict[str, Any]] = {}
    for n in names:
        tk = sorted(tokens(n), key=len, reverse=True)
        if len(tk) < 2:
            continue
        cur.execute("SELECT node_id,name,countries,sourceID FROM doa_icij_officers WHERE name LIKE %s LIMIT 400",
                    (f"%{tk[0]}%",))
        for nid, nm, ctry, src in cur.fetchall():
            if name_match(n, nm) and nid not in found:
                found[nid] = {"node_id": nid, "name": nm, "countries": ctry, "leak": src,
                              "url": ICIJ_NODE.format(nid), "identity": "NAME_ONLY_LEAD"}
    officers = list(found.values())[:max_officers]
    out["officers"] = officers
    if not officers:
        return out

    ids = [o["node_id"] for o in officers]
    ph = ",".join(["%s"] * len(ids))
    cur.execute(f"SELECT node_id_start,node_id_end,link,start_date,end_date FROM doa_icij_relationships "
                f"WHERE node_id_start IN ({ph}) AND rel_type='officer_of' LIMIT 500", ids)
    roles = cur.fetchall()
    ent_ids = list(dict.fromkeys(r[1] for r in roles))[:max_entities]
    if not ent_ids:
        return out
    ph = ",".join(["%s"] * len(ent_ids))
    cur.execute(f"SELECT node_id,name,jurisdiction,jurisdiction_description,company_type,incorporation_date,"
                f"inactivation_date,struck_off_date,status,service_provider,sourceID,address "
                f"FROM doa_icij_entities WHERE node_id IN ({ph})", ent_ids)
    ents = {}
    for (nid, nm, jc, jd, ct, inc, inact, struck, st, sp, src, addr) in cur.fetchall():
        ents[nid] = {"node_id": nid, "name": nm, "jurisdiction": jd or jc, "jurisdiction_code": jc,
                     "company_type": ct, "incorporated": inc, "inactivated": inact or struck, "status": st,
                     "service_provider": sp, "leak": src, "address": addr, "url": ICIJ_NODE.format(nid),
                     "roles": [], "signals": []}
    for s, e, link, sd, ed in roles:
        if e in ents:
            nm = next(o["name"] for o in officers if o["node_id"] == s)
            ents[e]["roles"].append({"officer": nm, "role": link, "from": sd, "to": ed})

    # co-officers, intermediaries, registered addresses of those entities
    ph = ",".join(["%s"] * len(ents))
    eids = list(ents)
    cur.execute(f"SELECT node_id_start,node_id_end,rel_type,link FROM doa_icij_relationships "
                f"WHERE node_id_end IN ({ph}) AND rel_type IN ('officer_of','intermediary_of') LIMIT 3000", eids)
    co: Dict[int, Dict[str, Any]] = {}
    inter: Dict[int, Dict[str, Any]] = {}
    for s, e, rt, link in cur.fetchall():
        if s in ids:
            continue
        bucket = co if rt == "officer_of" else inter
        b = bucket.setdefault(s, {"node_id": s, "links": [], "entities": set()})
        b["entities"].add(e)
        b["links"].append(link)
    cur.execute(f"SELECT node_id_start,node_id_end FROM doa_icij_relationships "
                f"WHERE node_id_start IN ({ph}) AND rel_type='registered_address' LIMIT 500", eids)
    addr_of = cur.fetchall()

    def names_for(table, keys):
        if not keys:
            return {}
        p = ",".join(["%s"] * len(keys))
        cols = "node_id,name,countries" if table != "doa_icij_addresses" else "node_id,address,countries"
        cur.execute(f"SELECT {cols} FROM {table} WHERE node_id IN ({p})", list(keys))
        return {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    # rank co-officers by shared entities
    co_ranked = sorted(co.values(), key=lambda x: -len(x["entities"]))[:max_coofficers]
    con = names_for("doa_icij_officers", [c["node_id"] for c in co_ranked])
    # appointment count per co-officer (nominee signal)
    for c in co_ranked:
        cur.execute("SELECT COUNT(*) FROM doa_icij_relationships WHERE node_id_start=%s AND rel_type='officer_of'",
                    (c["node_id"],))
        nroles = cur.fetchone()[0]
        nm, ctry = con.get(c["node_id"], (f"node {c['node_id']}", None))
        out["co_officers"].append({"node_id": c["node_id"], "name": nm, "countries": ctry,
                                   "shared_entities": [ents[e]["name"] for e in c["entities"] if e in ents][:6],
                                   "roles": sorted(set(c["links"]))[:4], "total_appointments": nroles,
                                   "possible_nominee": nroles >= NOMINEE_ROLES, "url": ICIJ_NODE.format(c["node_id"])})
    inn = names_for("doa_icij_intermediaries", list(inter)[:15])
    for k, v in list(inter.items())[:15]:
        nm, ctry = inn.get(k, (f"node {k}", None))
        out["intermediaries"].append({"node_id": k, "name": nm, "countries": ctry,
                                      "entities": [ents[e]["name"] for e in v["entities"] if e in ents][:6],
                                      "url": ICIJ_NODE.format(k)})
    a_ids = list(dict.fromkeys(a for _, a in addr_of))[:20]
    an = names_for("doa_icij_addresses", a_ids)
    for a in a_ids:
        cur.execute("SELECT COUNT(*) FROM doa_icij_relationships WHERE node_id_end=%s AND rel_type='registered_address'",
                    (a,))
        cnt = cur.fetchone()[0]
        txt, ctry = an.get(a, ("", None))
        linked = [ents[e]["name"] for e, aa in addr_of if aa == a and e in ents]
        out["addresses"].append({"node_id": a, "address": (txt or "")[:160], "countries": ctry,
                                 "companies_registered_here": cnt, "mass_registration": cnt >= MASS_ADDRESS,
                                 "entities": linked[:6], "url": ICIJ_NODE.format(a)})
        for e, aa in addr_of:
            if aa == a and e in ents and cnt >= MASS_ADDRESS:
                ents[e]["signals"].append(f"MASS_REGISTRATION_ADDRESS ({cnt} companies at its address)")

    for e in ents.values():
        if is_secrecy(e["jurisdiction_code"], e["jurisdiction"]):
            e["signals"].append(f"SECRECY_JURISDICTION ({e['jurisdiction']})")
        y1, y2 = _year(e["incorporated"]), _year(e["inactivated"])
        if y1 and y2 and 0 <= y2 - y1 <= 2:
            e["signals"].append(f"SHORT_LIFESPAN ({y1}-{y2})")
        if any(i for i in inter.values() if e["node_id"] in i["entities"]):
            e["signals"].append("FORMED_VIA_INTERMEDIARY")
        if any(c["possible_nominee"] and e["name"] in c["shared_entities"] for c in out["co_officers"]):
            e["signals"].append("CO_OFFICER_HOLDS_50+_APPOINTMENTS (possible nominee)")
    out["entities"] = sorted(ents.values(), key=lambda x: -len(x["signals"]))
    return out


# ------------------------------------------------------------------ UK Companies House
def _ch_dob(text: str) -> Optional[Tuple[int, int]]:
    m = re.search(r"Born\s+([A-Za-z]+)\s+(\d{4})", text or "")
    if m and m.group(1).lower() in MONTHS:
        return MONTHS[m.group(1).lower()], int(m.group(2))
    return None


def _ch_role(txt: str) -> str:
    m = re.search(r"Role\s*\|\s*(?:(Active|Resigned)\s*\|\s*)?([^|]+)", txt or "")
    return m.group(2).strip() if m else ""


def _ch_appointed(txt: str) -> str:
    m = re.search(r"Appointed (on|before)\s*\|\s*([^|]+)", txt or "")
    return ("before " if m and m.group(1) == "before" else "") + m.group(2).strip() if m else ""


def uk_companies_house(names: List[str], dob: Optional[str], *, fetcher=None, max_officers: int = 4,
                       max_companies: int = 8, co_for: int = 4, deadline: float = 30.0) -> Dict[str, Any]:
    from bs4 import BeautifulSoup
    from journalist_research.sources.http_polite import PoliteFetcher, SourceBlocked
    f = fetcher or PoliteFetcher(delay=0.7, timeout=15)
    t0 = time.time()
    out = {"source": "UK Companies House", "status": "OK", "officers": [], "rejected": [], "companies": [],
           "co_officers": [], "notes": []}
    want = None
    if dob and re.fullmatch(r"\d{4}-\d{2}-\d{2}", dob):
        want = (int(dob[5:7]), int(dob[:4]))
    try:
        seen = set()
        for n in names[:2]:
            r = f.get(f"{CH}/search/officers?q={quote_plus(n)}")
            s = BeautifulSoup(r.text, "html.parser")
            for li in s.select("li.type-officer")[:10]:
                a = li.select_one("a")
                if not a or a.get("href") in seen or not name_match(n, a.get_text(" ", strip=True)):
                    continue
                seen.add(a.get("href"))
                meta = " ".join(p.get_text(" ", strip=True) for p in li.select("p"))
                cd = _ch_dob(meta)
                m = re.search(r"appointments\s+(\d+)", meta)
                o = {"name": a.get_text(" ", strip=True), "url": CH + a["href"], "born": cd and f"{cd[1]}-{cd[0]:02d}",
                     "appointments": int(m.group(1)) if m else None,
                     "address": meta.split(" - ")[-1][:140] if " - " in meta else ""}
                if want and cd:
                    o["identity"] = "DOB_MONTH_YEAR_MATCH" if cd == want else "NAMESAKE_REJECTED"
                else:
                    o["identity"] = "NAME_ONLY_LEAD"
                (out["rejected"] if o["identity"] == "NAMESAKE_REJECTED" else out["officers"]).append(o)
        out["officers"].sort(key=lambda o: (o["identity"] != "DOB_MONTH_YEAR_MATCH", -(o["appointments"] or 0)))
        out["officers"] = out["officers"][:max_officers]
        comp_seen = {}
        for o in out["officers"]:
            if time.time() - t0 > deadline:
                out["notes"].append("time budget reached; some appointments not read")
                break
            s = BeautifulSoup(f.get(o["url"]).text, "html.parser")
            for d in s.select("div[class^=appointment-]"):
                a = d.select_one("h2 a, a")
                if not a:
                    continue
                txt = d.get_text(" | ", strip=True)
                num = re.search(r"\((\w{8})\)", a.get_text(" ", strip=True))
                g = lambda lab: (re.search(lab + r"\s*\|\s*([^|]+)", txt) or [None, None])[1]
                row = {"company": re.sub(r"\s*\(\w{8}\)\s*$", "", a.get_text(" ", strip=True)),
                       "number": num.group(1) if num else None, "url": CH + a["href"],
                       "status": (g("Company status") or "").strip(), "role": _ch_role(txt),
                       "appointed": _ch_appointed(txt), "resigned": (g("Resigned on") or "").strip(),
                       "residence": (g("Place of residence") or "").strip(),
                       "officer": o["name"], "identity": o["identity"], "signals": []}
                if row["status"].lower() in ("dissolved", "liquidation", "struck off"):
                    row["signals"].append(row["status"].upper())
                key = row["number"] or row["company"]
                if key not in comp_seen:
                    comp_seen[key] = row
                    out["companies"].append(row)
        out["companies"] = out["companies"][:max_companies]
        for row in [c for c in out["companies"] if c["number"]][:co_for]:
            if time.time() - t0 > deadline:
                out["notes"].append("time budget reached; some co-directors not read")
                break
            s = BeautifulSoup(f.get(f"{CH}/company/{row['number']}/officers").text, "html.parser")
            for d in s.select("div[class^=appointment-]")[:15]:
                a = d.select_one("h2 a, a")
                if not a or any(name_match(n, a.get_text(" ", strip=True)) for n in names):
                    continue
                txt = d.get_text(" | ", strip=True)
                role = _ch_role(txt)
                res = (re.search(r"Resigned on\s*\|\s*([^|]+)", txt) or [None, ""])[1].strip()
                dm = re.search(r"Date of birth\s*\|\s*([A-Za-z]+ \d{4})", txt)
                out["co_officers"].append({"name": a.get_text(" ", strip=True), "company": row["company"],
                                           "role": role, "resigned": res, "appointed": _ch_appointed(txt),
                                           "born": dm.group(1) if dm else "", "url": CH + a["href"]})
    except SourceBlocked as e:
        out.update(status="NOT_AVAILABLE", notes=out["notes"] + [f"blocked: {e}"])
    except Exception as e:  # noqa: BLE001
        out["status"] = "PARTIAL" if out["officers"] else "NOT_AVAILABLE"
        out["notes"].append(f"{type(e).__name__}: {str(e)[:120]}")
    return out


# ------------------------------------------------------------------ GLEIF
def gleif_parents(company_names: List[str], *, fetcher=None, max_lookups: int = 5) -> Dict[str, Any]:
    import json
    from journalist_research.sources.http_polite import PoliteFetcher
    f = fetcher or PoliteFetcher(delay=0.3, timeout=15)
    out = {"source": "GLEIF LEI", "status": "OK", "entities": [], "notes": []}

    def rec(d):
        a = d["attributes"]["entity"]
        return {"lei": d["id"], "name": a["legalName"]["name"],
                "jurisdiction": a.get("jurisdiction"), "status": a.get("status"),
                "address": ", ".join(filter(None, [a["legalAddress"].get("city"), a["legalAddress"].get("country")])),
                "url": f"https://search.gleif.org/#/record/{d['id']}"}
    try:
        for n in list(dict.fromkeys(company_names))[:max_lookups]:
            r = f.get(f"{GLEIF}/lei-records?filter[entity.legalName]={quote_plus(n)}&page[size]=1")
            data = json.loads(r.text).get("data") or []
            if not data:
                continue
            e = rec(data[0])
            e["parents"] = []
            for kind in ("direct-parent", "ultimate-parent"):
                pr = f.get(f"{GLEIF}/lei-records/{e['lei']}/{kind}")
                if pr.status == 200:
                    pd = json.loads(pr.text).get("data")
                    if pd:
                        p = rec(pd)
                        p["kind"] = kind
                        p["offshore"] = is_secrecy((p["jurisdiction"] or "")[:2], p["address"])
                        e["parents"].append(p)
            e["signals"] = [f"OFFSHORE_{p['kind'].upper().replace('-', '_')} ({p['name']}, {p['jurisdiction']})"
                            for p in e["parents"] if p["offshore"]]
            out["entities"].append(e)
    except Exception as e:  # noqa: BLE001
        out["status"] = "PARTIAL" if out["entities"] else "NOT_AVAILABLE"
        out["notes"].append(f"{type(e).__name__}: {str(e)[:120]}")
    return out


# ------------------------------------------------------------------ orchestrator
def collect_corporate(profile, *, use_icij=True, use_uk=True, use_gleif=True, budget: float = 35.0) -> Dict[str, Any]:
    names = [n for n in [profile.name, *profile.aliases] if n and n.strip()]
    res: Dict[str, Any] = {"subject": profile.name, "dob": profile.dob, "sources": {}}
    with cf.ThreadPoolExecutor(3) as ex:
        futs = {}
        if use_icij:
            futs["icij"] = ex.submit(icij_network, names)
        if use_uk:
            futs["uk"] = ex.submit(uk_companies_house, names, profile.dob, deadline=budget - 8)
        for k, fu in futs.items():
            try:
                res["sources"][k] = fu.result(timeout=budget)
            except Exception as e:  # noqa: BLE001
                res["sources"][k] = {"status": "NOT_AVAILABLE", "notes": [f"{type(e).__name__}"]}
    if use_gleif:
        cands = list(profile.organizations) + [c["company"] for c in (res["sources"].get("uk") or {}).get("companies", [])
                                               if c.get("identity") == "DOB_MONTH_YEAR_MATCH" and "active" in c["status"].lower()]
        res["sources"]["gleif"] = gleif_parents(cands) if cands else {"status": "NOT_ASSESSED", "entities": [],
                                                                       "notes": ["no company to look up"]}
    return res
