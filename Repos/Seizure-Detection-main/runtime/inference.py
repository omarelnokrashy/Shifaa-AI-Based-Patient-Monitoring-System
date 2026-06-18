"""
Seizure-only real-time monitoring pipeline.

Stages:
  1. Direct patient crop from the full frame or an optional bed ROI.
  2. Lightweight OpenPose-18 keypoint extraction.
  3. VSViG patch/AP scoring.
  4. Optional async Cross-Joint worker.
  5. Series gate for final NORMAL / SEIZURE rendering.
"""

from __future__ import annotations

import csv
import contextlib
import json
import os
import queue
import sys
import threading
import time
import warnings
from collections import deque
from dataclasses import dataclass, field

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import cv2
import numpy as np
import torch

from runtime.models.vsvig import VSViG_ProtoGCN_base, VSViG_base
from runtime.utils.patches import extract_patches_from_context, prepare_patch_context
from runtime.utils.paths import resolve_path

pose_repo_path = resolve_path(os.environ.get("POSE_REPO", "vendor/lightweight-human-pose-estimation.pytorch"))
if str(pose_repo_path) not in sys.path:
    sys.path.insert(0, str(pose_repo_path))
from models.with_mobilenet import PoseEstimationWithMobileNet
from modules.load_state import load_state


VIDEO_PATH = "dataset/VSVIG_Data/pat03/Sz1PG.mp4"
OUTPUT_PATH = "output_inference.avi"

MODEL_WEIGHTS = "weights/vsvig/model_paper_finetuned.pth"
POSE_WEIGHTS = "weights/pose/pose.pth"
DY_POINT_ORDER = str(resolve_path(os.environ.get("DY_POINT_ORDER", "model_weights/dy_point_order.pt")))
USE_PROTO_GCN = True
USE_AMP = os.environ.get("USE_AMP", "1") == "1"
CJ_USE_AMP = os.environ.get("CJ_USE_AMP", "1") == "1"
POSE_USE_AMP = os.environ.get("POSE_USE_AMP", "1") == "1"
CUDA_STREAMS = os.environ.get("CUDA_STREAMS", "1") == "1"
FAST_SKIP_DECODE = os.environ.get("FAST_SKIP_DECODE", "0") == "1"
ASYNC_ALERT_LOG = os.environ.get("ASYNC_ALERT_LOG", "1") == "1"
PROFILE_PIPELINE = os.environ.get("PROFILE_PIPELINE", "0") == "1"
PROFILE_EVERY = int(os.environ.get("PROFILE_EVERY", "100"))
PROFILE_OUT = os.environ.get("PROFILE_OUT", "")
MAX_FRAMES = int(os.environ.get("MAX_FRAMES", "0") or "0")
DISPLAY_UI = os.environ.get("DISPLAY_UI", "1") == "1"
BED_ROI_RAW = os.environ.get("BED_ROI", "").strip()
ALERT_LOG = os.environ.get("ALERT_LOG", "").strip()
WRITE_OUTPUT = os.environ.get("WRITE_OUTPUT", "1") == "1"
PATIENT_BRANCH_FPS = float(os.environ.get("PATIENT_BRANCH_FPS", "5.0"))

WINDOW_FRAMES = 30
INFERENCE_STRIDE = 15
AP_BUFFER_SIZE = 6
AP_WINDOW_SEC = float(os.environ.get("AP_WINDOW_SEC", "3.0"))
SEIZURE_THRESHOLDS = {
    "safety": 0.88,
    "monitor": 0.49,
    "screening": 0.12,
}
ALERT_MODE = os.environ.get("ALERT_MODE", "monitor").strip().lower()
if ALERT_MODE not in SEIZURE_THRESHOLDS:
    print(f"[WARN] Unknown ALERT_MODE={ALERT_MODE!r}; using 'monitor'.")
    ALERT_MODE = "monitor"
SEIZURE_DT = float(os.environ.get("SEIZURE_DT", SEIZURE_THRESHOLDS[ALERT_MODE]))

ENABLE_CJ_ASYNC = os.environ.get("ENABLE_CJ_ASYNC", "1") == "1"
ENABLE_LIVE_VSVIG = os.environ.get("ENABLE_LIVE_VSVIG", "1") == "1"
CJ_CHECKPOINT = os.environ.get(
    "CJ_CHECKPOINT",
    (
        "weights/cross_joint/checkpoints/cj_fullfit_distilled_w0p5_seed123.pt,"
        "weights/cross_joint/checkpoints/cj_fullfit_distilled_w0p5_seed789.pt"
    ),
)
CJ_PAPER_REPO = os.environ.get("CJ_PAPER_REPO", "vendor/joint-attention-seizure-detection")
CJ_GATE_MODE = os.environ.get("CJ_GATE_MODE", "blend_if_suspicious").strip().lower()
CJ_GATE = float(os.environ.get("CJ_GATE", "0.20"))
CJ_THRESHOLD = float(os.environ.get("CJ_THRESHOLD", "0.49451708793640137"))
CJ_ALPHA = float(os.environ.get("CJ_ALPHA", "0.30"))
CJ_SAMPLE_FPS = float(os.environ.get("CJ_SAMPLE_FPS", "6.0"))
CJ_PATCH_SIZE = int(os.environ.get("CJ_PATCH_SIZE", "120"))
CJ_MAX_RESULT_AGE_SEC = float(os.environ.get("CJ_MAX_RESULT_AGE_SEC", "15.0"))
CJ_ALERT_MAX_RESULT_AGE_SEC = float(os.environ.get("CJ_ALERT_MAX_RESULT_AGE_SEC", "60.0"))
SEIZURE_ALERT_HOLD_SEC = float(os.environ.get("SEIZURE_ALERT_HOLD_SEC", "30.0"))
POSE_CONFIDENCE_GATE = float(os.environ.get("POSE_CONFIDENCE_GATE", "0.10"))
POSE_REUSE_MAX_SEC = float(os.environ.get("POSE_REUSE_MAX_SEC", "10.0"))

