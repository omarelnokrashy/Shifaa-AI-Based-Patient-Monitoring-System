"""
Seizure Detection Inference Microservice
==========================================
Runs on port 8003 (configurable via PORT env var).

Spawns one C++ subprocess and one in-process Python thread per session:
  1. seizure_runtime_cpp.exe (C++ native ONNX openpose/vsvig runtime)
  2. Background python thread (ViViT tokens producer, using globally cached models)
They communicate via Win32 Named Pipes. A background thread tails the C++
alerts CSV output and broadcasts it to WebSocket subscribers.
"""

from __future__ import annotations

import importlib.util
_orig_find_spec = importlib.util.find_spec
importlib.util.find_spec = lambda name, package=None: None if name == 'torchaudio' else _orig_find_spec(name, package)

import os
# Smart HuggingFace offline detection — must run before any HF imports.
# Sets offline mode only when the model is already cached; otherwise allows
# first-time download so a fresh machine can self-provision.
sys_pre = __import__('sys')
sys_pre.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent / 'runtime'))
from utils.hf_utils import configure_hf_mode as _configure_hf_mode
_VIVIT_MODEL_ID = "google/vivit-b-16x2-kinetics400"
_vivit_offline = _configure_hf_mode(_VIVIT_MODEL_ID)

import asyncio
import csv
import logging
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

# ── Path constants ───────────────────────────────────────────────────────────
REPO_ROOT     = Path(__file__).resolve().parent
CPP_RUN_EXE   = REPO_ROOT / "runtime" / "build" / "seizure_runtime_cpp.exe"
PYTHON_EXE    = sys.executable        # same interpreter that runs this service
ALERT_LOG_DIR = REPO_ROOT.parent.parent / "outputs" / "runtime" / "alert_logs"
ALERT_LOG_DIR.mkdir(parents=True, exist_ok=True)

