"""
engines/ml_engines.py — the model-inference engines.

  NEREngine              HuggingFace token-classification (entity extraction)
  VoiceEngine            x-vector TDNN speaker-ID model (.pt)
  FaceEngine             ArcFace-style resnet18 embedding model
  OCREngine              TrOCR (HuggingFace) for photos/ID documents
  XGBPatternEngine       XGBoost risk-pattern model (heuristic fallback)
  HFImageClassifierEngine  generic HF image-classification wrapper
                           (used for both the CCTV classifier and the
                           deepfake detector)
  QwenGGUFEngine         local LLM (llama-cpp-python) — statement insight,
                         hypothesis generation, deception-cue read, story draft

Each engine is defensive: if its checkpoint/dependency is missing, it
sets self.ready = False and the rest of the pipeline runs without it.

Extracted from gradio_app.py (was ~900 lines inline in the middle of
the file, mixed in with app/UI code).
"""

import os
import json
import re as _re
from datetime import datetime

import numpy as np

from config import log, MODELS_DIR


class NEREngine:
    def __init__(self, path):
        self.ready = False
        try:
            from transformers import pipeline, AutoTokenizer, AutoModelForTokenClassification
            tok        = AutoTokenizer.from_pretrained(str(path))
            mdl        = AutoModelForTokenClassification.from_pretrained(str(path))
            self.pipe  = pipeline("ner", model=mdl, tokenizer=tok,
                                  aggregation_strategy="simple", device=-1)
            self.ready = True
            log.info("NER ✓")
        except Exception as e:
            log.warning(f"NER not loaded: {e}")
        # Hybrid rule layer (models/hybrid_rules/hybrid_rules_v*.json, newest
        # version wins). Runs after the fine-tuned model: keeps its entities,
        # validates pattern labels, adds rule/lexicon hits, maps PER->PERSON,
        # de-duplicates. If the rules cannot load, NER behaves as before.
        self.rules = None
        self.last_provenance = {}
        try:
            from engines.hybrid_rules import HybridRules
            self.rules = HybridRules(MODELS_DIR / "hybrid_rules")
            log.info(f"NER hybrid rules v{self.rules.version} ✓")
        except Exception as e:
            log.warning(f"NER hybrid rules not loaded: {e}")

    # Common function words / punctuation the aggregation pipeline
    # occasionally mis-tags as an entity on longer or run-on text —
    # these are never real entity values, so they're filtered out
    # before anything downstream (counts, matching, reports) sees them.
    _JUNK_TOKENS = {
        "a", "an", "the", "and", "or", "but", "of", "in", "on", "at",
        "to", "for", "with", "from", "by", "as", "is", "was", "were",
        "be", "been", "being", "this", "that", "these", "those",
        "it", "its", "he", "she", "they", "his", "her", "their",
        ",", ".", ";", ":", "-", "—", "'", '"', "(", ")", "and,",
    }

    # BUG FIX (reviewer feedback — same failure pattern seen twice now,
    # Subhash Chandra case and NHAI case): a bare generic financial/
    # institutional noun ("Bank", "Account", "accounts", "Court") tagged
    # as entity_group ORG gets treated downstream as "a named organization
    # is involved in this case" — feeding false network associations and
    # inflated evidence-coverage. A real organization NAME is a proper
    # noun ("HDFC Bank", "Essel Group Ltd") — a lone common noun that
    # merely describes a TYPE of institution is not. Filter these out of
    # the ORG bucket specifically (they're still fine as ordinary text,
    # just not as "a named organization").
    _GENERIC_ORG_TERMS = {
        "bank", "banks", "banking", "account", "accounts", "court",
        "courts", "police", "government", "authority", "department",
        "ministry", "office", "company", "companies", "firm", "agency",
        "group", "committee", "board", "branch", "unit", "division",
    }

    def _looks_like_real_entity(self, word: str) -> bool:
        w = (word or "").strip()
        if len(w) < 2:
            return False
        w_clean = w.strip(",.;:-—'\"() ")
        if not w_clean or w_clean.lower() in self._JUNK_TOKENS:
            return False
        # must contain at least one letter or digit (rules out pure punctuation)
        if not any(ch.isalnum() for ch in w_clean):
            return False
        # Sub-word tokenizer fragments (e.g. "theft" -> "the"+"ft", "Crore"
        # -> "Cro"+"re") are the single biggest source of junk in this
        # pipeline's NER output — a short, lowercase, non-acronym fragment
        # like "ft"/"Cro"/"over"/"res" is essentially never a real, useful
        # entity on its own. Per the standing rule here: if it's not a
        # complete-looking entity, don't show it rather than showing a
        # fragment.
        if len(w_clean) < 4 and not (w_clean.isupper() or any(ch.isdigit() for ch in w_clean)):
            return False
        return True

    # Same failure mode as ORG above, but for MONEY: the model's own label
    # prediction for entity_group=="MONEY" is occasionally just wrong (a
    # violence/action word like "attack" tagged MONEY with moderate
    # confidence) — there was no content check for MONEY at all before
    # this, so a bad model prediction went straight through to the report
    # and inflated the financial-anomaly score downstream. Require the
    # matched text to actually look financial (currency symbol, a number,
    # or a common money-related word) before accepting it as MONEY.
    _MONEY_LOOKS_FINANCIAL_RE = _re.compile(
        r'[₹$€£]|\d|\b(rupee|rupees|dollar|dollars|lakh|crore|thousand|million|'
        r'billion|cash|laundering|transfer|payment|wallet|account|deposit|'
        r'withdraw|bank|loan|debt|fund|crypto|bitcoin|invoice|salary|paid|price|cost)\b',
        _re.IGNORECASE,
    )

    def extract(self, text):
        if not self.ready or not text.strip():
            return {}
        try:
            out = self.pipe(text)
            ents = {}
            for e in out:
                word = e["word"].strip()
                if not self._looks_like_real_entity(word):
                    continue
                # A short, common English word (e.g. "over", "under") tagged
                # as an entity is almost always a low-confidence model
                # misfire rather than a real finding — require a higher
                # confidence bar for short words specifically, since that's
                # exactly the failure mode reported (e.g. "over" as ORG).
                score = e.get("score", 1.0)
                if len(word.strip(",.;:-—'\"() ")) <= 5 and score < 0.85:
                    continue
                w_clean = word.strip(",.;:-—'\"() ").strip()
                # A single generic institutional noun tagged as ORG (e.g.
                # "Bank", "accounts") is not a named organization — a real
                # org name is a proper noun / multi-word name. Only filter
                # single-word generic nouns; "Essel Group" (2 words) is
                # unaffected because it isn't equal to just "group".
                if e["entity_group"] == "ORG" and w_clean.lower() in self._GENERIC_ORG_TERMS:
                    continue
                if e["entity_group"] == "MONEY" and not self._MONEY_LOOKS_FINANCIAL_RE.search(w_clean):
                    continue
                ents.setdefault(e["entity_group"], []).append(w_clean)
            if self.rules is not None:
                try:
                    ents, self.last_provenance = self.rules.apply(text, ents)
                except Exception as re_err:
                    log.error(f"NER hybrid rules error: {re_err}")
            return ents
        except Exception as e:
            log.error(f"NER error: {e}"); return {}

    def score(self, ents):
        if getattr(self, "rules", None) is not None and self.rules.risk:
            return self.rules.score(ents)
        s = 40.0
        s += len(ents.get("CRIME",  [])) * 10
        s += len(ents.get("WEAPON", [])) * 12
        s += len(ents.get("PERSON", [])) * 3
        s += len(ents.get("THREAT", [])) * 8
        return min(s, 95.0)