_MODEL_CACHE_LOCK = threading.Lock()
_CJ_MODEL_LOAD_LOCK = threading.Lock()
_POSE_MODEL_CACHE: dict[tuple[str, str], torch.nn.Module] = {}
_VSVIG_MODEL_CACHE: dict[tuple[str, str, bool], torch.nn.Module] = {}
_CJ_MODEL_CACHE: dict[tuple[tuple[str, ...], str, str], tuple] = {}
_CUDA_STREAM_CACHE: dict[tuple[str, str], torch.cuda.Stream] = {}

TRACK_MAX_AGE_FRAMES = 150
STATE_COLORS = {
    "NORMAL": (0, 220, 0),
    "SEIZURE": (0, 0, 255),
    "INITIALISING": (0, 200, 255),
}


def get_cuda_stream(name: str, device: torch.device):
    if not CUDA_STREAMS or device.type != "cuda":
        return None
    key = (name, str(device))
    with _MODEL_CACHE_LOCK:
        stream = _CUDA_STREAM_CACHE.get(key)
        if stream is None:
            stream = torch.cuda.Stream(device=device)
            _CUDA_STREAM_CACHE[key] = stream
    return stream


@contextlib.contextmanager
def cuda_stream_context(name: str, device: torch.device):
    stream = get_cuda_stream(name, device)
    if stream is None:
        yield None
        return
    with torch.cuda.stream(stream):
        yield stream


class Profiler:
    def __init__(self, enabled: bool, every: int = 100):
        self.enabled = enabled
        self.every = max(1, every)
        self.samples: dict[str, list[float]] = {}
        self.frame_n = 0
        self.started_at = time.perf_counter()

    def add(self, name: str, elapsed_ms: float):
        if self.enabled:
            self.samples.setdefault(name, []).append(float(elapsed_ms))

    def tick(self):
        if not self.enabled:
            return
        self.frame_n += 1
        if self.frame_n % self.every:
            return
        print("\n[PROFILE] mean latency over recent samples")
        for name, vals in sorted(self.samples.items()):
            arr = np.asarray(vals[-self.every:], dtype=np.float32)
            if arr.size:
                print(f"  {name:24s} {arr.mean():7.2f} ms +/- {arr.std():5.2f}")
        frame_vals = self.samples.get("frame_total", [])
        if frame_vals:
            arr = np.asarray(frame_vals[-self.every:], dtype=np.float32)
            fps = 1000.0 / max(float(arr.mean()), 1e-6)
            verdict = "REAL-TIME" if fps >= 15.0 else "BELOW 15 FPS"
            print(f"  {'effective_fps':24s} {fps:7.2f} fps  {verdict}")

    def summary(self, target_fps: float = 15.0):
        elapsed = max(time.perf_counter() - self.started_at, 1e-6)
        frame_vals = self.samples.get("frame_total", [])
        frame_count = len(frame_vals)
        out = {
            "frame_count": frame_count,
            "wall_time_sec": elapsed,
            "wall_fps": frame_count / elapsed if frame_count else 0.0,
            "target_fps": target_fps,
            "target_ms_per_frame": 1000.0 / target_fps,
            "components": {},
        }
        for name, vals in sorted(self.samples.items()):
            arr = np.asarray(vals, dtype=np.float32)
            if not arr.size:
                continue
            out["components"][name] = {
                "count": int(arr.size),
                "mean_ms": float(arr.mean()),
                "std_ms": float(arr.std()),
                "p95_ms": float(np.percentile(arr, 95)),
                "max_ms": float(arr.max()),
            }
        if frame_vals:
            mean_ms = out["components"]["frame_total"]["mean_ms"]
            out["effective_fps"] = 1000.0 / max(mean_ms, 1e-6)
            out["real_time_15fps"] = out["effective_fps"] >= target_fps
        else:
            out["effective_fps"] = 0.0
            out["real_time_15fps"] = False
        return out

    def print_summary(self):
        if not self.enabled:
            return
        summary = self.summary()
        print("\n[PROFILE SUMMARY]")
        print(
            f"  frames={summary['frame_count']}  "
            f"effective_fps={summary['effective_fps']:.2f}  "
            f"wall_fps={summary['wall_fps']:.2f}  "
            f"target=15.00 fps  "
            f"verdict={'REAL-TIME' if summary['real_time_15fps'] else 'BELOW TARGET'}"
        )
        for name, stats in summary["components"].items():
            print(
                f"  {name:24s} mean={stats['mean_ms']:8.2f} ms  "
                f"p95={stats['p95_ms']:8.2f} ms  count={stats['count']}"
            )
        if PROFILE_OUT:
            out_path = os.path.abspath(PROFILE_OUT)
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
            print(f"  wrote profile JSON: {out_path}")


