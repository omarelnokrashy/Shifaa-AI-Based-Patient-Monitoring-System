"""
Seizure Detection Inference Microservice
==========================================
Runs on port 8003 (configurable via PORT env var).

Architecture choice — subprocess-per-session:
    The seizure pipeline (runtime/inference.py → live.main()) is a blocking
    frame-loop that configures itself entirely through environment variables
    and module-level globals that are set BEFORE importing the inference module.
    This design makes it impossible to run multiple sessions in the same process,
    or to call it in a non-blocking way from an async server without major
    refactoring of code we are not allowed to touch.

    Solution: each monitoring session is launched as a child subprocess running
    real_time_seizure_pipeline.py with --no-display --alert-log pointing to a
    named temp file.  A background thread tails that CSV and translates new
    rows into WebSocket events pushed to the connected client.

Endpoints
---------
GET  /health                  → {"status": "ok", "active_sessions": int}
POST /sessions                → start a new session, returns {"session_id": str}
DELETE /sessions/{session_id} → terminate the subprocess
GET  /sessions                → list active sessions
WebSocket /ws/{session_id}    → real-time event stream
    Server sends JSON: {
        "status":          "NORMAL" | "SEIZURE" | "INITIALISING",
        "gate_score":      float,
        "seizure_source":  str,
        "alert":           bool,
        "alert_latched":   bool,
        "timestamp":       float
    }
"""

from __future__ import annotations

import asyncio
import csv
import logging
import os
import subprocess
import sys
import tempfile
import time
import threading
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [seizure-svc] %(levelname)s %(message)s")
log = logging.getLogger("seizure-service")

# ── Path constants ────────────────────────────────────────────────────────────
REPO_ROOT    = Path(__file__).resolve().parent
PIPELINE_PY  = REPO_ROOT / "runtime" / "real_time_seizure_pipeline.py"
PYTHON_EXE   = sys.executable        # same interpreter that runs this service
ALERT_LOG_DIR = REPO_ROOT / "runtime_outputs" / "alert_logs"
ALERT_LOG_DIR.mkdir(parents=True, exist_ok=True)


# ── Per-session state ─────────────────────────────────────────────────────────
class SeizureSession:
    """
    Wraps one subprocess running the seizure pipeline.
    Also owns the CSV tail thread and the list of subscribed WebSocket clients.
    """

    def __init__(self, session_id: str, source: str, mode: str, bed_roi: str):
        self.session_id  = session_id
        self.source      = source
        self.mode        = mode
        self.bed_roi     = bed_roi
        self.alert_log   = str(ALERT_LOG_DIR / f"{session_id}_alerts.csv")
        self.created_at  = time.time()
        self.proc: Optional[subprocess.Popen] = None
        self.clients: list[WebSocket] = []
        self._tail_thread: Optional[threading.Thread] = None
        self._stop_event  = threading.Event()
        self.last_event: Optional[dict] = None

    def start(self):
        """Launch the pipeline subprocess and begin tailing the alert CSV."""
        cmd = [
            PYTHON_EXE, str(PIPELINE_PY),
            "--source", str(self.source),
            "--mode", self.mode,
            "--no-display", "--no-output",
            "--alert-log", self.alert_log,
        ]
        if self.bed_roi:
            cmd += ["--bed-roi", self.bed_roi]

        log.info(f"[{self.session_id}] Launching subprocess: {' '.join(cmd)}")
        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            cwd=str(REPO_ROOT),
        )
        self._tail_thread = threading.Thread(
            target=self._tail_alert_csv, daemon=True
        )
        self._tail_thread.start()

    def stop(self):
        """Terminate the subprocess and stop the tail thread."""
        self._stop_event.set()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        log.info(f"[{self.session_id}] Session stopped.")

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _tail_alert_csv(self):
        """
        Background thread: wait for the alert CSV to appear, then tail new rows.
        For each new CSV row, convert to a dict and push to all connected clients.
        """
        # Wait up to 30 s for the subprocess to create the CSV file
        deadline = time.time() + 30
        while not os.path.exists(self.alert_log) and time.time() < deadline:
            if self._stop_event.is_set():
                return
            time.sleep(0.5)

        if not os.path.exists(self.alert_log):
            log.warning(f"[{self.session_id}] Alert CSV never appeared; subprocess may have crashed.")
            return

        with open(self.alert_log, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            while not self._stop_event.is_set():
                for row in reader:
                    if self._stop_event.is_set():
                        break
                    event = _csv_row_to_event(row)
                    self.last_event = event
                    asyncio.run_coroutine_threadsafe(
                        self._broadcast(event), _event_loop
                    )
                time.sleep(0.2)  # poll interval

    async def _broadcast(self, event: dict):
        """Send an event to all currently connected WebSocket clients."""
        disconnected = []
        for ws in self.clients:
            try:
                await ws.send_json(event)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            try:
                self.clients.remove(ws)
            except ValueError:
                pass


def _csv_row_to_event(row: dict) -> dict:
    """Convert a raw CSV row from the alert log into a typed event dict."""
    def _float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return {
        "frame":          int(row.get("frame", 0) or 0),
        "time_sec":       _float(row.get("time_sec")),
        "status":         row.get("status", "INITIALISING"),
        "gate_score":     _float(row.get("seizure_signal")),
        "seizure_source": row.get("seizure_source", ""),
        "ap_sum":         _float(row.get("ap_sum")),
        "current_risk":   _float(row.get("current_risk")),
        "cj_prob":        _float(row.get("cj_prob")),
        "alert":          row.get("status") == "SEIZURE",
        "alert_latched":  row.get("alert_latched", "0") == "1",
        "timestamp":      time.time(),
    }


# ── Active sessions + event loop reference ───────────────────────────────────
_sessions: dict[str, SeizureSession] = {}
_event_loop: asyncio.AbstractEventLoop


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _event_loop
    _event_loop = asyncio.get_event_loop()
    log.info("Seizure detection service started.")
    yield
    log.info("Shutting down; stopping all sessions.")
    for s in list(_sessions.values()):
        s.stop()


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Seizure Detection Service",
    description="Real-time VSViG + Cross-Joint seizure monitoring via subprocess isolation.",
    version="1.0.0",
    lifespan=lifespan,
)