class VoiceEngine:
    """
    Loads the voice model — confirmed architecture from checkpoint inspection
    (speaker_best.pt = {'enc': x-vector encoder state_dict, 'cls': speaker
    classifier state_dict, 'spk2id': {...}, 'num_spk': N, 'val_acc': ...}).

    This is a classic x-vector (TDNN) SPEAKER-ID / voiceprint model, not a
    stress classifier:
      enc:  5x TDNN(Conv1d+BN+ReLU) frame layers (80-dim input, i.e. 80-mel
            log-filterbank frames) -> stats pooling (mean+std over time)
            -> fc(3000->512) -> bn -> proj(512->192) -> bn2  => 192-d voiceprint
      cls:  Linear(192 -> num_spk)  — closed-set speaker classifier

    Since there's no literal "stress" output, we repurpose the classifier's
    top-1 confidence as an identity-consistency signal: low confidence /
    no strong match => flagged as higher-risk ("voice_mismatch_score").
    Raw pitch/energy features (librosa) are still reported alongside for
    the report, as before.
    """
    @staticmethod
    def _build_arch(torch, num_spk):
        import torch.nn as nn

        class TDNNLayer(nn.Module):
            def __init__(self, in_dim, out_dim, kernel_size, dilation):
                super().__init__()
                self.conv = nn.Conv1d(in_dim, out_dim, kernel_size, dilation=dilation)
                self.bn   = nn.BatchNorm1d(out_dim)
                self.relu = nn.ReLU()
            def forward(self, x):
                return self.relu(self.bn(self.conv(x)))

        class XVectorEncoder(nn.Module):
            def __init__(self, in_dim=80):
                super().__init__()
                self.tdnn = nn.ModuleList([
                    TDNNLayer(in_dim, 512, kernel_size=5, dilation=1),
                    TDNNLayer(512,    512, kernel_size=3, dilation=2),
                    TDNNLayer(512,    512, kernel_size=3, dilation=3),
                    TDNNLayer(512,    512, kernel_size=1, dilation=1),
                    TDNNLayer(512,   1500, kernel_size=1, dilation=1),
                ])
                self.fc   = nn.Linear(3000, 512)
                self.bn   = nn.BatchNorm1d(512)
                self.proj = nn.Linear(512, 192)
                self.bn2  = nn.BatchNorm1d(192)
                self.relu = nn.ReLU()

            def forward(self, x):
                # x: (batch, 80, time)
                for layer in self.tdnn:
                    x = layer(x)
                mean = x.mean(dim=2)
                std  = x.std(dim=2)
                stats = torch.cat([mean, std], dim=1)          # (batch, 3000)
                x = self.relu(self.bn(self.fc(stats)))          # (batch, 512)
                x = self.bn2(self.proj(x))                      # (batch, 192) — voiceprint
                return x

        class SpeakerModel(nn.Module):
            def __init__(self, num_spk):
                super().__init__()
                self.enc = XVectorEncoder()
                self.cls = nn.Linear(192, num_spk)
            def forward(self, x):
                emb = self.enc(x)
                logits = self.cls(emb)
                return emb, logits

        return SpeakerModel(num_spk)

    def __init__(self, path):
        self.ready = False
        self.spk2id = {}
        try:
            import torch
            candidates = (list(path.glob("*.pt")) + list(path.glob("*.pth")) +
                          list(path.glob("*.safetensors")))
            if not candidates: raise FileNotFoundError("No voice checkpoint found in voice/")
            ckpt_path = candidates[0]

            if ckpt_path.suffix == ".safetensors":
                raise RuntimeError(
                    f"'{ckpt_path.name}' is a bare safetensors state_dict — "
                    f"the voice checkpoint here is expected as a .pt bundle "
                    f"with 'enc'/'cls' sub-dicts."
                )

            obj = torch.load(ckpt_path, map_location="cpu")
            if not isinstance(obj, dict) or "enc" not in obj or "cls" not in obj:
                raise RuntimeError(
                    f"'{ckpt_path.name}' doesn't have the expected "
                    f"{{'enc':..., 'cls':...}} structure."
                )

            self.spk2id = obj.get("spk2id", {})
            self.id2spk = {v: k for k, v in self.spk2id.items()}
            num_spk = obj.get("num_spk", len(self.spk2id) or 251)

            model = self._build_arch(torch, num_spk)
            missing_e, unexpected_e = model.enc.load_state_dict(obj["enc"], strict=False)
            missing_c, unexpected_c = model.cls.load_state_dict(obj["cls"], strict=False)
            if missing_e or unexpected_e or missing_c or unexpected_c:
                log.warning(f"Voice load_state_dict mismatch — enc missing:{len(missing_e)} "
                            f"unexpected:{len(unexpected_e)}, cls missing:{len(missing_c)} "
                            f"unexpected:{len(unexpected_c)}")

            self.model = model
            self.model.eval()
            self.torch = torch
            self.ready = True
            log.info(f"Voice ✓ (x-vector TDNN, {num_spk} speakers, "
                      f"val_acc={obj.get('val_acc', 'n/a')})")
        except Exception as e:
            log.warning(f"Voice not loaded: {e}")

    def analyse(self, audio_path):
        if not self.ready: return {}
        try:
            import librosa
            y, sr = librosa.load(audio_path, sr=16000, mono=True)

            # 80-dim log-mel filterbank frames, matching the encoder's input dim
            mel = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=80, n_fft=400, hop_length=160)
            logmel = librosa.power_to_db(mel, ref=np.max)
            L = 300
            logmel = np.pad(logmel, ((0, 0), (0, max(0, L - logmel.shape[1]))))[:, :L]
            tensor = self.torch.tensor(logmel[None].astype("float32"))  # (1, 80, 300)

            with self.torch.no_grad():
                emb, logits = self.model(tensor)
                probs = self.torch.softmax(logits, dim=-1)[0]
                top_prob, top_idx = probs.max(dim=0)

            top_prob = float(top_prob.item())
            top_idx  = int(top_idx.item())
            top_speaker = self.id2spk.get(top_idx, f"spk_{top_idx}")

            # Repurposed "mismatch/risk" score: low classifier confidence => higher score
            mismatch_score = round((1.0 - top_prob) * 100, 1)

            pitches, mags = librosa.piptrack(y=y, sr=sr)
            pv = pitches[mags > np.median(mags)]

            return {
                "stress_score":     mismatch_score,   # kept for pipeline compatibility
                "voice_match_conf": round(top_prob * 100, 1),
                "top_speaker":      top_speaker,
                "embedding_dim":    int(emb.shape[-1]),
                "pitch_deviation":  round(float(np.std(pv)) if len(pv) else 0, 2),
                "energy":           round(float(np.mean(librosa.feature.rms(y=y))) * 1000, 2),
                "label": ("Low ID Confidence" if mismatch_score > 65 else
                          "Moderate ID Confidence" if mismatch_score > 40 else
                          "High ID Confidence"),
            }
        except Exception as e:
            log.error(f"Voice error: {e}"); return {}