class Timer:
    def __init__(self, profiler: Profiler, name: str):
        self.profiler = profiler
        self.name = name
        self.t0 = 0.0

    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.profiler.add(self.name, (time.perf_counter() - self.t0) * 1000.0)


class AlertCsvLogger:
    def __init__(self, path: str, fieldnames: list[str], async_enabled: bool = True):
        self.path = os.path.abspath(path)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._file = open(self.path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=fieldnames)
        self._writer.writeheader()
        self._async_enabled = bool(async_enabled)
        self._queue: queue.Queue | None = None
        self._thread: threading.Thread | None = None
        if self._async_enabled:
            self._queue = queue.Queue(maxsize=8192)
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    @property
    def async_enabled(self) -> bool:
        return self._async_enabled

    def _run(self):
        assert self._queue is not None
        while True:
            row = self._queue.get()
            if row is None:
                break
            self._writer.writerow(row)

    def writerow(self, row: dict):
        if self._queue is None:
            self._writer.writerow(row)
            return
        self._queue.put(row)

    def close(self):
        if self._queue is not None:
            self._queue.put(None)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._file.flush()
        self._file.close()


def finite_score(value, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if np.isfinite(out) else default


def series_gate_signal(
    cj_prob: float | None,
    vsvig_ap: float | None,
    cj_age_sec: float | None,
    alert_active: bool = False,
):
    if cj_prob is not None and not np.isfinite(cj_prob):
        cj_prob = None
    if vsvig_ap is not None and not np.isfinite(vsvig_ap):
        vsvig_ap = None
    max_age = CJ_ALERT_MAX_RESULT_AGE_SEC if alert_active else CJ_MAX_RESULT_AGE_SEC
    if cj_prob is None or cj_age_sec is None or cj_age_sec > max_age:
        if vsvig_ap is None:
            return 0.0, "CJ_PENDING"
        return finite_score(vsvig_ap), "CJ_PENDING" if cj_prob is None else "VSViG_AP"
    if vsvig_ap is None:
        return finite_score(cj_prob), "CJ"

    if cj_prob >= 0.50:
        return finite_score(cj_prob), "CJ"
    if cj_prob >= CJ_GATE:
        score = CJ_ALPHA * cj_prob + (1.0 - CJ_ALPHA) * vsvig_ap
        score = max(0.0, float(score))
        if score >= CJ_THRESHOLD:
            return score, "BLEND"
        return score, "CJ_LOW"

    return finite_score(cj_prob), "CJ_LOW"


def build_cj_tubelets(frames_bgr: list[np.ndarray], kpts_seq: list[np.ndarray], patch_size: int = CJ_PATCH_SIZE):
    """
    Build Cross-Joint tubelets with the paper repo crop/tokenizer path while
    reusing OpenPose keypoints already computed by the live main loop.
    """
    cj_repo = resolve_path(CJ_PAPER_REPO)
    if str(cj_repo) not in sys.path:
        sys.path.insert(0, str(cj_repo))
    from seizure_classifier.pose import build_joint_tubelets_from_poses

    class _Pose:
        __slots__ = ("keypoints",)

        def __init__(self, kpts18: np.ndarray):
            coords = np.asarray(kpts18, dtype=np.float32)[:, :2].copy()
            conf = np.asarray(kpts18, dtype=np.float32)[:, 2]
            coords[(~np.isfinite(coords).all(axis=1)) | (conf <= 0.0)] = -1.0
            self.keypoints = coords

    frames_rgb = np.stack(
        [cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) for frame in frames_bgr],
        axis=0,
    ).astype(np.uint8)
    poses = [_Pose(kpts18) for kpts18 in kpts_seq]
    return build_joint_tubelets_from_poses(frames_rgb, poses, P=patch_size)