# Add vendor paths for imports
vendor_path = REPO_ROOT.parent.parent / "third_party" / "joint-attention-seizure-detection"
pose_repo_path = REPO_ROOT.parent.parent / "third_party" / "lightweight-human-pose-estimation.pytorch"
for p in (vendor_path, pose_repo_path, REPO_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# ── Global PyTorch Models ─────────────────────────────────────────────────────
device = None
pose_model = None
vivit_model = None

def load_global_models():
    global device, pose_model, vivit_model
    if pose_model is not None:
        return
    
    import torch
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log.info(f"Loading global PyTorch models on device: {device}...")
    
    # Add torch/lib and CUDA bin to PATH so DLLs resolve on Windows.
    # Paths are discovered from the active Python environment — no hardcoding.
    dll_dirs: list[str] = []
    try:
        import torch
        torch_lib = str(__import__('pathlib').Path(torch.__file__).parent / 'lib')
        if os.path.isdir(torch_lib):
            dll_dirs.append(torch_lib)
    except Exception:
        pass
    # Add CUDA bin if nvcc or cuda_runtime is detectable
    try:
        import subprocess as _sp
        _nvcc = _sp.run(['nvcc', '--version'], capture_output=True, timeout=5)
        if _nvcc.returncode == 0:
            import shutil as _sh
            nvcc_path = _sh.which('nvcc')
            if nvcc_path:
                dll_dirs.append(str(__import__('pathlib').Path(nvcc_path).parent))
    except Exception:
        pass
    for p in dll_dirs:
        if os.path.isdir(p):
            os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
            if sys.platform == 'win32':
                try:
                    os.add_dll_directory(p)
                except Exception:
                    pass

    # Imports
    from runtime.utils.pose import load_pose_model
    from seizure_classifier.models import VivitModel
    
    pose_weights = REPO_ROOT.parent.parent / "models" / "seizure" / "pose.pth"
    pose_model = load_pose_model(str(pose_weights), device)
    
    vivit_name = _VIVIT_MODEL_ID
    log.info(f"Loading ViViT from HuggingFace ({'offline/cached' if _vivit_offline else 'online download'})...")
    vivit_model = VivitModel.from_pretrained(
        vivit_name,
        local_files_only=_vivit_offline,
        use_safetensors=False,
    ).to(device).eval()
    log.info("Global PyTorch models loaded successfully.")


# ── Per-session state ─────────────────────────────────────────────────────────
class SeizureSession:
    """
    Wraps C++ subprocess and Python token-producer thread running the seizure pipeline.
    Also owns the CSV tail thread and the list of subscribed WebSocket clients.
    """

    def __init__(self, session_id: str, source: str, mode: str, bed_roi: str):
        self.session_id  = session_id
        self.source      = source
        self.mode        = mode
        self.bed_roi     = bed_roi
        self.alert_log   = str(ALERT_LOG_DIR / f"{session_id}_alerts.csv")
        self.created_at  = time.time()
        self.proc_cpp: Optional[subprocess.Popen] = None
        self._py_thread: Optional[threading.Thread] = None
        self.clients: list[WebSocket] = []
        self._tail_thread: Optional[threading.Thread] = None
        self._stop_event  = threading.Event()
        self.last_event: Optional[dict] = None
        self.ready        = False
        self.latch_override = False
        self.latch_start_time = None
        
        self.cpp_stdout_file = None
        self.cpp_stderr_file = None
        self.py_stdout_file = None
        self.py_stderr_file = None

    def start(self):
        """Launch C++ runtime subprocess, start Python IPC thread, and tail CSV."""
        pipe_name = f"\\\\.\\pipe\\seizure_vivit_tokens_{self.session_id}"
        
        # 1. C++ Runtime Command
        cpp_cmd = [
            str(CPP_RUN_EXE),
            "run",
            "--root", str(REPO_ROOT),
            "--source", str(self.source),
            "--output-csv", self.alert_log,
            "--pipe-name", pipe_name,
        ]

        # Clear old alert log if it exists
        if os.path.exists(self.alert_log):
            try:
                os.remove(self.alert_log)
            except Exception:
                pass

        cpp_stdout_path = ALERT_LOG_DIR / f"{self.session_id}_cpp_stdout.log"
        cpp_stderr_path = ALERT_LOG_DIR / f"{self.session_id}_cpp_stderr.log"
        py_stdout_path = ALERT_LOG_DIR / f"{self.session_id}_py_stdout.log"
        py_stderr_path = ALERT_LOG_DIR / f"{self.session_id}_py_stderr.log"

        try:
            self.cpp_stdout_file = open(cpp_stdout_path, "w", encoding="utf-8")
            self.cpp_stderr_file = open(cpp_stderr_path, "w", encoding="utf-8")
            self.py_stdout_file = open(py_stdout_path, "w", encoding="utf-8")
            self.py_stderr_file = open(py_stderr_path, "w", encoding="utf-8")
        except Exception as e:
            log.error(f"Failed to open logging files: {e}")

        # Prepend CUDA bin path and torch lib paths to PATH environment variable for DLL resolution
        paths_to_add = [
            r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.2\bin",
            r"C:\python\Lib\site-packages\torch\lib"
        ]
        env = os.environ.copy()
        added_paths = []
        for p in paths_to_add:
            if os.path.exists(p):
                env["PATH"] = p + os.pathsep + env.get("PATH", "")
                added_paths.append(p)
        if added_paths:
            log.info(f"[{self.session_id}] Prepended to PATH: {', '.join(added_paths)}")

        log.info(f"[{self.session_id}] Launching C++ subprocess: {' '.join(cpp_cmd)}")
        self.proc_cpp = subprocess.Popen(
            cpp_cmd,
            stdout=self.cpp_stdout_file or subprocess.DEVNULL,
            stderr=self.cpp_stderr_file or subprocess.PIPE,
            env=env,
            cwd=str(REPO_ROOT),
        )

        log.info(f"[{self.session_id}] Starting in-process token producer thread.")
        self._py_thread = threading.Thread(
            target=self._run_token_producer,
            args=(pipe_name,),
            daemon=True
        )
        self._py_thread.start()

        self._tail_thread = threading.Thread(
            target=self._tail_alert_csv, daemon=True
        )
        self._tail_thread.start()

    def stop(self):
        """Terminate the subprocess and stop the token producer and tail threads."""
        self._stop_event.set()
        
        # Stop C++ subprocess
        if self.proc_cpp and self.proc_cpp.poll() is None:
            self.proc_cpp.terminate()
            try:
                self.proc_cpp.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc_cpp.kill()
                
        # Wait for token producer thread
        if self._py_thread:
            self._py_thread.join(timeout=3)
            self._py_thread = None

        for f in (self.cpp_stdout_file, self.cpp_stderr_file, self.py_stdout_file, self.py_stderr_file):
            if f:
                try:
                    f.close()
                except Exception:
                    pass
        log.info(f"[{self.session_id}] Session stopped.")

    def is_alive(self) -> bool:
        return (self.proc_cpp is not None and self.proc_cpp.poll() is None and
                self._py_thread is not None and self._py_thread.is_alive())

    def _run_token_producer(self, pipe_name: str):
        def session_log(msg):
            log_line = f"[{self.session_id}] {msg}\n"
            if self.py_stdout_file:
                try:
                    self.py_stdout_file.write(log_line)
                    self.py_stdout_file.flush()
                except Exception:
                    pass
            log.info(f"[{self.session_id}] {msg}")

        session_log("Token producer thread started.")
        
        # Connect to named pipe created by C++ runtime
        pipe = None
        for _ in range(300):
            if self._stop_event.is_set():
                return
            try:
                pipe = open(pipe_name, "wb")
                break
            except FileNotFoundError:
                time.sleep(0.2)
                
        if pipe is None:
            session_log("Failed to connect to pipe after 60 seconds.")
            return
            
        session_log("Connected to pipe!")

        try:
            import cv2
            import numpy as np
            import torch
            import struct
            from runtime.utils.pose import get_openpose_keypoints, map_crop_kpts_to_frame
            from runtime.utils.tubelet_builder import build_tubelets
            from seizure_classifier.models import vivit_joint_tokens_forward_chunked

            cap = cv2.VideoCapture(self.source)
            if not cap.isOpened():
                session_log(f"Could not open source {self.source}")
                try:
                    pipe.close()
                except Exception:
                    pass
                return

            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            sample_fps = 6.0
            vsvig_sample_step = max(1, int(round(fps / sample_fps)))
            frame_idx = 0
            seg_frames = []
            
            total_vivit_ms = 0.0
            count_vivit = 0
            
            while not self._stop_event.is_set():
                if getattr(self, "trigger_reset", False):
                    self.trigger_reset = False
                    import struct
                    payload = struct.pack("4s d d d", b"RSET", 0.0, 0.0, 0.0)
                    payload += b"\x00" * (14 * 768 * 4)  # tokens
                    payload += b"\x00" * (14 * 30 * 3 * 4)  # pos
                    try:
                        pipe.write(payload)
                        pipe.flush()
                        session_log("Wrote RSET command to pipe")
                    except Exception as e:
                        session_log(f"Pipe reset write failed: {e}")

                ok, frame = cap.read()
                if not ok:
                    break
                frame_idx += 1
                time_sec = frame_idx / fps

                if frame_idx % vsvig_sample_step == 0:
                    crop_kpts = get_openpose_keypoints(pose_model, frame, device)
                    kpts18 = map_crop_kpts_to_frame(crop_kpts, (0, 0, frame.shape[1], frame.shape[0])).astype(np.float32)
                    seg_frames.append({
                        "frame": frame.copy(),
                        "skeleton": {"keypoints": kpts18},
                        "t": time_sec
                    })

                if len(seg_frames) >= 30:
                    segment = seg_frames[:30]
                    slide_sec = 5.0
                    slide_samples = max(1, int(round(max(slide_sec, 1.0 / max(sample_fps, 0.1)) * sample_fps)))
                    seg_frames = seg_frames[slide_samples:]
                    
                    session_log(f"Processing segment at {time_sec:.2f}s slide={slide_sec:.2f}s")
                    t0_build = time.perf_counter()
                    tubelets, pos = build_tubelets(segment, n_joints=14, patch_size=120, sample_fps=sample_fps)
                    t1_build = time.perf_counter()
                    token_build_ms = (t1_build - t0_build) * 1000.0
                    
                    with torch.no_grad(), torch.autocast(device_type=str(device), enabled=(str(device) == "cuda"), dtype=torch.float16):
                        tubelets = tubelets.to(device)
                        pos = pos.to(device)
                        
                        t0_vivit = time.time()
                        tokens = vivit_joint_tokens_forward_chunked(
                            tubelets=tubelets,
                            vivit_model=vivit_model,
                            num_frames=32,
                            out_size=224,
                            pool="cls",
                            enforce_model_num_frames=True,
                            joint_chunk=14,
                            move_chunk_to_device=True,
                        )
                        t1_vivit = time.time()
                        total_vivit_ms += (t1_vivit - t0_vivit) * 1000.0
                        count_vivit += 1
                        
                    tokens_np = tokens.cpu().numpy().astype(np.float32)
                    pos_np = pos.cpu().numpy().astype(np.float32)

                    vivit_ms = (t1_vivit - t0_vivit) * 1000.0
                    payload = struct.pack("4s d d d", b"VIVT", time_sec, token_build_ms, vivit_ms)
                    payload += tokens_np.tobytes()
                    payload += pos_np.tobytes()
                    
                    try:
                        pipe.write(payload)
                        pipe.flush()
                        session_log(f"Wrote {len(payload)} bytes to pipe")
                    except Exception as e:
                        session_log(f"Pipe write failed: {e}")
                        break

            session_log("--- PROFILING PYTHON THREAD ---")
            session_log(f"ViViT mean: {(total_vivit_ms / count_vivit if count_vivit > 0 else 0.0):.2f} ms")
            cap.release()
        except Exception as e:
            session_log(f"Error in token producer thread: {e}")
            import traceback
            tb_str = traceback.format_exc()
            if self.py_stderr_file:
                try:
                    self.py_stderr_file.write(tb_str)
                    self.py_stderr_file.flush()
                except Exception:
                    pass
        finally:
            try:
                pipe.close()
            except Exception:
                pass
            session_log("Token producer thread finished.")

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

        with open(self.alert_log, "r", newline="", encoding="utf-8") as fh:
            # Read header
            header_line = fh.readline()
            while not header_line and not self._stop_event.is_set():
                time.sleep(0.1)
                header_line = fh.readline()
                
            if self._stop_event.is_set():
                return
                
            import csv
            headers = list(csv.reader([header_line.strip()]))[0]
            
            # Tail new lines
            buffer = ""
            while not self._stop_event.is_set():
                line = fh.readline()
                if not line:
                    time.sleep(0.1)
                    continue
                
                buffer += line
                if not buffer.endswith("\n"):
                    continue
                
                parsed_line = buffer.strip()
                buffer = ""
                
                if parsed_line:
                    row_values = list(csv.reader([parsed_line]))[0]
                    row = dict(zip(headers, row_values))
                    event = _csv_row_to_event(row)
                    
                    if self.latch_override:
                        if event.get("status") == "SEIZURE" or event.get("alert_latched"):
                            event["status"] = "NORMAL"
                            event["alert"] = False
                            event["alert_latched"] = False
                        else:
                            self.latch_override = False

                    if event.get("status") != "INITIALISING":
                        self.ready = True
                    event["ready"] = self.ready

                    if event.get("alert_latched"):
                        if not self.latch_start_time:
                            self.latch_start_time = event.get("time_sec") or time.time()
                    else:
                        self.latch_start_time = None
                    event["latch_start_time"] = self.latch_start_time

                    self.last_event = event
                    asyncio.run_coroutine_threadsafe(
                        self._broadcast(event), _event_loop
                    )

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
        "ready":          row.get("status", "INITIALISING") != "INITIALISING",
        "timestamp":      time.time(),
    }


