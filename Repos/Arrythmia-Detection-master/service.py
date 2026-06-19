"""
Arrhythmia Inference Microservice
===================================
Runs on port 8001 (configurable via PORT env var).

Wraps the two-stage ECG cascade (binary screening → abnormal subtype) from
scripts/inference_cascade.py.  Models are loaded ONCE at startup into module-
level globals so every request is inference-only, with no repeated disk I/O.

Endpoints
---------
GET  /health               → {"status": "ok", "models_loaded": bool}
POST /predict              → ArrhythmiaResult
    Body: JSON {"signal": [[float]*12]*5000, "qrs7": [float]*7 (optional)}
    Returns:
        {
            "stage1": "Normal" | "Abnormal",
            "stage1_confidence": float,
            "stage2_class": "AF"|"IAVB"|"SB"|"STach"|null,
            "stage2_confidence": float | null,
            "all_probabilities": {...}
        }

Why JSON instead of file upload?
    ECG data arrives from medical devices or the main backend as numeric arrays.
    Sending a raw numpy array as JSON avoids requiring multipart form-data and
    keeps the service callable with a simple httpx.post(..., json=payload).
    For large batches, base64-encoded .npy could be added later.
"""

from __future__ import annotations

import os
import sys
import logging
import pathlib
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# Patch WindowsPath on non-Windows systems to load models serialized on Windows
if os.name != 'nt':
    pathlib.WindowsPath = pathlib.PosixPath

# ── Path setup ──────────────────────────────────────────────────────────────
# Add the repo's own src/ to sys.path so `from model import build_model` works.
REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from model import build_model  # noqa: E402  (comes from src/model.py)

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [arrhythmia] %(levelname)s %(message)s")
log = logging.getLogger("arrhythmia-service")

# ── Constants ────────────────────────────────────────────────────────────────
BINARY_CLASSES  = ["Normal", "Abnormal"]
ABNORMAL_CLASSES = ["AF", "IAVB", "SB", "STach"]

BINARY_CKPT  = REPO_ROOT / "models" / "binary_normal_abnormal" / "checkpoints" / "best.pt"
SUBTYPE_CKPT = REPO_ROOT / "models" / "abnormal_subtype"       / "checkpoints" / "best.pt"

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# ── Module-level model holders (populated at startup) ─────────────────────
_binary_model  = None
_subtype_model = None
_models_loaded = False


# ── Lifespan: load models once when the process starts ────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load both model checkpoints into VRAM/RAM before accepting requests."""
    global _binary_model, _subtype_model, _models_loaded

    log.info(f"Loading models on device={DEVICE}")
    try:
        _binary_model = _load_checkpoint(
            build_model(n_leads=12, n_classes=2, qrs_aux_dim=64, device=str(DEVICE)),
            BINARY_CKPT,
        )
        _subtype_model = _load_checkpoint(
            build_model(n_leads=12, n_classes=4, qrs_aux_dim=64, device=str(DEVICE)),
            SUBTYPE_CKPT,
        )
        _models_loaded = True
        log.info("Both ECG models loaded successfully.")
    except Exception as exc:
        log.error(f"Failed to load models: {exc}")
        # Service stays up but /predict will return 503 until models are available
    yield
    log.info("Arrhythmia service shutting down.")


def _load_checkpoint(model, path: Path):
    """Load a state-dict checkpoint and switch model to eval mode."""
    ckpt = torch.load(path, map_location=DEVICE)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()
    return model


# ── FastAPI app ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="Arrhythmia Detection Service",
    description="Two-stage ECG cascade: Normal/Abnormal screening then AF/IAVB/SB/STach subtype.",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Request / Response schemas ───────────────────────────────────────────────
class ECGRequest(BaseModel):
    """
    signal : list of 5000 samples, each sample is a list of 12 lead values.
             Shape after conversion: (5000, 12) float32.
    qrs7   : 7 Pan-Tompkins RR-interval statistics [optional].
             If omitted, zeros are used (model is trained to handle this).
    """
    signal: list[list[float]] = Field(..., description="5000×12 ECG array")
    qrs7: Optional[list[float]] = Field(None, description="7-element QRS feature vector")