class AsyncCrossJointWorker:
    def __init__(self, checkpoint: str, paper_repo: str, device: torch.device):
        self.checkpoints = [p.strip() for p in checkpoint.split(",") if p.strip()]
        self.checkpoint = ",".join(self.checkpoints)
        self.paper_repo = paper_repo
        self.device = device
        self.jobs: queue.Queue = queue.Queue(maxsize=1)
        self.results: dict[int, dict] = {}
        self.enabled = ENABLE_CJ_ASYNC
        self._stop_event = threading.Event()
        self.thread = None
        if self.enabled:
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
            print("Async Cross-Joint worker enabled.")

    def submit(self, track_id: int, frames_bgr: list[np.ndarray], kpts_seq: list[np.ndarray]):
        if not self.enabled:
            return
        item = (track_id, [f.copy() for f in frames_bgr], [k.copy() for k in kpts_seq])
        try:
            self.jobs.put_nowait(item)
        except queue.Full:
            pass

    def stop(self):
        if not self.enabled:
            return
        self._stop_event.set()
        try:
            self.jobs.put_nowait(None)
        except queue.Full:
            pass
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=2.0)

    def latest(self, track_id: int):
        result = self.results.get(track_id)
        if not result:
            return None, None
        return float(result["prob"]), time.time() - float(result["time"])

    def _load_models(self):
        with _CJ_MODEL_LOAD_LOCK:
            paper_repo = resolve_path(self.paper_repo)
            cache_key = (tuple(os.path.abspath(p) for p in self.checkpoints), str(paper_repo), str(self.device))
            with _MODEL_CACHE_LOCK:
                cached = _CJ_MODEL_CACHE.get(cache_key)
            if cached is not None:
                print(f"Async Cross-Joint reused cached model(s): {self.checkpoint}")
                return cached

            if str(paper_repo) not in sys.path:
                sys.path.insert(0, str(paper_repo))
            from seizure_classifier.models import (
                JointTransformerClassifier,
                VivitModel,
                compute_joint_padding_mask,
                vivit_joint_tokens_forward_chunked,
            )
            if not self.checkpoints:
                raise ValueError("No Cross-Joint checkpoints configured.")
            ckpts = [torch.load(path, map_location=self.device, weights_only=False) for path in self.checkpoints]
            vivit = VivitModel.from_pretrained(
                "google/vivit-b-16x2-kinetics400",
                local_files_only=True,
                use_safetensors=False,
            ).to(self.device).eval()
            heads = []
            for ckpt in ckpts:
                head = JointTransformerClassifier(
                    token_dim=int(vivit.config.hidden_size),
                    d_model=256,
                    nhead=8,
                    num_layers=4,
                    dropout=0.5,
                    use_cls_token=bool(ckpt.get("use_cls_token", False)),
                ).to(self.device).eval()
                head.load_state_dict(ckpt["model"])
                heads.append(head)
            print(f"Async Cross-Joint loaded {len(heads)} head(s): {self.checkpoint}")
            loaded = (vivit, heads, vivit_joint_tokens_forward_chunked, compute_joint_padding_mask)
            with _MODEL_CACHE_LOCK:
                _CJ_MODEL_CACHE[cache_key] = loaded
            return loaded

    def _run(self):
        try:
            vivit, heads, token_forward, padding_mask_fn = self._load_models()
        except Exception as exc:
            print(f"[WARN] Async Cross-Joint worker disabled: {exc}")
            self.enabled = False
            return
        while not self._stop_event.is_set():
            item = self.jobs.get()
            if item is None:
                break
            track_id, frames, kpts = item
            try:
                tubelets, pos = build_cj_tubelets(frames, kpts)
                with cuda_stream_context("cj", self.device):
                    tube_t = torch.tensor(tubelets, dtype=torch.float32).unsqueeze(0).to(self.device)
                    pos_t = torch.tensor(pos, dtype=torch.float32).unsqueeze(0).to(self.device)
                    with torch.no_grad(), torch.autocast(
                        device_type=self.device.type,
                        enabled=(CJ_USE_AMP and self.device.type == "cuda"),
                        dtype=torch.float16,
                    ):
                        tokens = token_forward(
                            tubelets=tube_t,
                            vivit_model=vivit,
                            num_frames=32,
                            out_size=224,
                            pool="cls",
                            enforce_model_num_frames=True,
                            joint_chunk=14,
                            move_chunk_to_device=True,
                        )
                        mask = padding_mask_fn(pos_t)
                        logits = torch.stack([head(tokens, pos_t, joint_padding_mask=mask).reshape(()) for head in heads])
                        prob = torch.sigmoid(logits.mean()).item()
                self.results[track_id] = {"prob": float(prob), "time": time.time()}
            except Exception as exc:
                print(f"[WARN] Async Cross-Joint job failed for patient: {exc}")


def load_pose_model(weights_path: str, device: torch.device):
    cache_key = (os.path.abspath(str(weights_path)), str(device))
    with _MODEL_CACHE_LOCK:
        cached = _POSE_MODEL_CACHE.get(cache_key)
    if cached is not None:
        print(f"Reusing cached pose model: {weights_path}")
        return cached
    net = PoseEstimationWithMobileNet()
    load_state(net, torch.load(weights_path, map_location="cpu"))
    net = net.to(device).eval()
    with _MODEL_CACHE_LOCK:
        _POSE_MODEL_CACHE[cache_key] = net
    return net


def load_seizure_model(weights_path: str, device: torch.device):
    cache_key = (os.path.abspath(str(weights_path)), str(device), bool(USE_PROTO_GCN))
    with _MODEL_CACHE_LOCK:
        cached = _VSVIG_MODEL_CACHE.get(cache_key)
    if cached is not None:
        print(f"Reusing cached VSViG model: {weights_path}")
        return cached
    model = VSViG_ProtoGCN_base() if USE_PROTO_GCN else VSViG_base()
    model.load_state_dict(torch.load(weights_path, map_location=device, weights_only=False))
    model = model.to(device).eval()
    with _MODEL_CACHE_LOCK:
        _VSVIG_MODEL_CACHE[cache_key] = model
    return model