# ── Active sessions + event loop reference ───────────────────────────────────
_sessions: dict[str, SeizureSession] = {}
_event_loop: asyncio.AbstractEventLoop


async def _run_background_warmup():
    log.info("Starting background model warm-up...")
    sample_video = REPO_ROOT / "sample_videos" / "pat10_Sz1P_demo_good.mp4"
    if not sample_video.exists():
        videos = list((REPO_ROOT / "sample_videos").glob("*.mp4"))
        if videos:
            sample_video = videos[0]
        else:
            log.warning("No sample video found for warm-up.")
            return

    session = SeizureSession("warmup", str(sample_video), "monitor", "")
    try:
        session.start()
        # Let it run for 10 seconds to compile engines and initialize CUDA
        await asyncio.sleep(10)
    except Exception as e:
        log.warning(f"Warm-up failed: {e}")
    finally:
        session.stop()
        log.info("Background model warm-up complete and ready.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _event_loop
    _event_loop = asyncio.get_event_loop()
    log.info("Seizure detection service started.")
    
    # Preload global PyTorch models
    load_global_models()
    
    # Warm up ONNX C++ engine
    asyncio.create_task(_run_background_warmup())
    yield
    log.info("Shutting down; stopping all sessions.")
    for s in list(_sessions.values()):
        s.stop()


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Seizure Detection Service",
    description="Real-time VSViG + Cross-Joint seizure monitoring via native subprocesses.",
    version="2.0.0",
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
    alive: bool
    created_at: float
    clients:    int
    ready:      bool = False


@app.get("/health")
def health():
    alive = sum(1 for s in _sessions.values() if s.is_alive())
    return {"status": "ok", "active_sessions": len(_sessions), "alive_processes": alive}


@app.post("/sessions", response_model=SessionInfo)
def start_session(req: StartSessionRequest):
    """Start a new seizure monitoring session for a patient room/camera."""
    if req.session_id in _sessions:
        s = _sessions[req.session_id]
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


@app.post("/sessions/{session_id}/reset-latch")
def reset_seizure_latch(session_id: str):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    session = _sessions[session_id]
    session.latch_override = True
    session.trigger_reset = True
    session.latch_start_time = None
    log.info(f"Seizure latch override enabled for session={session_id}")
    return {"status": "success", "session_id": session_id}


@app.get("/sessions", response_model=list[SessionInfo])
def list_sessions():
    return [_session_info(s) for s in _sessions.values()]


@app.websocket("/ws/{session_id}")
async def ws_session(websocket: WebSocket, session_id: str):
    """
    Subscribe to real-time seizure events for an active session.
    """
    if session_id not in _sessions:
        await websocket.close(code=4004, reason="Session not found — start it via POST /sessions first")
        return

    session = _sessions[session_id]
    await websocket.accept()
    session.clients.append(websocket)
    log.info(f"Client subscribed: session={session_id} total_clients={len(session.clients)}")

    if session.last_event:
        await websocket.send_json(session.last_event)

    try:
        while True:
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
        ready=s.ready,
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8003))
    uvicorn.run("service:app", host="0.0.0.0", port=port, reload=False)