class ArrhythmiaResult(BaseModel):
    stage1: str                       # "Normal" or "Abnormal"
    stage1_confidence: float
    stage2_class: Optional[str]       # None when stage1=="Normal"
    stage2_confidence: Optional[float]
    all_probabilities: dict           # full softmax dict for audit trail


# ── Inference helper ─────────────────────────────────────────────────────────
def _run_predict(model, signal_np: np.ndarray, qrs7_np: np.ndarray, class_names: list[str]) -> dict:
    """
    Run a single-sample forward pass.
    Returns {"class_name": str, "confidence": float, "probabilities": {name: float}}.
    """
    with torch.no_grad():
        sig_t  = torch.tensor(signal_np[None], dtype=torch.float32, device=DEVICE)  # (1,5000,12)
        qrs_t  = torch.tensor(qrs7_np[None],   dtype=torch.float32, device=DEVICE)  # (1,7)
        logits, _ = model(sig_t, qrs_t)
        probs  = torch.softmax(logits, dim=-1).cpu().numpy()[0]

    pred_idx = int(probs.argmax())
    return {
        "class_name": class_names[pred_idx],
        "confidence": float(probs[pred_idx]),
        "probabilities": {name: float(probs[i]) for i, name in enumerate(class_names)},
    }


# ── Endpoints ────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    """Lightweight health check used by the main backend to verify this service is up."""
    return {"status": "ok", "models_loaded": _models_loaded, "device": str(DEVICE)}


@app.post("/predict", response_model=ArrhythmiaResult)
def predict(req: ECGRequest):
    """
    Run the two-stage arrhythmia cascade on the submitted 12-lead ECG signal.

    Stage 1 (binary): classifies the signal as Normal or Abnormal.
    Stage 2 (subtype): only runs when Stage 1 returns Abnormal; identifies
        specific arrhythmia type: AF, IAVB, SB, or STach.
    """
    if not _models_loaded:
        raise HTTPException(status_code=503, detail="Models are not loaded yet. Retry in a moment.")

    # ── Validate and convert input ──────────────────────────────────────────
    try:
        signal_np = np.array(req.signal, dtype=np.float32)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse signal: {exc}")

    if signal_np.shape != (5000, 12):
        raise HTTPException(
            status_code=422,
            detail=f"Expected signal shape (5000, 12), got {signal_np.shape}. "
                   "Ensure you have sent 5000 time-steps × 12 leads."
        )

    if req.qrs7 is not None:
        qrs7_np = np.array(req.qrs7, dtype=np.float32)
        if qrs7_np.shape != (7,):
            raise HTTPException(status_code=422, detail=f"Expected qrs7 shape (7,), got {qrs7_np.shape}")
    else:
        qrs7_np = np.zeros(7, dtype=np.float32)  # safe default: model trained with zero-padding

    # ── Stage 1: Binary screening ────────────────────────────────────────────
    binary_result = _run_predict(_binary_model, signal_np, qrs7_np, BINARY_CLASSES)
    log.info(f"Stage 1: {binary_result['class_name']} ({binary_result['confidence']:.3f})")

    # ── Stage 2: Subtype (only when abnormal) ────────────────────────────────
    all_probs = {"binary": binary_result["probabilities"]}
    stage2_class = None
    stage2_conf  = None

    if binary_result["class_name"] == "Abnormal":
        subtype_result = _run_predict(_subtype_model, signal_np, qrs7_np, ABNORMAL_CLASSES)
        stage2_class   = subtype_result["class_name"]
        stage2_conf    = subtype_result["confidence"]
        all_probs["subtype"] = subtype_result["probabilities"]
        log.info(f"Stage 2: {stage2_class} ({stage2_conf:.3f})")

    return ArrhythmiaResult(
        stage1=binary_result["class_name"],
        stage1_confidence=binary_result["confidence"],
        stage2_class=stage2_class,
        stage2_confidence=stage2_conf,
        all_probabilities=all_probs,
    )


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8001))
    uvicorn.run("service:app", host="0.0.0.0", port=port, reload=False)