def get_openpose_keypoints(net, img: np.ndarray, device: torch.device) -> np.ndarray:
    if img.size == 0:
        return np.zeros((18, 3), dtype=np.float32)

    h, w = img.shape[:2]
    if h < 4 or w < 4:
        return np.zeros((18, 3), dtype=np.float32)

    sc = 256 / h
    resized_w = max(1, int(round(w * sc)))
    resized_h = max(1, int(round(h * sc)))
    t = (
        torch.from_numpy(cv2.resize(img, (resized_w, resized_h)))
        .permute(2, 0, 1)
        .unsqueeze(0)
        .float()
        / 128.0
        - 1.0
    ).to(device)

    with cuda_stream_context("main", device):
        with torch.no_grad(), torch.autocast(
            device_type=device.type,
            enabled=(POSE_USE_AMP and device.type == "cuda"),
            dtype=torch.float16,
        ):
            stages = net(t)

    hm = np.transpose(stages[-2].squeeze().float().cpu().numpy(), (1, 2, 0))
    if hm.size == 0 or hm.shape[0] < 1 or hm.shape[1] < 1:
        return np.zeros((18, 3), dtype=np.float32)
    hm_w = max(1, int(round(w / 8.0)))
    hm_h = max(1, int(round(h / 8.0)))
    hm = cv2.resize(hm, (hm_w, hm_h), interpolation=cv2.INTER_CUBIC)

    kpts = np.zeros((18, 3), dtype=np.float32)
    for i in range(18):
        h2 = hm[:, :, i]
        h2[h2 < 0.1] = 0
        pad = np.pad(h2, [(2, 2), (2, 2)], mode="constant")
        c = pad[1:-1, 1:-1]
        pk = (
            (c > pad[1:-1, 2:])
            & (c > pad[1:-1, :-2])
            & (c > pad[2:, 1:-1])
            & (c > pad[:-2, 1:-1])
        )[1:-1, 1:-1]
        ys, xs = np.nonzero(pk)
        if len(ys):
            b = int(np.argmax(h2[ys, xs]))
            xc, yc = xs[b], ys[b]
            kpts[i] = (xc, yc, h2[yc, xc])
    return kpts


def clamp_box(box, width: int, height: int):
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    x1 = max(0, min(x1, width - 1))
    y1 = max(0, min(y1, height - 1))
    x2 = max(x1 + 1, min(x2, width))
    y2 = max(y1 + 1, min(y2, height))
    return x1, y1, x2, y2


def parse_bed_roi(raw: str, width: int, height: int):
    if not raw:
        return None
    try:
        vals = [float(v.strip()) for v in raw.split(",")]
    except ValueError:
        print(f"[WARN] Invalid BED_ROI={raw!r}; ignoring.")
        return None
    if len(vals) != 4:
        print(f"[WARN] BED_ROI must be x1,y1,x2,y2; got {raw!r}; ignoring.")
        return None
    x1, y1, x2, y2 = vals
    if max(vals) <= 1.0:
        x1, x2 = x1 * width, x2 * width
        y1, y2 = y1 * height, y2 * height
    x1, y1, x2, y2 = clamp_box((x1, y1, x2, y2), width, height)
    if x2 <= x1 or y2 <= y1:
        print(f"[WARN] Empty BED_ROI={raw!r}; ignoring.")
        return None
    return x1, y1, x2, y2


def map_crop_kpts_to_frame(kpts: np.ndarray, box) -> np.ndarray:
    x1, y1, _, _ = box
    mapped = kpts.copy()
    mapped[:, 0] = mapped[:, 0] * 8.0 + x1
    mapped[:, 1] = mapped[:, 1] * 8.0 + y1
    return mapped


def pose_confidence_mean(kpts: np.ndarray) -> float:
    if kpts is None or not len(kpts):
        return 0.0
    conf = np.asarray(kpts, dtype=np.float32)[:, 2]
    conf = conf[np.isfinite(conf)]
    if conf.size == 0:
        return 0.0
    return float(np.mean(conf))


def reorder_kpts_for_vsvig(kpts_buf):
    tk = torch.tensor(np.array(kpts_buf), dtype=torch.float32).unsqueeze(0)
    raw = list(np.arange(18))
    new = [0, -3, -4] + list(np.arange(12) + 2) + [1, -1, -2]
    tk[:, :, raw, :] = tk[:, :, new, :]
    return tk[:, :, :15, :]


def draw_skeleton(frame, kpts):
    skeleton = [
        (0, 1), (1, 2), (2, 3), (3, 4), (1, 5), (5, 6), (6, 7),
        (1, 14), (14, 8), (8, 9), (9, 10), (14, 11), (11, 12), (12, 13),
    ]
    for x, y, c in kpts:
        if c > 0.1 and np.isfinite(x) and np.isfinite(y):
            cv2.circle(frame, (int(x), int(y)), 4, (0, 255, 255), -1)
    for a, b in skeleton:
        if kpts[a, 2] > 0.1 and kpts[b, 2] > 0.1:
            ax, ay = int(kpts[a, 0]), int(kpts[a, 1])
            bx, by = int(kpts[b, 0]), int(kpts[b, 1])
            cv2.line(frame, (ax, ay), (bx, by), (0, 180, 255), 2)