class FaceEngine:
    """
    Loads the ArcFace face-recognition backbone.

    Confirmed architecture (from checkpoint key/shape inspection of
    face_model_v7_masked.safetensors):
      - torchvision resnet18 backbone (conv1..layer4, i.e. children()[:8]),
        wrapped as `self.features`
      - global average pool -> flatten -> `self.embedding` = Linear(512, 512)
    """
    @staticmethod
    def _build_arch(torch, torchvision):
        import torch.nn as nn
        import torch.nn.functional as F

        class ArcFaceNet(nn.Module):
            def __init__(self):
                super().__init__()
                base = torchvision.models.resnet18(weights=None)
                self.features  = nn.Sequential(*list(base.children())[:8])  # conv1..layer4
                self.embedding = nn.Linear(512, 512)

            def forward(self, x):
                x = self.features(x)
                x = F.adaptive_avg_pool2d(x, 1).flatten(1)
                x = self.embedding(x)
                return x

        return ArcFaceNet()

    def __init__(self, path):
        self.ready = False
        try:
            import torch, torchvision
            candidates = (list(path.glob("*.pt")) + list(path.glob("*.pth")) +
                          list(path.glob("*.safetensors")))
            if not candidates: raise FileNotFoundError("No face checkpoint found in face/")
            ckpt_path = candidates[0]

            if ckpt_path.suffix == ".safetensors":
                from safetensors.torch import load_file
                state = load_file(str(ckpt_path))
                model = self._build_arch(torch, torchvision)
                missing, unexpected = model.load_state_dict(state, strict=False)
                if missing or unexpected:
                    log.warning(f"ArcFace load_state_dict — missing:{len(missing)} "
                                f"unexpected:{len(unexpected)} "
                                f"(missing sample: {missing[:5]}, unexpected sample: {unexpected[:5]})")
                self.model = model
                log.info(f"ArcFace ✓ (resnet18 backbone, safetensors, "
                          f"{len(state)-len(unexpected)}/{len(state)} tensors matched)")
            else:
                loaded = torch.load(ckpt_path, map_location="cpu")
                if not isinstance(loaded, torch.nn.Module):
                    raise RuntimeError(
                        f"'{ckpt_path.name}' is a state_dict/checkpoint dict, not a "
                        f"pickled nn.Module — needs the model architecture class."
                    )
                self.model = loaded
                log.info("ArcFace ✓ (pickled .pt)")

            self.model.eval()
            self.torch = torch; self.tv = torchvision
            self.ready = True
        except Exception as e:
            log.warning(f"ArcFace not loaded: {e}")

    def _crop(self, img):
        # 2026-11-06: OpenCV 5 on this server has no CascadeClassifier, so the Haar path below always failed
        # and the whole image was embedded. Use the YuNet detector first.
        try:
            from journalist_research.biometrics.face_detect import detect_faces
            _f = detect_faces(img)
            if _f:
                return _f[0][1]
        except Exception:
            pass
        try:
            import cv2
            arr   = np.array(img.convert("RGB"))
            gray  = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
            cas   = cv2.CascadeClassifier(cv2.data.haarcascades+"haarcascade_frontalface_default.xml")
            faces = cas.detectMultiScale(gray, 1.1, 5, minSize=(60,60))
            if len(faces):
                x,y,w,h = faces[0]
                from PIL import Image
                return Image.fromarray(arr[y:y+h,x:x+w])
        except: pass
        return img

    def analyse(self, pil_img):
        if not self.ready or pil_img is None: return {}
        try:
            import torchvision.transforms as T
            crop = self._crop(pil_img)
            tf   = T.Compose([T.Resize((112,112)),T.ToTensor(),
                               T.Normalize([.5,.5,.5],[.5,.5,.5])])
            t    = tf(crop.convert("RGB")).unsqueeze(0)
            with self.torch.no_grad():
                emb = self.model(t).squeeze().numpy()
            norm    = float(np.linalg.norm(emb))
            anomaly = round(max(0, min(100, (1-norm/25)*100)), 1)
            return {"anomaly_score": anomaly, "embedding_norm": round(norm,3),
                    "label": "Anomalous" if anomaly>60 else "Within Range"}
        except Exception as e:
            log.error(f"ArcFace error: {e}"); return {}