class StartSessionRequest(BaseModel):
    session_id: str                               # caller supplies e.g. patient_id
    source:     str                               # camera index, file path, or RTSP URL
    mode:       str = "monitor"                  # "safety" | "monitor" | "screening"
    bed_roi:    str = ""                          # optional "x1,y1,x2,y2"


class SessionInfo(BaseModel):
    session_id: str
    source:     str
    mode:       str
    alive:      bool
    created_at: float
    clients:    int


@app.get("/health")
def health():
    alive = sum(1 for s in _sessions.values() if s.is_alive())
    return {"status": "ok", "active_sessions": len(_sessions), "alive_processes": alive}


@app.post("/sessions", response_model=SessionInfo)
def start_session(req: StartSessionRequest):
    """Start a new seizure monitoring session for a patient room/camera."""
    if req.session_id in _sessions:
        s = _sessions[req.session_id]
        if s.is_alive():
            return _session_info(s)
        # Stale — clean up and restart
        s.stop()
        del _sessions[req.session_id]

    if req.mode not in ("safety", "monitor", "screening"):
        raise HTTPException(status_code=422, detail="mode must be safety | monitor | screening")

    session = SeizureSession(req.session_id, req.source, req.mode, req.bed_roi)
    session.start()
    _sessions[req.session_id] = session
    log.info(f"Session started: {req.session_id} source={req.source} mode={req.mode}")
    return _session_info(session)


@app.delete("/sessions/{session_id}")
def stop_session(session_id: str):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    _sessions[session_id].stop()
    del _sessions[session_id]
    return {"stopped": session_id}


@app.get("/sessions", response_model=list[SessionInfo])
def list_sessions():
    return [_session_info(s) for s in _sessions.values()]


@app.websocket("/ws/{session_id}")
async def ws_session(websocket: WebSocket, session_id: str):
    """
    Subscribe to real-time seizure events for an active session.

    Multiple clients (e.g. doctor's browser and the main backend) can
    subscribe to the same session simultaneously.
    """
    if session_id not in _sessions:
        await websocket.close(code=4004, reason="Session not found — start it via POST /sessions first")
        return

    session = _sessions[session_id]
    await websocket.accept()
    session.clients.append(websocket)
    log.info(f"Client subscribed: session={session_id} total_clients={len(session.clients)}")

    # Send the last known event immediately so the client sees the current state
    if session.last_event:
        await websocket.send_json(session.last_event)

    try:
        while True:
            # Keep-alive: wait for any message from the client (e.g. ping)
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        try:
            session.clients.remove(websocket)
        except ValueError:
            pass
        log.info(f"Client unsubscribed: session={session_id} remaining={len(session.clients)}")


def _session_info(s: SeizureSession) -> SessionInfo:
    return SessionInfo(
        session_id=s.session_id,
        source=s.source,
        mode=s.mode,
        alive=s.is_alive(),
        created_at=s.created_at,
        clients=len(s.clients),
    )


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8003))
    uvicorn.run("service:app", host="0.0.0.0", port=port, reload=False)