@dataclass
class TrackState:
    kpts_buf: deque = field(default_factory=lambda: deque(maxlen=WINDOW_FRAMES))
    patches_buf: deque = field(default_factory=lambda: deque(maxlen=WINDOW_FRAMES))
    risk_buf: deque = field(default_factory=deque)
    cj_frames_buf: deque = field(default_factory=lambda: deque(maxlen=30))
    cj_kpts_buf: deque = field(default_factory=lambda: deque(maxlen=30))
    current_risk: float = 0.0
    ap_sum: float = 0.0
    cj_prob: float | None = None
    cj_age_sec: float | None = None
    seizure_signal: float = 0.0
    seizure_source: str = "VSViG"
    status: str = "NORMAL"
    last_seen: int = 0
    last_kpts18: np.ndarray | None = None
    last_kpts_frame: int = 0
    last_valid_kpts18: np.ndarray | None = None
    last_valid_kpts_frame: int = 0
    last_pose_conf_mean: float = 0.0
    pose_source: str = "none"
    alert_hold_until_frame: int = 0
    alert_latched: bool = False


def resolve_status(seizure_signal: float):
    threshold = CJ_THRESHOLD if ENABLE_CJ_ASYNC else SEIZURE_DT
    return "SEIZURE" if seizure_signal >= threshold else "NORMAL"


def update_ap_sum(state: TrackState, now_sec: float) -> float:
    while state.risk_buf and now_sec - state.risk_buf[0][0] >= AP_WINDOW_SEC:
        state.risk_buf.popleft()
    return finite_score(sum(finite_score(v) for _, v in state.risk_buf))


def both_models_waiting_for_clip(state: TrackState, live_vsvig_enabled: bool) -> bool:
    vsvig_waiting = live_vsvig_enabled and len(state.risk_buf) == 0
    cj_waiting = ENABLE_CJ_ASYNC and state.cj_prob is None
    return vsvig_waiting and cj_waiting


def apply_alert_latch(state: TrackState, frame_n: int, fps: float):
    threshold = CJ_THRESHOLD if ENABLE_CJ_ASYNC else SEIZURE_DT
    raw_status = resolve_status(state.seizure_signal)
    hold_frames = int(round(max(0.0, SEIZURE_ALERT_HOLD_SEC) * max(float(fps), 1.0)))
    state.alert_latched = False
    if raw_status == "SEIZURE":
        state.alert_hold_until_frame = max(state.alert_hold_until_frame, frame_n + hold_frames)
        state.status = "SEIZURE"
        state.alert_latched = frame_n <= state.alert_hold_until_frame
        return
    if frame_n <= state.alert_hold_until_frame:
        state.status = "SEIZURE"
        state.alert_latched = True
        state.seizure_signal = max(finite_score(state.seizure_signal), threshold)
        if not state.seizure_source.startswith("LATCH"):
            state.seizure_source = f"LATCH/{state.seizure_source}"
        return
    state.status = raw_status


def render_patient(frame, box, state: TrackState):
    color = STATE_COLORS.get(state.status, STATE_COLORS["NORMAL"])
    x1, y1, x2, y2 = box
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)