class OCREngine:
    """TrOCR (HuggingFace) — reads suspect photo / ID document images.

    NOTE: the deployed package (Investigator_OCR_v2) ships only
    config.json + model.safetensors + generation_config.json — no
    tokenizer/preprocessor files. The processor (image processor +
    tokenizer) is therefore loaded from the HF Hub base checkpoint
    (override via OCR_PROCESSOR_ID env var if the base model differs).
    This requires outbound internet access on first run; after that,
    HF's local cache makes it work offline.
    """
    def __init__(self, path):
        self.ready = False
        try:
            from transformers import TrOCRProcessor, VisionEncoderDecoderModel
            processor_id = os.environ.get("OCR_PROCESSOR_ID", "microsoft/trocr-base-printed")
            try:
                self.processor = TrOCRProcessor.from_pretrained(str(path), local_files_only=True)
            except Exception:
                log.info(f"OCR processor not bundled locally, fetching '{processor_id}' from HF Hub")
                self.processor = TrOCRProcessor.from_pretrained(processor_id)
            self.model = VisionEncoderDecoderModel.from_pretrained(str(path))
            self.model.eval()
            self.ready = True
            log.info("OCR ✓")
        except Exception as e:
            log.warning(f"OCR not loaded: {e}")

    def extract(self, files, max_pdf_pages=5):
        """Runs TrOCR across one or more uploaded documents and returns the
        combined extracted text (may be empty).

        `files` accepts:
          - a single PIL Image (legacy single-image call site),
          - a single filepath string (image or .pdf),
          - a list of filepath strings, mixing images and PDFs.

        Each PDF page is rasterized (via PyMuPDF) and OCR'd like an image;
        text from every file/page is concatenated with newlines.
        """
        if not self.ready or not files:
            return ""

        # Legacy call sites may still pass a PIL Image directly.
        from PIL import Image as _PILImage
        if isinstance(files, _PILImage.Image):
            return self._extract_one(files)

        paths = files if isinstance(files, list) else [files]
        texts = []
        for p in paths:
            if not p:
                continue
            try:
                p_str = str(p)
                if p_str.lower().endswith(".pdf"):
                    texts.append(self._extract_pdf(p_str, max_pages=max_pdf_pages))
                else:
                    img = _PILImage.open(p_str)
                    texts.append(self._extract_one(img))
            except Exception as e:
                log.error(f"OCR error reading {p}: {e}")
        return "\n".join(t for t in texts if t).strip()

    def _extract_one(self, pil_img):
        """Runs TrOCR on a single PIL image, returns extracted text (may be empty)."""
        if pil_img is None:
            return ""
        try:
            img = pil_img.convert("RGB")
            pixel_values = self.processor(images=img, return_tensors="pt").pixel_values
            generated_ids = self.model.generate(pixel_values, max_new_tokens=64)
            text = self.processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
            return text.strip()
        except Exception as e:
            log.error(f"OCR error: {e}"); return ""

    def _extract_pdf(self, pdf_path, max_pages=5):
        """Rasterizes up to `max_pages` pages of a PDF and OCRs each one."""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            log.warning(
                "PyMuPDF not installed (pip install pymupdf) — cannot OCR "
                f"PDF '{pdf_path}'; skipping this file."
            )
            return ""
        from PIL import Image as _PILImage
        page_texts = []
        try:
            doc = fitz.open(pdf_path)
            for i, page in enumerate(doc):
                if i >= max_pages:
                    break
                pix = page.get_pixmap(dpi=200)
                img = _PILImage.frombytes("RGB", [pix.width, pix.height], pix.samples)
                page_texts.append(self._extract_one(img))
            doc.close()
        except Exception as e:
            log.error(f"PDF OCR error ({pdf_path}): {e}")
        return "\n".join(t for t in page_texts if t).strip()

    def score(self, ocr_text, suspect_name):
        """
        Document-consistency score (higher = more suspicious):
          - empty/unreadable document → moderate flag
          - suspect name not found in extracted text → strong mismatch flag
        """
        if not ocr_text:
            return 45.0, {"match": None, "text": ""}
        s = 15.0
        name_match = None
        if suspect_name and suspect_name.strip():
            name_match = suspect_name.strip().lower() in ocr_text.lower()
            s += 5 if name_match else 50
        if len(ocr_text) < 8:
            s += 15
        return round(min(s, 95.0), 1), {"match": name_match, "text": ocr_text}


