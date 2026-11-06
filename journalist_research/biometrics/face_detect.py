"""Face detection for DOA and the face engine (2026-11-06).

The server's OpenCV 5 build has no CascadeClassifier, so the old Haar crop silently failed and whole
images were embedded. This uses OpenCV's YuNet detector (opencv_zoo, Apache-2.0, models/face_detect/).
"""
import os
from pathlib import Path
from typing import List, Tuple, Any

import numpy as np

APP = Path(__file__).resolve().parents[2]
YUNET = APP / "models" / "face_detect" / "face_detection_yunet_2023mar.onnx"
MAX_SIDE = 1280


def detect_faces(pil, min_score: float = 0.8, min_size: int = 40) -> List[Tuple[Tuple[int, int, int, int], Any]]:
    """[(box(x,y,w,h), PIL crop)] largest first. Empty list when no detector or no face."""
    import cv2
    from PIL import Image
    rgb = np.array(pil.convert("RGB"))
    h0, w0 = rgb.shape[:2]
    scale = min(1.0, MAX_SIDE / float(max(h0, w0)))
    small = cv2.resize(rgb, (int(w0 * scale), int(h0 * scale))) if scale < 1.0 else rgb
    boxes = []
    if YUNET.exists() and hasattr(cv2, "FaceDetectorYN"):
        bgr = cv2.cvtColor(small, cv2.COLOR_RGB2BGR)
        det = cv2.FaceDetectorYN.create(str(YUNET), "", (bgr.shape[1], bgr.shape[0]), min_score, 0.3, 5000)
        det.setInputSize((bgr.shape[1], bgr.shape[0]))
        _, faces = det.detect(bgr)
        for f in (faces if faces is not None else []):
            x, y, w, h = [int(round(v / scale)) for v in f[:4]]
            boxes.append((x, y, w, h))
    elif hasattr(cv2, "CascadeClassifier"):
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        cas = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        boxes = [tuple(int(v) for v in b) for b in cas.detectMultiScale(gray, 1.1, 5, minSize=(min_size, min_size))]
    out = []
    for (x, y, w, h) in sorted(boxes, key=lambda b: -b[2] * b[3])[:12]:
        x, y = max(0, x), max(0, y)
        w, h = min(w, w0 - x), min(h, h0 - y)
        if w >= min_size and h >= min_size:
            out.append(((x, y, w, h), Image.fromarray(rgb[y:y + h, x:x + w])))
    return out