def render_summary(frame, state: TrackState):
    color = STATE_COLORS.get(state.status, STATE_COLORS["NORMAL"])
    h, w = frame.shape[:2]
    panel_w = min(max(430, int(w * 0.28)), max(1, w - 20))
    panel_h = 142
    x0, y0 = 10, 10
    x1, y1 = x0 + panel_w, min(y0 + panel_h, h - 10)
    overlay = frame.copy()
    cv2.rectangle(overlay, (x0, y0), (x1, y1), (12, 12, 12), -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)
    cv2.rectangle(frame, (x0, y0), (x1, y1), color, 2)

    labels = [
        ("Clinical mode", ALERT_MODE.upper(), (220, 220, 220)),
        ("Status", state.status, color),
        ("Seizure signal", f"{finite_score(state.seizure_signal):.3f}", (235, 235, 235)),
        ("Source", str(state.seizure_source or "NA"), (210, 210, 210)),
    ]
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.58 if panel_w < 500 else 0.64
    label_color = (155, 155, 155)
    row_y = y0 + 31
    row_gap = 31
    label_x = x0 + 14
    value_x = x0 + min(178, max(132, panel_w // 3))
    max_value_px = max(60, x1 - value_x - 12)

    for label, value, value_color in labels:
        full_value = str(value)
        value = full_value
        while value and cv2.getTextSize(value, font, font_scale, 2)[0][0] > max_value_px:
            value = value[:-1]
        if value != full_value and len(value) > 3:
            value = value[:-3] + "..."
        cv2.putText(frame, f"{label}:", (label_x, row_y), font, font_scale, label_color, 1, cv2.LINE_AA)
        cv2.putText(frame, value, (value_x, row_y), font, font_scale, value_color, 2, cv2.LINE_AA)
        row_y += row_gap


def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    profiler = Profiler(PROFILE_PIPELINE, PROFILE_EVERY)
    print(f"Inference on {device}")
    print(
        f"AP strategy: {AP_WINDOW_SEC:.1f}s time window, VSViG stride={INFERENCE_STRIDE} frames, "
        f"mode={ALERT_MODE}, seizure DT={SEIZURE_DT}"
    )
    print(f"Patient branch cadence: {PATIENT_BRANCH_FPS:.2f} fps")
    if ENABLE_CJ_ASYNC:
        print(f"Series gate: CJ gate={CJ_GATE}, threshold={CJ_THRESHOLD}, alpha={CJ_ALPHA}")
        print(f"CJ AMP: {'on' if CJ_USE_AMP and device.type == 'cuda' else 'off'}")
    print(f"CUDA stream separation: {'on' if CUDA_STREAMS and device.type == 'cuda' else 'off'}")
    print(f"OpenPose AMP: {'on' if POSE_USE_AMP and device.type == 'cuda' else 'off'}")
    live_vsvig_enabled = ENABLE_LIVE_VSVIG or not ENABLE_CJ_ASYNC
    print(f"Live VSViG branch: {'on' if live_vsvig_enabled else 'off (CJ-only live mode)'}")
    effective_fast_skip = FAST_SKIP_DECODE and not DISPLAY_UI and not WRITE_OUTPUT
    print(f"Fast skip decode: {'on' if effective_fast_skip else 'off'}")

    with Timer(profiler, "load_pose"):
        pose_model = load_pose_model(POSE_WEIGHTS, device)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if os.path.exists(DY_POINT_ORDER):
            torch.load(DY_POINT_ORDER, weights_only=False)
        seizure_model = None
        if live_vsvig_enabled:
            with Timer(profiler, "load_vsvig"):
                seizure_model = load_seizure_model(MODEL_WEIGHTS, device)
    cj_worker = AsyncCrossJointWorker(CJ_CHECKPOINT, CJ_PAPER_REPO, device)

    cap = cv2.VideoCapture(VIDEO_PATH)
    if not cap.isOpened():
        raise SystemExit(f"Could not open video/camera: {VIDEO_PATH}")
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
    writer_fps = fps if fps > 0 else 30.0
    patient_branch_step = max(1, int(round(fps / max(PATIENT_BRANCH_FPS, 0.1))))
    cj_step = max(1, int(round(fps / max(CJ_SAMPLE_FPS, 0.1))))
    patient_box = parse_bed_roi(BED_ROI_RAW, width, height) or (0, 0, width, height)
    print(f"Input fps={fps:.3f}; patient branch every {patient_branch_step} frame(s)")
    if ENABLE_CJ_ASYNC:
        print(f"CJ collection every {cj_step} frame(s) ({fps / cj_step:.2f} fps effective)")
    print(f"Patient crop: {patient_box}")

    vout = cv2.VideoWriter(OUTPUT_PATH, cv2.VideoWriter_fourcc(*"XVID"), writer_fps, (width, height)) if WRITE_OUTPUT else None
    if not WRITE_OUTPUT:
        print("AVI output disabled.")

    state = TrackState()
    frame_n = 0
    alert_logger = None
    alert_fields = [
        "frame",
        "time_sec",
        "status",
        "seizure_signal",
        "seizure_source",
        "ap_sum",
        "current_risk",
        "cj_prob",
        "cj_age_sec",
        "pose_conf_mean",
        "alert_latched",
        "x1",
        "y1",
        "x2",
        "y2",
    ]
    if ALERT_LOG:
        alert_path = os.path.abspath(ALERT_LOG)
        alert_logger = AlertCsvLogger(alert_path, alert_fields, async_enabled=ASYNC_ALERT_LOG)
        print(f"Alert log: {alert_path} ({'async' if alert_logger.async_enabled else 'sync'})")

    while cap.isOpened():
        frame_t0 = time.perf_counter()
        next_frame_n = frame_n + 1
        run_patient_branch = next_frame_n % patient_branch_step == 0 or len(state.kpts_buf) == 0
        run_cj_collect = ENABLE_CJ_ASYNC and (next_frame_n % cj_step == 0 or len(state.cj_frames_buf) == 0)
        need_decode = (not effective_fast_skip) or run_patient_branch or run_cj_collect
        with Timer(profiler, "capture"):
            if need_decode:
                ret, frame = cap.read()
            else:
                ret = cap.grab()
                frame = None
        if not ret:
            break
        frame_n = next_frame_n
        disp = frame.copy() if frame is not None else None
        state.last_seen = frame_n
        x1, y1, x2, y2 = patient_box
        crop = frame[y1:y2, x1:x2] if frame is not None else None
        patch_context = None

        run_model_sample = run_cj_collect if ENABLE_CJ_ASYNC else run_patient_branch
        if run_patient_branch or run_cj_collect:
            with Timer(profiler, "openpose"):
                crop_kpts = get_openpose_keypoints(pose_model, crop, device)
            kpts18 = map_crop_kpts_to_frame(crop_kpts, patient_box)
            kpts18 = np.nan_to_num(kpts18, nan=0.0, posinf=0.0, neginf=0.0)
            state.last_pose_conf_mean = pose_confidence_mean(kpts18)
            reuse_max_frames = int(round(max(0.0, POSE_REUSE_MAX_SEC) * max(float(fps), 1.0)))
            can_reuse_pose = (
                state.last_valid_kpts18 is not None
                and frame_n - state.last_valid_kpts_frame <= reuse_max_frames
            )
            if state.last_pose_conf_mean < POSE_CONFIDENCE_GATE and can_reuse_pose:
                kpts18 = state.last_valid_kpts18.copy()
                state.pose_source = "reused_last_valid"
            else:
                state.pose_source = "openpose"
                if state.last_pose_conf_mean >= POSE_CONFIDENCE_GATE:
                    state.last_valid_kpts18 = kpts18.copy()
                    state.last_valid_kpts_frame = frame_n
            state.last_kpts18 = kpts18.copy()
            state.last_kpts_frame = frame_n

            if live_vsvig_enabled and run_model_sample:
                state.kpts_buf.append(kpts18)
                with Timer(profiler, "patches"):
                    if patch_context is None:
                        patch_context = prepare_patch_context(frame)
                    patches = extract_patches_from_context(patch_context, kpts18)
                    patches = np.nan_to_num(patches, nan=0.0, posinf=0.0, neginf=0.0)
                state.patches_buf.append(patches)
            elif run_model_sample:
                state.kpts_buf.append(kpts18)

            if run_cj_collect:
                state.cj_frames_buf.append(frame.copy())
                state.cj_kpts_buf.append(kpts18.copy())
                if len(state.cj_frames_buf) == state.cj_frames_buf.maxlen:
                    cj_worker.submit(1, list(state.cj_frames_buf), list(state.cj_kpts_buf))

            if (
                live_vsvig_enabled
                and seizure_model is not None
                and frame_n % INFERENCE_STRIDE == 0
                and len(state.patches_buf) == WINDOW_FRAMES
            ):
                patch_tensor = (
                    torch.tensor(np.array(state.patches_buf), dtype=torch.float32)
                    .unsqueeze(0)
                    .permute(0, 1, 2, 5, 3, 4)
                    .to(device)
                )
                kpts_tensor = reorder_kpts_for_vsvig(state.kpts_buf).to(device)
                with cuda_stream_context("main", device):
                    with torch.no_grad(), torch.autocast(
                        device_type=device.type,
                        enabled=(USE_AMP and device.type == "cuda"),
                        dtype=torch.float16,
                    ):
                        state.current_risk = torch.clamp(
                            seizure_model(patch_tensor, kpts_tensor), 0.0, 1.0
                        ).item()
                state.current_risk = finite_score(state.current_risk)
                state.risk_buf.append((frame_n / max(float(fps), 1.0), state.current_risk))

        state.ap_sum = update_ap_sum(state, frame_n / max(float(fps), 1.0))
        state.cj_prob, state.cj_age_sec = cj_worker.latest(1)
        initialising = both_models_waiting_for_clip(state, live_vsvig_enabled)
        vsvig_signal = None if initialising or not live_vsvig_enabled else state.ap_sum
        if initialising:
            state.seizure_signal, state.seizure_source = 0.0, "INITIALISING"
        elif ENABLE_CJ_ASYNC:
            state.seizure_signal, state.seizure_source = series_gate_signal(
                state.cj_prob,
                vsvig_signal,
                state.cj_age_sec,
                alert_active=(state.status == "SEIZURE" or frame_n <= state.alert_hold_until_frame),
            )
        else:
            state.seizure_signal, state.seizure_source = state.ap_sum, "VSViG_AP"
        state.seizure_signal = finite_score(state.seizure_signal)
        if initialising:
            state.status = "INITIALISING"
            state.alert_latched = False
        else:
            apply_alert_latch(state, frame_n, fps)

        if disp is not None:
            if state.last_kpts18 is not None and frame_n - state.last_kpts_frame <= TRACK_MAX_AGE_FRAMES:
                draw_skeleton(disp, state.last_kpts18.copy())
            render_patient(disp, patient_box, state)
            render_summary(disp, state)
        profiler.tick()

        if alert_logger is not None:
            alert_logger.writerow({
                "frame": frame_n,
                "time_sec": frame_n / max(float(fps), 1.0),
                "status": state.status,
                "seizure_signal": finite_score(state.seizure_signal),
                "seizure_source": state.seizure_source,
                "ap_sum": finite_score(state.ap_sum),
                "current_risk": finite_score(state.current_risk),
                "cj_prob": "" if state.cj_prob is None else finite_score(state.cj_prob),
                "cj_age_sec": "" if state.cj_age_sec is None else finite_score(state.cj_age_sec),
                "pose_conf_mean": finite_score(state.last_pose_conf_mean),
                "alert_latched": int(bool(state.alert_latched)),
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
            })

        stop_requested = False
        with Timer(profiler, "render_write"):
            if vout is not None and disp is not None:
                vout.write(disp)
            if DISPLAY_UI and disp is not None:
                cv2.imshow("Monitoring", disp)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    stop_requested = True
        profiler.add("frame_total", (time.perf_counter() - frame_t0) * 1000.0)
        if stop_requested:
            break
        if MAX_FRAMES and frame_n >= MAX_FRAMES:
            print(f"Reached MAX_FRAMES={MAX_FRAMES}; stopping smoke run.")
            break

    cap.release()
    cj_worker.stop()
    if vout is not None:
        vout.release()
    if alert_logger is not None:
        alert_logger.close()
    if DISPLAY_UI:
        cv2.destroyAllWindows()
    profiler.print_summary()
    if WRITE_OUTPUT:
        print(f"Saved: {OUTPUT_PATH}")
    else:
        print("Output AVI disabled; no video file written.")


if __name__ == "__main__":
    main()
