"""p28: Narrative-vs-document consistency check with the user's own NLI v3 model
(TrustCircle NLI v3, mDeBERTa-v3 backbone, step 8000, FEVER eval acc 0.9626).
Replaces the raw Qwen 0.5B deception cue. EXPERIMENTAL: not validated on case documents.
Output labels: SUPPORTED / CONTRADICTED / NO_EVIDENCE (per claim), with the document sentence."""
import re, threading, logging
from pathlib import Path
log = logging.getLogger("InvestigatorAI")

NLI_DIR = Path("/home/trustcircleai/TRUSTCIRCLE_TRAINING_PACKAGE/artifacts/trustcircle_nli_v3")
LABELS = ("entailment", "neutral", "contradiction")
THRESH = 0.80
MAX_CLAIMS = 12
TOP_K = 3
MIN_CLAIM_TOKENS = 5  # p30
_WORD = re.compile(r"[\w\u0900-\u097F]{3,}", re.UNICODE)
_STOP = {"the","and","was","were","with","from","that","this","for","has","have","had","his","her",
         "their","they","are","not","but","been","into","which","who","its","also","per","said"}

def _sentences(text, max_len=320):
    parts = re.split(r"(?<!\bNo\.)(?<!\bMr\.)(?<!\bDr\.)(?<!\bLtd\.)(?<!\bvs\.)(?<=[.!?\u0964])\s+|\n+", text or "")
    out = []
    for p in parts:
        p = re.sub(r"\s+", " ", p).strip()
        if len(p) < 12:
            continue
        while len(p) > max_len:
            cut = p.rfind(" ", 0, max_len)
            cut = cut if cut > 40 else max_len
            out.append(p[:cut]); p = p[cut:].strip()
        if p:
            out.append(p)
    return out

def _toks(s):
    return {w.lower() for w in _WORD.findall(s)} - _STOP

class NLIEngine:
    def __init__(self, path=NLI_DIR):
        self.ready = False
        self._lock = threading.Lock()
        try:
            import torch
            from safetensors.torch import load_file
            from transformers import AutoTokenizer, AutoConfig, DebertaV2Model
            sd = load_file(str(path / "model.safetensors"))
            cfg = AutoConfig.from_pretrained(str(path), local_files_only=True)
            self.tok = AutoTokenizer.from_pretrained(str(path), local_files_only=True)
            m = DebertaV2Model(cfg)
            res = m.load_state_dict({k[9:]: v for k, v in sd.items() if k.startswith("backbone.")}, strict=True)
            self.W = sd["classifier.weight"]; self.b = sd["classifier.bias"]
            assert tuple(self.W.shape) == (3, cfg.hidden_size)
            m.eval(); self.model = m; self.torch = torch
            self.ready = True
            log.info(f"NLI v3 ✓ (TrustCircle NLI, CLS head, {path})")
        except Exception as e:
            log.warning(f"NLI v3 load failed: {e}")

    def _probs(self, premise, hypothesis):
        t = self.torch
        enc = self.tok(premise, hypothesis, return_tensors="pt", truncation=True, max_length=256)
        with t.no_grad():
            h = self.model(**enc).last_hidden_state[:, 0]
            p = t.softmax(h @ self.W.T + self.b, -1)[0].tolist()
        return dict(zip(LABELS, p))

    def check(self, narrative, document_text):
        base = {"engine": "TrustCircle NLI v3 (step 8000)", "status": "NOT_ASSESSED", "claims": [],
                "note": "EXPERIMENTAL - model trained on FEVER (Wikipedia claims); not validated on case documents. "
                        "Leads for human review, not findings."}
        if not self.ready:
            base["reason"] = "NLI model not loaded"; return base
        # p30: skip short fragments/labels (e.g. "QA TEST, public reporting only.")
        claims = [c for c in _sentences(narrative) if len(_toks(c)) >= MIN_CLAIM_TOKENS][:MAX_CLAIMS]
        evid = _sentences(document_text)
        if not claims:
            base["reason"] = "no narrative text"; return base
        if not evid:
            base["reason"] = "no document text submitted (OCR empty) - nothing to compare against"; return base
        ev_t = [(_toks(e), e) for e in evid]
        out = []
        with self._lock:
            self.torch.set_num_threads(4)
            for c in claims:
                ct = _toks(c)
                ranked = sorted(((len(ct & et), e) for et, e in ev_t), key=lambda x: -x[0])
                need = max(2, int(0.3 * len(ct) + 0.5))
                cands = [e for ov, e in ranked[:TOP_K] if ov >= need]
                best = {"claim": c, "verdict": "NO_EVIDENCE", "document_sentence": "", "probs": {}}
                scored = [(self._probs(e, c), e) for e in cands]
                ent = [x for x in scored if x[0]["entailment"] >= THRESH]
                if ent:
                    p, e = max(ent, key=lambda x: x[0]["entailment"])
                    best.update(verdict="SUPPORTED", document_sentence=e, probs={k: round(v, 3) for k, v in p.items()})
                elif scored and scored[0][0]["contradiction"] >= THRESH:
                    # contradiction only from the most on-topic document sentence:
                    # off-topic sentences about the same person give false contradictions
                    p, e = scored[0]
                    best.update(verdict="CONTRADICTED", document_sentence=e, probs={k: round(v, 3) for k, v in p.items()})
                out.append(best)
        base.update(status="ASSESSED", claims=out,
                    counts={v: sum(1 for x in out if x["verdict"] == v) for v in ("SUPPORTED", "CONTRADICTED", "NO_EVIDENCE")})
        return base
