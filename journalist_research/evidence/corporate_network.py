"""
People & company network + shell-company indicators (DOA 1.2).

Turns corporate_registry output into
  * a graph (nodes: PERSON / COMPANY / INTERMEDIARY / ADDRESS; edges with role + source URL),
  * shell indicators per company (secrecy jurisdiction, mass-registration address,
    possible nominee co-officer, short lifespan, intermediary, offshore parent, dissolved),
  * dossier text for "Companies & Ownership" and "People & Relationship Network",
  * an export in the knowledge_graph_engine input format (graph{nodes, edges}).

Indicators are LEADS. A company in a secrecy jurisdiction is not a crime, and a namesake
officer is not the subject. Status is always INDICATOR / NAME_ONLY_LEAD, never a finding.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

PROTECT = "Indicators are leads for checking, not findings of wrongdoing."
_SUFFIX = re.compile(r"\b(limited|ltd|plc|llc|inc|corp(?:oration)?|co|company|private|pvt|the)\b", re.I)


def norm_company(name: str) -> str:
    """Same company across registries: case, punctuation and legal suffixes ignored."""
    return " ".join(_SUFFIX.sub(" ", re.sub(r"[^\w ]", " ", (name or "").lower())).split())


def build_network(corp: Dict[str, Any]) -> Dict[str, Any]:
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []
    subj = corp.get("subject") or "subject"

    def node(nid, typ, label, **kw):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "type": typ, "label": label, **kw}
        return nid

    root = node("subject", "PERSON", subj, role="SUBJECT")
    s = corp.get("sources", {})
    icij = s.get("icij") or {}
    for o in icij.get("officers", []):
        oid = node(f"icij:{o['node_id']}", "PERSON", o["name"], identity=o["identity"], url=o["url"], source=o["leak"])
        edges.append({"from": root, "to": oid, "rel": "same_name_as", "basis": "NAME_ONLY_LEAD", "source": o["url"]})
    for e in icij.get("entities", []):
        eid = node(f"icij:{e['node_id']}", "COMPANY", e["name"], jurisdiction=e["jurisdiction"], url=e["url"],
                   signals=e["signals"], source=e["leak"], incorporated=e["incorporated"], status=e["status"])
        for r in e["roles"]:
            o = next((x for x in icij.get("officers", []) if x["name"] == r["officer"]), None)
            if o:
                edges.append({"from": f"icij:{o['node_id']}", "to": eid, "rel": r["role"], "basis": "RECORD",
                              "source": e["url"], "period": f"{r['from'] or '?'}..{r['to'] or ''}"})
    for c in icij.get("co_officers", []):
        cid = node(f"icij:{c['node_id']}", "PERSON", c["name"], url=c["url"], appointments=c["total_appointments"],
                   possible_nominee=c["possible_nominee"])
        for en in c["shared_entities"]:
            tgt = next((k for k, v in nodes.items() if v["label"] == en and v["type"] == "COMPANY"), None)
            if tgt:
                edges.append({"from": cid, "to": tgt, "rel": ", ".join(c["roles"]), "basis": "RECORD", "source": c["url"]})
    for i in icij.get("intermediaries", []):
        iid = node(f"icij:{i['node_id']}", "INTERMEDIARY", i["name"], url=i["url"])
        for en in i["entities"]:
            tgt = next((k for k, v in nodes.items() if v["label"] == en and v["type"] == "COMPANY"), None)
            if tgt:
                edges.append({"from": iid, "to": tgt, "rel": "intermediary of", "basis": "RECORD", "source": i["url"]})
    for a in icij.get("addresses", []):
        aid = node(f"icij:{a['node_id']}", "ADDRESS", a["address"], url=a["url"],
                   companies_registered_here=a["companies_registered_here"])
        for en in a["entities"]:
            tgt = next((k for k, v in nodes.items() if v["label"] == en and v["type"] == "COMPANY"), None)
            if tgt:
                edges.append({"from": tgt, "to": aid, "rel": "registered address", "basis": "RECORD", "source": a["url"]})

    uk = s.get("uk") or {}
    for o in uk.get("officers", []):
        oid = node(f"ch:{o['url']}", "PERSON", o["name"], identity=o["identity"], url=o["url"], born=o["born"],
                   appointments=o["appointments"])
        edges.append({"from": root, "to": oid,
                      "rel": "same_person_probable" if o["identity"] == "DOB_MONTH_YEAR_MATCH" else "same_name_as",
                      "basis": o["identity"], "source": o["url"]})
    for c in uk.get("companies", []):
        cid = node(f"ch:{c['number'] or c['company']}", "COMPANY", c["company"], jurisdiction="United Kingdom",
                   url=c["url"], status=c["status"], signals=c["signals"])
        oo = next((x for x in uk.get("officers", []) if x["name"] == c["officer"]), None)
        if oo:
            edges.append({"from": f"ch:{oo['url']}", "to": cid, "rel": c["role"] or "officer", "basis": "RECORD",
                          "source": c["url"], "period": f"{c['appointed'] or '?'}..{c['resigned'] or ''}"})
    for p in uk.get("co_officers", []):
        pid = node(f"ch:{p['url']}", "PERSON", p["name"], url=p["url"])
        tgt = next((k for k, v in nodes.items() if v["label"] == p["company"] and v["type"] == "COMPANY"), None)
        if tgt:
            edges.append({"from": pid, "to": tgt, "rel": p["role"] or "officer", "basis": "RECORD", "source": p["url"],
                          "period": f"..{p['resigned']}" if p["resigned"] else ""})

    def company_by_name(name):
        k = norm_company(name)
        return next((nid for nid, v in nodes.items() if v["type"] == "COMPANY" and norm_company(v["label"]) == k), None)

    for g in (s.get("gleif") or {}).get("entities", []):
        gid = company_by_name(g["name"])            # a UK company already in the graph keeps one node
        if gid:
            nodes[gid].setdefault("lei", g["lei"])
            nodes[gid]["signals"] = list(dict.fromkeys((nodes[gid].get("signals") or []) + g.get("signals", [])))
        else:
            gid = node(f"lei:{g['lei']}", "COMPANY", g["name"], jurisdiction=g["jurisdiction"], url=g["url"],
                       signals=g.get("signals", []), lei=g["lei"])
        for p in g.get("parents", []):
            pid = company_by_name(p["name"]) or node(f"lei:{p['lei']}", "COMPANY", p["name"], jurisdiction=p["jurisdiction"],
                                                     url=p["url"], lei=p["lei"], parent_of=g["name"], parent_kind=p["kind"])
            edges.append({"from": pid, "to": gid, "rel": p["kind"].replace("-", " "), "basis": "RECORD", "source": p["url"]})

    companies = [n for n in nodes.values() if n["type"] == "COMPANY"]
    flagged = [c for c in companies if c.get("signals")]
    people = [n for n in nodes.values() if n["type"] == "PERSON" and n["id"] != "subject"]
    return {"nodes": list(nodes.values()), "edges": edges,
            "stats": {"people": len(people), "companies": len(companies), "flagged_companies": len(flagged),
                      "intermediaries": sum(1 for n in nodes.values() if n["type"] == "INTERMEDIARY"),
                      "addresses": sum(1 for n in nodes.values() if n["type"] == "ADDRESS"),
                      "edges": len(edges),
                      "possible_nominees": sum(1 for n in people if n.get("possible_nominee"))},
            "status": "INDICATOR", "caveat": PROTECT}


def to_kge(net: Dict[str, Any]) -> Dict[str, Any]:
    """knowledge_graph_engine input: graph{nodes:[{id,type,content,source,weight,metadata}], edges}."""
    w = {"RECORD": 0.8, "DOB_MONTH_YEAR_MATCH": 0.7, "NAME_ONLY_LEAD": 0.3}
    return {"nodes": [{"id": n["id"], "type": n["type"].lower(), "content": n["label"], "source": n.get("url", ""),
                       "weight": 0.5, "metadata": {k: v for k, v in n.items() if k not in ("id", "type", "label")}}
                      for n in net["nodes"]],
            "edges": [{"source": e["from"], "target": e["to"], "type": e["rel"], "weight": w.get(e["basis"], 0.5),
                       "metadata": {"basis": e["basis"], "url": e["source"], "period": e.get("period", "")}}
                      for e in net["edges"]]}


def section_texts(corp: Dict[str, Any], net: Dict[str, Any]) -> Dict[str, str]:
    s = corp.get("sources", {})
    icij, uk, gl = s.get("icij") or {}, s.get("uk") or {}, s.get("gleif") or {}
    comp, ppl, nxt = [], [], []
    for c in uk.get("companies", []):
        comp.append(f"UK: {c['company']} ({c['number']}), {c['role']} {c['appointed'] or ''}"
                    f"{' to ' + c['resigned'] if c['resigned'] else ''}, status {c['status']}, officer match "
                    f"{c['identity']} [{c['url']}]")
    for e in icij.get("entities", [])[:15]:
        comp.append(f"Offshore ({e['leak']}): {e['name']}, {e['jurisdiction']}, incorporated {e['incorporated'] or '?'}"
                    f"{', ' + ', '.join(e['signals']) if e['signals'] else ''}; officer name-only lead [{e['url']}]")
    for g in gl.get("entities", []):
        par = "; ".join(f"{p['kind']} {p['name']} ({p['jurisdiction']})" for p in g.get("parents", [])) or "no parent reported"
        comp.append(f"LEI {g['lei']} {g['name']} ({g['jurisdiction']}): {par} [{g['url']}]")
    for p in uk.get("co_officers", [])[:15]:
        ppl.append(f"{p['name']}: {p['role']} at {p['company']}{' (resigned ' + p['resigned'] + ')' if p['resigned'] else ''} [{p['url']}]")
    for c in icij.get("co_officers", [])[:12]:
        ppl.append(f"{c['name']}: {', '.join(c['roles'])} in {', '.join(c['shared_entities'][:3])}; "
                   f"{c['total_appointments']} appointments in the leaks"
                   f"{' (possible nominee)' if c['possible_nominee'] else ''} [{c['url']}]")
    for i in icij.get("intermediaries", [])[:8]:
        ppl.append(f"Intermediary {i['name']} for {', '.join(i['entities'][:3])} [{i['url']}]")
    for o in uk.get("rejected", []):
        nxt.append(f"UK officer {o['name']} born {o['born']} rejected as namesake (DOB differs)")
    if any(o["identity"] == "NAME_ONLY_LEAD" for o in icij.get("officers", [])):
        nxt.append("Offshore Leaks officer records match on name only: confirm identity with address, passport "
                   "country or co-officers before reporting")
    for e in [e for e in icij.get("entities", []) if e["signals"]][:5]:
        nxt.append(f"Ask who beneficially owns {e['name']} ({e['jurisdiction']}) and why it was set up via "
                   f"{e['service_provider'] or 'its agent'}")
    st = net["stats"]
    head = (f"{st['companies']} companies, {st['people']} linked people, {st['intermediaries']} intermediaries; "
            f"{st['flagged_companies']} companies carry shell indicators, {st['possible_nominees']} possible nominee "
            f"officers. {PROTECT}")
    return {"Companies & Ownership": head + " " + "; ".join(comp) if comp else "",
            "People & Relationship Network": "; ".join(ppl),
            "_next": nxt,
            "_notes": [f"{k}: {v.get('status')} {'; '.join(v.get('notes', []))}".strip() for k, v in s.items()]}


def markdown(corp: Dict[str, Any], net: Dict[str, Any]) -> str:
    s = corp.get("sources", {})
    icij, uk, gl = s.get("icij") or {}, s.get("uk") or {}, s.get("gleif") or {}
    st = net["stats"]
    out = [f"**Companies & people network**: {st['companies']} companies, {st['people']} people, "
           f"{st['intermediaries']} intermediaries, {st['flagged_companies']} companies with shell indicators. "
           f"_{PROTECT} Offshore Leaks officers match on name only._", ""]
    rows = []
    for c in uk.get("companies", []):
        rows.append(f"| [{c['company']}]({c['url']}) | UK | {c['role']} | {c['appointed'] or ''} | {c['status']} | "
                    f"{c['identity'].replace('_', ' ').lower()} | {', '.join(c['signals'])} |")
    for e in icij.get("entities", [])[:15]:
        rows.append(f"| [{e['name']}]({e['url']}) | {e['jurisdiction'] or ''} | "
                    f"{', '.join(sorted({r['role'] for r in e['roles']}))} | {e['incorporated'] or ''} | "
                    f"{e['status'] or ''} | name only ({e['leak']}) | {'; '.join(e['signals'])} |")
    listed = {norm_company(c["company"]) for c in uk.get("companies", [])} | \
             {norm_company(e["name"]) for e in icij.get("entities", [])[:15]}
    for g in gl.get("entities", []):
        par = "; ".join(f"{p['kind']}: {p['name']}" for p in g.get("parents", []))
        if norm_company(g["name"]) not in listed:     # same company as a UK row: one row, not two
            listed.add(norm_company(g["name"]))
            rows.append(f"| [{g['name']}]({g['url']}) | {g['jurisdiction'] or ''} | LEI | | {g['status'] or ''} | {par} | "
                        f"{'; '.join(g.get('signals', []))} |")
        for p in g.get("parents", []):                # parents are companies in the count, so they get a row too
            if norm_company(p["name"]) not in listed:
                listed.add(norm_company(p["name"]))
                rows.append(f"| [{p['name']}]({p['url']}) | {p.get('jurisdiction') or ''} | "
                            f"{p['kind'].replace('-', ' ')} of {g['name']} | | | LEI record | |")
    hidden = max(0, st["companies"] - len(rows))
    if rows:
        out += ["| Company | Jurisdiction | Role | Since | Status | Match | Shell indicators |",
                "|---|---|---|---|---|---|---|"] + [r.replace("\n", " ") for r in rows]
    ppl = [f"| [{p['name']}]({p['url']}) | {p['role']}{' (resigned ' + p['resigned'] + ')' if p.get('resigned') else ''} | "
           f"{p['company']} | UK Companies House | {'born ' + p['born'] if p.get('born') else ''} |"
           for p in uk.get("co_officers", [])[:15]]
    ppl += [f"| [{c['name']}]({c['url']}) | {', '.join(c['roles'])} | {', '.join(c['shared_entities'][:2])} | "
            f"Offshore Leaks | {c['total_appointments']} appointments{' ⚠ possible nominee' if c['possible_nominee'] else ''} |"
            for c in icij.get("co_officers", [])[:10]]
    ppl += [f"| [{i['name']}]({i['url']}) | intermediary | {', '.join(i['entities'][:2])} | Offshore Leaks | |"
            for i in icij.get("intermediaries", [])[:6]]
    if hidden:
        out.append(f"\n<sub>{hidden} more compan{'y' if hidden == 1 else 'ies'} in the network graph not shown in this table.</sub>")
    if ppl:
        out += ["", "| Linked person | Role | Company | Source | Detail |", "|---|---|---|---|---|"] + ppl
    rej = uk.get("rejected", [])
    if rej:
        out.append(f"\n<sub>{len(rej)} UK officer record(s) with the same name rejected: date of birth differs.</sub>")
    if not rows and not ppl:
        out.append("No company records found for this name in the registries searched (UK Companies House, "
                   "ICIJ Offshore Leaks, GLEIF). Not found here does not mean none exist.")
    return "\n".join(out)