class XGBPatternEngine:
    def __init__(self, path):
        self.ready = False
        self.model = None
        # Try XGBoost JSON first, then pkl fallback
        for fname in ["risk_model.json", "xgb_model.json", "xgb_model.pkl",
                      "pattern_model.pkl", "pattern_model.json"]:
            fpath = path / fname
            if fpath.exists():
                try:
                    if fname.endswith(".json"):
                        import xgboost as xgb
                        self.model = xgb.XGBClassifier()
                        self.model.load_model(str(fpath))
                    else:
                        import joblib
                        self.model = joblib.load(fpath)
                    # 2026-11-06: refuse a model whose input size does not match this engine's features
                    # (risk_model.json is an offshore-company model with 8 company features, not 10 case features)
                    nf = None
                    try:
                        nf = int(self.model.get_booster().num_features())
                    except Exception:
                        nf = getattr(self.model, "n_features_in_", None)
                    if nf is not None and nf != len(self.KEYS):
                        log.warning(f"Pattern model {fname} expects {nf} features, engine sends {len(self.KEYS)}; "
                                    "not used (heuristic fallback)")
                        self.model = None
                        continue
                    self.ready = True
                    log.info(f"XGBoost Pattern ✓  ({fname})")
                    break
                except Exception as e:
                    log.warning(f"Pattern load failed ({fname}): {e}")
        if not self.ready:
            log.info("Pattern: heuristic fallback (no model file found)")

    KEYS = ["ner_crime","ner_weapon","ner_person","ner_threat",
            "voice_id_mismatch","face_anomaly","ocr_mismatch","modus_len","has_voice","has_photo"]

    def _vec(self, f):
        return np.array([[
            f.get("ner_crime",  0),
            f.get("ner_weapon", 0),
            f.get("ner_person", 0),
            f.get("ner_threat", 0),
            f.get("voice_id_mismatch", 50) / 100,
            f.get("face_anomaly",  50) / 100,
            f.get("ocr_mismatch",  20) / 100,
            min(f.get("modus_len", 0) / 500, 1.0),
            float(f.get("has_voice", 0)),
            float(f.get("has_photo", 0)),
        ]], dtype=np.float32)

    def predict(self, f):
        if self.ready:
            try:
                prob = float(self.model.predict_proba(self._vec(f))[0][1]) * 100
                return round(prob, 1), "xgboost"
            except Exception as e:
                log.error(f"XGB predict error: {e}")
        # heuristic
        s  = 35.0
        s += f.get("ner_crime",  0) * 10
        s += f.get("ner_weapon", 0) * 12
        s += f.get("ner_threat", 0) * 9
        s += f.get("ner_person", 0) * 3
        s += f.get("voice_id_mismatch", 50) * 0.30
        s += f.get("face_anomaly",  50) * 0.20
        s += f.get("ocr_mismatch",  20) * 0.15
        return round(min(s, 95), 1), "heuristic"

    def save_sample(self, features, label):
        out = MODELS_DIR / "risk_model" / "training_data.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "a") as fp:
            fp.write(json.dumps({"features": features, "label": label,
                                 "ts": datetime.now().isoformat()}) + "\n")


