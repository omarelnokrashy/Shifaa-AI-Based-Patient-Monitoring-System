"""
Fall Detection Inference Microservice
=======================================
Runs on port 8002 (configurable via PORT env var).

Architecture choice — WebSocket-per-camera-room:
    The original pipeline is a blocking frame-loop that requires a persistent
    video source.  Exposing a per-request REST endpoint would re-initialize
    the YOLO tracker and lose track IDs between calls — completely wrong for
    continuous monitoring.

    Instead this service exposes:
      - GET  /health                → liveness
      - POST /sessions              → create a named monitoring session for a room
      - DELETE /sessions/{room_id}  → stop a session
      - GET  /sessions              → list active sessions
      - WebSocket /ws/{room_id}     → bidirectional streaming:
            Client sends: JPEG frames as binary WebSocket messages.
            Server sends: JSON fall events  {"fall_detected": bool,
                                             "fall_probability": float,
                                             "track_id": str,
                                             "timestamp": float}

    The main backend connects to /ws/{room_id} (patient_id or room name) on
    behalf of an IP camera feed.  When a fall event fires, the main backend
    stores it in the DB and broadcasts the alert to the doctor's browser.

    Each WebSocket connection gets its own stateful pipeline instance (YOLO
    tracker, per-track skeleton buffers) so multiple rooms can run in parallel.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

# Prevent the `transformers` package (pulled in indirectly by ultralytics/timm)
# from disabling PyTorch when it detects a version older than 2.4.
# This service does NOT use HuggingFace models, so this is safe.
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import cv2
import mediapipe as mp
import numpy as np
import torch
from collections import deque
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

# ── Path setup ───────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent
RUNTIME_DIR = REPO_ROOT / "runtime"
sys.path.insert(0, str(RUNTIME_DIR))

from ctrgcn_model import Model                           # noqa: E402
from mediapipe_functions import mediapipe_to_ntu25       # noqa: E402
from role_classifier import MobileNetRoleClassifier      # noqa: E402

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [fall-svc] %(levelname)s %(message)s")
log = logging.getLogger("fall-detection-service")

# ── Constants ─────────────────────────────────────────────────────────────────
WINDOW_SIZE = 72
CLASS_MAP   = {0: "non_fall", 1: "fall"}
FALL_THRESHOLD   = float(os.getenv("FALL_THRESHOLD", "0.90"))
ROLE_THRESHOLD   = float(os.getenv("ROLE_THRESHOLD", "0.50"))
INFER_EVERY      = int(os.getenv("INFER_EVERY", "6"))
ROLE_EVERY       = int(os.getenv("ROLE_EVERY", "10"))

YOLO_WEIGHTS = REPO_ROOT / "model_weights" / "patient_detection_yolov8n.pt"
ROLE_WEIGHTS = REPO_ROOT / "model_weights" / "role_classification_mobilenetv3_best.pt"
FALL_WEIGHTS = REPO_ROOT / "model_weights" / "fall_motion_ctrgcn_72f_impact.pt"

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# ── Module-level model holders ────────────────────────────────────────────────
_yolo         = None
_role_clf     = None
_fall_model   = None
_models_loaded = False


# ── Lifespan: load all models once ───────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _yolo, _role_clf, _fall_model, _models_loaded
    log.info(f"Loading fall detection models on device={DEVICE}")
    try:
        from ultralytics import YOLO
        _yolo       = YOLO(str(YOLO_WEIGHTS))
        _role_clf   = MobileNetRoleClassifier(str(ROLE_WEIGHTS), device=DEVICE)
        _fall_model = _load_fall_model(str(FALL_WEIGHTS), DEVICE)
        _models_loaded = True
        log.info("Fall detection models loaded.")
    except Exception as exc:
        log.error(f"Model load failed: {exc}")
    yield
    log.info("Fall detection service shutting down.")


def _load_fall_model(weights_path: str, device: str):
    """Load the CTR-GCN fall classifier from its checkpoint."""
    import graph.ntu_rgb_d  # noqa — ensures graph module is importable
    model = Model(
        num_class=2, num_point=25, num_person=2,
        in_channels=3, graph="graph.ntu_rgb_d.Graph",
        graph_args={"labeling_mode": "spatial"},
    )
    ckpt = torch.load(weights_path, map_location=device, weights_only=False)
    model.load_state_dict(ckpt)
    model.to(device)
    model.eval()
    return model


# ── Per-session pipeline state ────────────────────────────────────────────────
class RoomSession:
    """Holds all mutable state for one active monitoring room / camera stream."""

    def __init__(self, room_id: str):
        self.room_id        = room_id
        self.track_state: dict = {}
        self.frame_index    = 0
        self.mp_pose        = None       # mediapipe Pose context
        self.created_at     = time.time()
        log.info(f"Session created: room_id={room_id}")

    def start_pose(self):
        mp_pose = mp.solutions.pose
        self.mp_pose = mp_pose.Pose(
            static_image_mode=False, model_complexity=1,
            min_detection_confidence=0.5, min_tracking_confidence=0.5,
        ).__enter__()

    def stop_pose(self):
        if self.mp_pose:
            try:
                self.mp_pose.__exit__(None, None, None)
            except Exception:
                pass
            self.mp_pose = None


# ── Active sessions registry ──────────────────────────────────────────────────
_active_sessions: dict[str, RoomSession] = {}


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Fall Detection Service",
    description="Real-time patient fall detection via YOLO+MediaPipe+CTR-GCN.",
    version="1.0.0",
    lifespan=lifespan,
)


class SessionCreateRequest(BaseModel):
    room_id: str


class SessionInfo(BaseModel):
    room_id:    str
    created_at: float
    active:     bool


@app.get("/health")
def health():
    return {"status": "ok", "models_loaded": _models_loaded, "active_sessions": len(_active_sessions)}


@app.post("/sessions", response_model=SessionInfo)
def create_session(req: SessionCreateRequest):
    """Create a named monitoring session.  Idempotent — returns existing if already open."""
    if req.room_id not in _active_sessions:
        _active_sessions[req.room_id] = RoomSession(req.room_id)
    s = _active_sessions[req.room_id]
    return SessionInfo(room_id=s.room_id, created_at=s.created_at, active=True)


@app.delete("/sessions/{room_id}")
def delete_session(room_id: str):
    """Stop and remove a monitoring session."""
    if room_id not in _active_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    _active_sessions[room_id].stop_pose()
    del _active_sessions[room_id]
    log.info(f"Session deleted: room_id={room_id}")
    return {"deleted": room_id}


@app.get("/sessions", response_model=list[SessionInfo])
def list_sessions():
    return [
        SessionInfo(room_id=s.room_id, created_at=s.created_at, active=True)
        for s in _active_sessions.values()
    ]


# ── WebSocket streaming endpoint ─────────────────────────────────────────────
@app.websocket("/ws/{room_id}")
async def ws_room(websocket: WebSocket, room_id: str):
    """
    Streaming camera WebSocket for a specific room.

    Protocol:
      - Client sends binary messages containing JPEG-encoded frames.
      - Server responds with JSON fall-detection events for each frame processed.
      - Client should disconnect when monitoring ends; server cleans up state.
    """
    if not _models_loaded:
        await websocket.close(code=1013, reason="Models not ready")
        return

    await websocket.accept()
    log.info(f"WebSocket connected: room_id={room_id}")

    # Get or create session
    if room_id not in _active_sessions:
        _active_sessions[room_id] = RoomSession(room_id)
    session = _active_sessions[room_id]
    session.start_pose()

    try:
        while True:
            # Receive a JPEG frame as raw bytes
            raw_bytes = await websocket.receive_bytes()
            frame = _bytes_to_frame(raw_bytes)
            if frame is None:
                continue

            event = await asyncio.get_event_loop().run_in_executor(
                None, _process_frame, session, frame
            )

            if event is not None:
                await websocket.send_json(event)

    except WebSocketDisconnect:
        log.info(f"WebSocket disconnected: room_id={room_id}")
    finally:
        session.stop_pose()
        # Keep session registered (it may reconnect); delete explicitly via REST if done.


def _bytes_to_frame(data: bytes) -> Optional[np.ndarray]:
    """Decode a JPEG byte payload into a BGR numpy frame."""
    try:
        arr = np.frombuffer(data, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return frame if frame is not None else None
    except Exception as exc:
        log.debug(f"Frame decode error: {exc}")
        return None


def _process_frame(session: RoomSession, frame: np.ndarray) -> Optional[dict]:
    """
    Run one frame through the full pipeline.
    Returns a fall-event dict if a prediction was made, else None.
    This function is CPU/GPU bound so it runs in a thread executor.
    """
    session.frame_index += 1
    frame_index = session.frame_index
    h, w = frame.shape[:2]

    # ── YOLO detection + tracking ─────────────────────────────────────────
    results = _yolo.track(
        source=frame, persist=True, classes=[0],
        conf=0.25, iou=0.45, imgsz=640, verbose=False,
    )[0]

    if results.boxes is None:
        return None

    boxes = results.boxes.xyxy.cpu().numpy()
    ids   = (results.boxes.id.cpu().numpy().astype(int)
             if results.boxes.id is not None
             else [f"det_{i}" for i in range(len(boxes))])

    best_event = None

    for box_vals, raw_id in zip(boxes, ids):
        x1, y1, x2, y2 = [int(v) for v in box_vals]
        x1 = max(0, min(w - 1, x1)); y1 = max(0, min(h - 1, y1))
        x2 = max(0, min(w,     x2)); y2 = max(0, min(h,     y2))
        if (x2 - x1) <= 0 or (y2 - y1) <= 0:
            continue

        track_id = str(int(raw_id)) if not isinstance(raw_id, str) else raw_id
        state    = session.track_state.setdefault(track_id, {
            "sequence":     deque(maxlen=WINDOW_SIZE),
            "prev_kpts":    None,
            "role_label":   "person",
            "role_conf":    0.0,
            "fall_prob":    0.0,
            "fall_streak":  0,
            "alarm_active": False,
            "last_role_f":  -9999,
            "last_infer_f": -9999,
        })

        # Role classification (every ROLE_EVERY frames per track)
        if frame_index - state["last_role_f"] >= ROLE_EVERY:
            crop = frame[y1:y2, x1:x2]
            if crop.size > 0:
                state["role_label"], state["role_conf"] = _role_clf.predict_crop(crop)
                state["last_role_f"] = frame_index

        is_patient = (state["role_label"] == "patient" and state["role_conf"] >= ROLE_THRESHOLD)
        if not is_patient:
            continue

        # MediaPipe pose
        crop_rgb = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2RGB)
        result   = session.mp_pose.process(crop_rgb)
        if result.pose_landmarks:
            mp_kpts  = np.array([[lm.x, lm.y, lm.z] for lm in result.pose_landmarks.landmark], dtype=np.float32)
            ctr_kpts = mediapipe_to_ntu25(mp_kpts, state["prev_kpts"])
            state["prev_kpts"] = ctr_kpts.copy()
            state["sequence"].append(ctr_kpts)
        else:
            state["sequence"].append(np.zeros((25, 3), dtype=np.float32))

        # CTR-GCN inference every INFER_EVERY frames once buffer is full
        if len(state["sequence"]) == WINDOW_SIZE and frame_index - state["last_infer_f"] >= INFER_EVERY:
            label, conf, fall_prob = _predict_fall(list(state["sequence"]))
            state["last_infer_f"] = frame_index
            state["fall_prob"]    = fall_prob

            if fall_prob >= FALL_THRESHOLD:
                state["fall_streak"] += 1
            else:
                state["fall_streak"] = 0
                state["alarm_active"] = False

            # Require ≥2 consecutive predictions to trigger (reduces flicker)
            state["alarm_active"] = state["fall_streak"] >= 2
            if state["alarm_active"]:
                best_event = {
                    "fall_detected":   True,
                    "fall_probability": round(fall_prob, 4),
                    "track_id":        track_id,
                    "timestamp":       time.time(),
                }
                log.warning(f"FALL DETECTED room={session.room_id} track={track_id} p={fall_prob:.3f}")

    return best_event


def _preprocess_window(sequence: list) -> Optional[np.ndarray]:
    x = np.array(sequence, dtype=np.float32)
    if len(x) != WINDOW_SIZE or not np.any(np.abs(x) > 1e-8):
        return None
    root   = x[:, 0, :]
    x      = x - root[:, None, :]
    bones  = [(0, 1), (1, 2), (2, 3), (0, 12), (0, 16)]
    lengths = np.stack([np.linalg.norm(x[:, i] - x[:, j], axis=1) for i, j in bones], axis=1)
    scale   = np.median(lengths[lengths > 1e-6]) if np.any(lengths > 1e-6) else 1.0
    x      = x / scale
    first_p = np.transpose(x, (2, 0, 1))[:, :, :, None]
    return np.concatenate([first_p, np.zeros_like(first_p)], axis=3).astype(np.float32)


@torch.no_grad()
def _predict_fall(sequence: list):
    data = _preprocess_window(sequence)
    if data is None:
        return "no_pose", 0.0, 0.0
    tensor = torch.tensor(data).unsqueeze(0).to(DEVICE)
    probs  = torch.softmax(_fall_model(tensor), dim=1)[0].cpu().numpy()
    pred   = int(np.argmax(probs))
    return CLASS_MAP[pred], float(probs[pred]), float(probs[1])


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8002))
    uvicorn.run("service:app", host="0.0.0.0", port=port, reload=False)
