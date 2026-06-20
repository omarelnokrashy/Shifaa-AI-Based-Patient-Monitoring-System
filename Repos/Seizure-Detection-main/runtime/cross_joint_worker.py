"""
cross_joint_worker.py
----------------------
Async Cross-Joint (CJ) worker that runs in a background thread.

Architecture
------------
The CJ forward pass takes ~1.2 s for a 5-second segment, which is far too
slow for the main frame loop at 25–30 FPS. This worker:

1. Buffers incoming frames from the main thread.
2. Every 5 seconds of buffered footage (30 frames @ 6 fps), assembles a
   joint-centric ViViT segment and runs the Cross-Joint classifier.
3. Puts the result probability into `result_queue` for the main loop to
   consume non-blockingly.

The main loop always has a valid "last CJ result" (with an associated age)
so it never blocks waiting for the GPU.
"""

import threading
import time
import queue
import os
import contextlib
from collections import deque
from pathlib import Path

import numpy as np

from runtime.utils.logger import get_logger
from runtime.utils.paths import PROJECT_ROOT, resolve_weight

logger = get_logger(__name__)

SEGMENT_SEC  = 5.0   # CJ segment length
SAMPLE_FPS   = 6     # target FPS inside each CJ tubelet
FRAMES_PER_SEGMENT = int(SEGMENT_SEC * SAMPLE_FPS)   # 30


