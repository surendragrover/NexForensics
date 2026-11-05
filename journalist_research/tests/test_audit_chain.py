"""Offline test of the audit hash chain logic (in-memory fake DB; the real table is never touched)."""
from journalist_research.jobs import audit_chain as A

R = []
def t(name, cond): R.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), name)

class Cur:
    def __init__(self, rows): self.rows, self.res = rows, None
    def execute(self, q, args=None):
        q = " ".join(q.split())
        if q.startswith("SELECT entry_hash"):
            self.res = [(self.rows[-1]["entry_hash"],)] if self.rows else []
        elif q.startswith("INSERT INTO doa_audit_chain"):
            ca, et, ref, ps, det, ph, eh = args
            self.rows.append({"id": len(self.rows) + 1, "created_at": ca, "event_type": et, "ref_id": ref,
                              "payload_sha256": ps, "prev_hash": ph, "entry_hash": eh})
        elif q.startswith("SELECT id,created_at"):
            self.res = [(r["id"], r["created_at"], r["event_type"], r["ref_id"], r["payload_sha256"], r["prev_hash"],
                         r["entry_hash"]) for r in self.rows]
        else:
            self.res = [(1,)]
    def fetchone(self): return self.res[0] if self.res else None
    def fetchall(self): return self.res or []
class Conn:
    def __init__(self): self.rows = []
    def cursor(self): return Cur(self.rows)
    def commit(self): pass
    def close(self): pass

c = Conn()
e1 = A.append("DOA_DOSSIER", "DOA-1", "a" * 64, conn=c)
e2 = A.append("SOURCE_SNAPSHOT", "uk:1", "b" * 64, conn=c)
t("first entry links to genesis", e1["prev_hash"] == A.GENESIS)
t("second entry links to first", e2["prev_hash"] == e1["entry_hash"])
t("verify ok on untouched chain", A.verify(conn=c)["ok"] and A.verify(conn=c)["entries"] == 2)
c.rows[0]["payload_sha256"] = "c" * 64
v = A.verify(conn=c)
t("edited payload detected", not v["ok"] and v["problems"][0]["id"] == 1)
c.rows[0]["payload_sha256"] = "a" * 64
del c.rows[0]
t("deleted entry detected", not A.verify(conn=c)["ok"])
t("hash is deterministic", A.entry_hash("0", "x", "y", "z", "t") == A.entry_hash("0", "x", "y", "z", "t"))

ok = sum(1 for _, v in R if v)
print(f"\nAUDIT CHAIN: {ok}/{len(R)} PASS")
raise SystemExit(0 if ok == len(R) else 1)