# ══════════════════════════════════════════════════════════════════════════════
# HF IMAGE CLASSIFIER ENGINE — generic, architecture-agnostic loader
# ══════════════════════════════════════════════════════════════════════════════

def _extract_video_frame(video_path, at_ratio=0.5):
    """
    Pulls one representative frame from an uploaded CCTV video for the
    CCTV/Deepfake image classifiers to run on (they're image models, not
    video models). Defaults to the frame at the video's midpoint, which
    tends to avoid black frames at the very start/end of a clip. Returns
    a PIL Image, or None if extraction fails for any reason — callers
    must handle None gracefully, same as "no photo submitted".
    """
    if not video_path:
        return None
    try:
        import cv2
        from PIL import Image
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        target_frame = int(total_frames * at_ratio) if total_frames > 1 else 0
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            return None
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(frame_rgb)
    except Exception as e:
        log.warning(f"CCTV frame extraction failed: {e}")
        return None


class HFImageClassifierEngine:
    """
    Generic wrapper around a HuggingFace AutoModelForImageClassification
    checkpoint. Unlike ArcFace (a raw state_dict with no config, requiring
    a hand-confirmed architecture), both crime_cctv/ and deepfake/face/
    ship as standard, self-describing HF checkpoints (config.json +
    preprocessor_config.json + model.safetensors) — so this loader is
    safely architecture- and label-set-agnostic: it reads id2label
    straight from the checkpoint's own config, never hardcoding or
    guessing a label space.

    Used for two independent instances:
      - CCTV crime-scene classifier  (models/crime_cctv/, local checkpoint)
      - Deepfake detector            (models/deepfake/face/, HF hub cache
                                       of the public prithivMLmods/
                                       Deepfake-vs-Real-8000 model)
    """

    def __init__(self, name, path=None, repo_id=None, cache_dir=None):
        self.name = name
        self.ready = False
        self.model = None
        self.processor = None
        self.id2label = {}
        try:
            from transformers import AutoModelForImageClassification, AutoImageProcessor
            import torch
            self.torch = torch

            if path is not None:
                if not path.exists() or not (path / "config.json").exists():
                    log.info(f"{name}: not loaded (no config.json at {path}) — optional, skipping")
                    return
                src, load_kwargs = str(path), {"local_files_only": True}
            elif repo_id is not None:
                src = repo_id
                load_kwargs = {"local_files_only": True}
                if cache_dir is not None:
                    load_kwargs["cache_dir"] = str(cache_dir)
            else:
                return

            self.processor = AutoImageProcessor.from_pretrained(src, **load_kwargs)
            self.model = AutoModelForImageClassification.from_pretrained(src, **load_kwargs)
            self.model.eval()
            self.id2label = dict(self.model.config.id2label)
            self.ready = True
            log.info(f"{name} ✓ (labels: {list(self.id2label.values())})")
        except Exception as e:
            log.warning(f"{name} not loaded: {e}")

    def classify(self, image):
        """image: PIL.Image, filepath, or numpy array (whatever face_eng
        already receives as `photo`). Returns a list of
        {"label": str, "score": 0-100} sorted by score descending, or
        None if unavailable/failed — callers must handle None gracefully."""
        if not self.ready or image is None:
            return None
        try:
            from PIL import Image
            if isinstance(image, str):
                image = Image.open(image).convert("RGB")
            elif hasattr(image, "convert"):
                image = image.convert("RGB")
            else:
                image = Image.fromarray(image).convert("RGB")

            inputs = self.processor(images=image, return_tensors="pt")
            with self.torch.no_grad():
                logits = self.model(**inputs).logits
            probs = self.torch.nn.functional.softmax(logits, dim=-1)[0]
            results = [
                {"label": self.id2label.get(i, str(i)), "score": round(float(probs[i]) * 100, 1)}
                for i in range(len(probs))
            ]
            results.sort(key=lambda r: r["score"], reverse=True)
            return results
        except Exception as e:
            log.error(f"{self.name} inference error: {e}")
            return None