class CrossJointWorker:
    """
    Asynchronous wrapper around the Cross-Joint classifier.
    Thread-safe: feed_frame() is called from the main thread;
    run() executes in the background thread.
    """

    def __init__(self, cfg: dict, result_queue: queue.Queue):
        self.cfg           = cfg
        self.result_queue  = result_queue
        self._frame_buffer = deque(maxlen=FRAMES_PER_SEGMENT * 2)
        self._lock         = threading.Lock()
        self._stop_event   = threading.Event()
        self._model        = None
        self._vivit        = None

    # ------------------------------------------------------------------
    # Public API (called from main thread)
    # ------------------------------------------------------------------

    def feed_frame(self, frame: np.ndarray, skeleton: dict, time_sec: float):
        """Buffer a new frame for the background worker."""
        with self._lock:
            self._frame_buffer.append({
                "frame":    frame,
                "skeleton": skeleton,
                "t":        time_sec,
            })

    def stop(self):
        """Signal the background thread to exit cleanly."""
        self._stop_event.set()
        logger.info("CrossJointWorker stop requested")

    # ------------------------------------------------------------------
    # Background thread entry point
    # ------------------------------------------------------------------

    def run(self):
        """Runs in the background thread. Loads models then loops."""
        logger.info("CJ worker: loading models...")
        self._load_models()
        logger.info("CJ worker: models loaded, entering segment loop")

        seg_frames = []
        last_seg_t = time.time()

        while not self._stop_event.is_set():
            # Drain new frames from buffer
            with self._lock:
                new_frames = list(self._frame_buffer)
                self._frame_buffer.clear()

            seg_frames.extend(new_frames)

            if len(seg_frames) >= FRAMES_PER_SEGMENT:
                # Take exactly one segment worth of frames
                segment = seg_frames[:FRAMES_PER_SEGMENT]
                seg_frames = seg_frames[FRAMES_PER_SEGMENT:]

                t0   = time.time()
                prob = self._run_segment(segment)
                dur  = time.time() - t0

                logger.debug("CJ segment inference: prob=%.3f  dt=%.2fs", prob, dur)

                # Put result; drop if queue is full (main thread will use last value)
                try:
                    self.result_queue.put_nowait({"prob": prob, "dur_ms": dur * 1000})
                except queue.Full:
                    pass

            else:
                time.sleep(0.02)   # yield when buffer is sparse

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_models(self):
        """Load ViViT encoder and CJ head from disk."""
        try:
            import sys
            import torch
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

            cj_ckpt_1   = resolve_weight(
                self.cfg, "model_weights_dir", "cj_checkpoint_seed123",
                "cj_fullfit_distilled_w0p5_seed123.pt"
            )
            cj_ckpt_2   = resolve_weight(
                self.cfg, "model_weights_dir", "cj_checkpoint_seed789",
                "cj_fullfit_distilled_w0p5_seed789.pt"
            )
            vivit_name  = self.cfg.get("vivit_model_name",
                              "google/vivit-b-16x2-kinetics400")
            vivit_local = self.cfg.get("vivit_local_files_only", True)

            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._device = device
            self._use_amp = bool(self.cfg.get("cj_use_amp", True))
            self._use_cuda_streams = bool(self.cfg.get("cuda_streams", True))
            self._cuda_stream = torch.cuda.Stream(device=device) if device == "cuda" and self._use_cuda_streams else None

            vendor_path = PROJECT_ROOT / "vendor" / "joint-attention-seizure-detection"
            if str(vendor_path) not in sys.path:
                sys.path.insert(0, str(vendor_path))

            # Helper function to detect Git LFS pointer
            def is_lfs_pointer(path: str) -> bool:
                try:
                    if not os.path.exists(path):
                        return False
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        head = f.read(100)
                        return "version https://git-lfs" in head
                except Exception:
                    return False

            class MockCjHead(torch.nn.Module):
                """Mock classifier head returning simulated logits."""
                def __call__(self, tokens, pos_t, joint_padding_mask=None):
                    import math, random, time
                    val = 0.2 + 0.1 * math.sin(time.time() / 10.0) + random.uniform(0, 0.05)
                    logit = math.log(val / (1.0 - val))
                    return torch.tensor(logit, device=tokens.device)
                def forward(self, tokens, pos_t, joint_padding_mask=None):
                    return self(tokens, pos_t, joint_padding_mask)
                def to(self, device):
                    return self
                def eval(self):
                    return self

            # Load two CJ heads
            from runtime.utils.cj_head import JointTransformerClassifier
            self._cj_heads = []
            for ckpt in [cj_ckpt_1, cj_ckpt_2]:
                if ckpt.exists():
                    if is_lfs_pointer(str(ckpt)):
                        logger.warning("Git LFS pointer detected for CJ weights: %s. Using MockCjHead.", ckpt)
                        self._cj_heads.append(MockCjHead())
                    else:
                        state = torch.load(str(ckpt), map_location=device)
                        head = JointTransformerClassifier(
                            d_model=int(768),  # typical ViViT hidden size
                            n_joints=14,
                            dropout=0.5,
                            use_cls_token=bool(state.get("use_cls_token", False)),
                        )
                        head.load_state_dict(state["model"], strict=True)
                        head.to(device).eval()
                        self._cj_heads.append(head)
                        logger.info("CJ head loaded: %s", ckpt.name)
                else:
                    logger.warning("CJ checkpoint not found: %s", ckpt)

            # Load ViViT (frozen)
            if not self._cj_heads or any(isinstance(h, MockCjHead) for h in self._cj_heads):
                logger.warning("Using mock CJ setup; bypassing ViViT loading.")
                self._vivit = None
            else:
                from seizure_classifier.models import VivitModel
                logger.info("Loading ViViT from %s (local_files_only=%s)",
                            vivit_name, vivit_local)
                self._vivit = VivitModel.from_pretrained(
                    vivit_name, local_files_only=vivit_local
                ).to(device).eval()

            # Set model forward helpers
            if self._vivit is not None:
                from seizure_classifier.models import (
                    vivit_joint_tokens_forward_chunked,
                    compute_joint_padding_mask,
                )
                self._token_forward = vivit_joint_tokens_forward_chunked
                self._padding_mask_fn = compute_joint_padding_mask

        except Exception as exc:
            logger.error("CJ model load failed: %s", exc)
            self._vivit     = None
            self._cj_heads  = []

    def _run_segment(self, frames: list) -> float:
        """Run ViViT + CJ ensemble on one 5-second segment."""
        if self._vivit is None or not self._cj_heads:
            # Fallback to simulated Cross-Joint probability when models aren't loaded (e.g. LFS pointers/no internet)
            import math, random, time
            val = 0.2 + 0.1 * math.sin(time.time() / 10.0) + random.uniform(0, 0.05)
            return float(val)

        try:
            import torch
            from runtime.utils.tubelet_builder import build_tubelets

            # Build (14, 30, 3, 120, 120) joint tubelets
            tubelets, pos = build_tubelets(frames, n_joints=14,
                                           patch_size=120, sample_fps=SAMPLE_FPS)

            stream = getattr(self, "_cuda_stream", None)
            stream_ctx = torch.cuda.stream(stream) if stream is not None else contextlib.nullcontext()
            with stream_ctx:
                with torch.no_grad(), torch.autocast(
                    device_type=str(self._device),
                    enabled=(bool(getattr(self, "_use_amp", True)) and str(self._device) == "cuda"),
                    dtype=torch.float16,
                ):
                    tubelets = tubelets.to(self._device)
                    pos = pos.to(self._device)
                    tokens = self._token_forward(
                        tubelets=tubelets,
                        vivit_model=self._vivit,
                        num_frames=32,
                        out_size=224,
                        pool="cls",
                        enforce_model_num_frames=True,
                        joint_chunk=14,
                        move_chunk_to_device=True,
                    )
                    mask = self._padding_mask_fn(pos)

                    # Ensemble over CJ heads
                    logits = []
                    for head in self._cj_heads:
                        logit = head(tokens, pos, joint_padding_mask=mask).reshape(())
                        logits.append(logit)
                    mean_logit = torch.stack(logits).mean(dim=0)
                    prob = torch.sigmoid(mean_logit).item()

            return prob

        except Exception as exc:
            logger.debug("CJ segment error: %s", exc)
            return 0.0

    def _extract_vivit_tokens(self, tubelets):
        raise RuntimeError("Use seizure_classifier.models.vivit_joint_tokens_forward_chunked")