# ══════════════════════════════════════════════════════════════════════════════
# QWEN GGUF ENGINE — llama-cpp-python, does NOT replace NER
# ══════════════════════════════════════════════════════════════════════════════

class QwenGGUFEngine:
    """
    Qwen model in GGUF format — loaded via llama-cpp-python from
    models/qwen/model.gguf, as an ADDITIONAL reasoning layer alongside
    (not instead of) the existing NER/Voice/Face/OCR/Risk models.

    NER stays the entity extractor for the pipeline; Qwen runs in parallel
    and adds what NER/XGBoost can't do on their own:
      - Statement-level insight (tone, sophistication, red flags)
      - LLM-generated investigative hypotheses (fed into the Reasoning
        Engine alongside the rule-based MO/Network hypotheses)
      - A deception-cue read on the modus text, used ONLY as a fallback
        when no voice evidence is available for a stress score
      - A draft investigative story/narrative for the journalist to edit

    Falls back gracefully (self.ready = False) if llama-cpp-python isn't
    installed, the .gguf file is missing/too small, or inference fails —
    the rest of the pipeline runs exactly as before in that case.
    """

    def __init__(self, gguf_path):
        self.ready = False
        self.model = None

        try:
            from llama_cpp import Llama

            if not gguf_path or not gguf_path.exists():
                log.info(f"Qwen GGUF: not loaded (no file at {gguf_path}) — optional, skipping")
                return

            file_size = gguf_path.stat().st_size / (1024 * 1024)
            if file_size < 50:
                log.warning(f"Qwen GGUF file too small ({file_size:.1f}MB) — skipping")
                return

            log.info(f"Qwen GGUF: loading {gguf_path.name} ({file_size:.1f}MB)...")

            n_gpu_layers = 0
            try:
                import torch
                n_gpu_layers = -1 if torch.cuda.is_available() else 0
            except Exception:
                pass

            self.model = Llama(
                model_path=str(gguf_path),
                n_ctx=4096,
                n_threads=8,
                n_gpu_layers=n_gpu_layers,
                verbose=False,
            )
            self.ready = True
            log.info(f"Qwen GGUF ✓ ({file_size:.1f}MB, GPU layers: {n_gpu_layers})")

        except ImportError:
            log.warning("Qwen GGUF: llama-cpp-python not installed — skipping")
        except Exception as e:
            log.warning(f"Qwen GGUF not loaded: {e}")

    def _infer(self, prompt, max_tokens=512, temperature=0.1):
        if not self.ready or self.model is None:
            return None
        try:
            response = self.model.create_chat_completion(
                messages=[
                    {"role": "system", "content": "You are an investigative assistant. Return valid JSON when requested."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                # Small quantized GGUF models are especially prone to
                # getting stuck repeating the same sentence/phrase —
                # these three penalties push the sampler away from
                # tokens/phrases it has already used in this response.
                repeat_penalty=1.3,
                frequency_penalty=0.4,
                presence_penalty=0.3,
                stop=["</s>", "```"],
            )
            return response["choices"][0]["message"]["content"]
        except Exception as e:
            log.error(f"Qwen GGUF inference error: {e}")
            return None

    @staticmethod
    def _collapse_repetition(text):
        """
        Defensive second layer: even with repeat/frequency/presence
        penalties, a small quantized model can still loop on the same
        sentence. This collapses consecutive (or near-consecutive)
        duplicate sentences down to a single occurrence, and hard-caps
        any single sentence from appearing more than twice in the whole
        response — so a report never ships with a paragraph that's just
        one line repeated 10 times.
        """
        if not text:
            return text
        import re as _re
        sentences = _re.split(r'(?<=[.!?])\s+', text.strip())
        seen_counts = {}
        out = []
        prev_norm = None
        for s in sentences:
            norm = _re.sub(r'\s+', ' ', s.strip().lower())
            if not norm:
                continue
            if norm == prev_norm:
                continue  # drop immediate repeats entirely
            seen_counts[norm] = seen_counts.get(norm, 0) + 1
            if seen_counts[norm] > 2:
                continue  # allow at most 2 occurrences of any exact sentence
            out.append(s.strip())
            prev_norm = norm
        return " ".join(out)

    @staticmethod
    def _extract_json(response, open_ch, close_ch):
        if not response:
            return None
        start = response.find(open_ch)
        end = response.rfind(close_ch) + 1
        if start == -1 or end <= start:
            return None
        try:
            return json.loads(response[start:end])
        except Exception:
            return None

    def analyze_statement(self, text, suspect_name=None, location=None):
        """Statement-level insight: tone, sophistication, red flags. Never
        used to accuse — purely descriptive signals for a human to weigh."""
        if not self.ready or not (text or "").strip():
            return {}
        prompt = f"""Analyze this statement and return ONLY JSON:
Statement: {text}
Suspect: {suspect_name or 'Unknown'}
Location: {location or 'Unknown'}

{{
    "entities_extracted": {{
        "persons": [], "organizations": [], "locations": [], "weapons": [],
        "crimes": [], "threats": [], "financial_terms": [], "digital_indicators": []
    }},
    "sentiment": {{"tone": "neutral", "deception_likelihood": 50, "emotional_state": "neutral", "confidence": "medium"}},
    "modus_operandi_insights": {{"pattern": "", "sophistication_level": "medium", "risk_indicators": [], "signature_behaviors": []}},
    "investigative_leads": {{"follow_up_questions": [], "evidence_gaps": [], "key_observations": []}}
}}"""
        response = self._infer(prompt, max_tokens=512, temperature=0.1)
        return self._extract_json(response, "{", "}") or {}

    def generate_hypotheses(self, modus, entities, watchlist_data, mo_links):
        """LLM-generated investigative hypotheses — merged into the
        rule-based Reasoning Engine's hypothesis list, each explicitly
        source-tagged 'Qwen LLM' so a human can weigh it accordingly."""
        if not self.ready:
            return []
        prompt = f"""Generate 3 investigative hypotheses. Return ONLY a JSON array:
MO: {(modus or '')[:500]}
Entities: {str(entities)[:300]}
Watchlist: {str(watchlist_data)[:200]}
[
    {{"hypothesis": "", "supporting_evidence": [], "contradicting_evidence": [],
      "confidence": "low/medium/high", "recommended_action": ""}}
]"""
        response = self._infer(prompt, max_tokens=900, temperature=0.2)
        return self._extract_json(response, "[", "]") or []

    def assess_deception(self, text):
        """Deception-cue read on language patterns — used only as a
        fallback signal when no voice evidence is available."""
        if not self.ready or not (text or "").strip():
            return {"deception_score": 50, "detected_cues": [], "confidence": "low"}
        prompt = f"""Analyze for deception indicators (vague language, inconsistent
details, overly defensive tone, emotional detachment, contradictions,
evasiveness). Return ONLY JSON:
Text: {text}
{{"deception_score": 0, "detected_cues": [], "confidence": "high/medium/low", "explanation": ""}}"""
        response = self._infer(prompt, max_tokens=512, temperature=0.1)
        return self._extract_json(response, "{", "}") or {"deception_score": 50, "detected_cues": [], "confidence": "low"}

    def generate_story_draft(self, case_id, modus, suspect_name, location, entities,
                              mo_links, unidentified_leads, watchlist, reasoning):
        """
        Draft investigative narrative in plain prose (not JSON) — a
        journalist-editable starting point that weaves together the case
        facts, MO Fingerprinting links, and Reasoning Engine gaps/leads
        into a short story-style draft. Every claim must still be
        independently verified by a human before publication — this is
        explicitly labelled as a draft, never a finished piece.
        """
        if not self.ready or not (modus or "").strip():
            return ""
        context = f"""CASE ID: {case_id or '(unassigned)'}
LOCATION: {location or 'Unknown'}
SUSPECT: {suspect_name or 'Unidentified'}
MODUS OPERANDI: {(modus or '')[:600]}
MO FINGERPRINTING LINKS: {len((mo_links or {}).get('linked_cases', []))} similar case(s) on record
UNIDENTIFIED-OFFENDER LEADS: {len((unidentified_leads or {}).get('possible_leads', []))} possible lead(s)
KNOWN DATASET HITS: {json.dumps(watchlist, default=str)[:400] if watchlist else 'None'}
EVIDENCE GAPS IDENTIFIED: {len((reasoning or {}).get('gaps', []))}
"""
        prompt = f"""You are a research assistant helping a journalist draft the OPENING of an
investigative story, based only on the facts below. Write 3-4 short
paragraphs in plain prose (not JSON, no headings). Requirements:
  - State only what the evidence below supports; do not invent names,
    dates, or outcomes not present in the context.
  - Every non-obvious factual claim should be followed by a short bracketed
    source tag, e.g. [case intake] or [MO Fingerprinting].
  - Never state or imply guilt — use "reportedly", "according to", "under
    investigation".
  - End with one line noting this is an AI-generated draft requiring full
    independent verification before publication.

CONTEXT:
{context}

Write the draft now:"""
        draft = self._infer(prompt, max_tokens=700, temperature=0.4)
        return self._collapse_repetition((draft or "").strip())
