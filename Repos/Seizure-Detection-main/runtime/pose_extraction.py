"""
pose_extraction.py
-------------------
Wraps the fine-tuned Lightweight OpenPose-18 model for patient skeleton
extraction.

The fine-tuned weights (pose.pth) were trained on EMU patient data and
significantly outperform a generic pretrained checkpoint at detecting joints
under clinical clothing, bedding, and overhead camera angles.

Output format
-------------
skeleton : dict with keys
    keypoints : list of (x, y, confidence) for each of the 18 OpenPose joints
    bbox      : (x1, y1, x2, y2) bounding box of the detected person

conf_mean : float — mean confidence across all detected joints
"""

from pathlib import Path
import contextlib
import numpy as np
from runtime.utils.logger import get_logger
from runtime.utils.paths import resolve_path, resolve_weight

logger = get_logger(__name__)

N_JOINTS_OPENPOSE = 18


class PoseExtractor:
    def __init__(self, cfg: dict):
        self._model  = None
        self._device = "cpu"
        self._load(cfg)

    def _load(self, cfg: dict):
        try:
            import torch
            import sys

            ckpt_path  = resolve_weight(cfg, "model_weights_dir", "pose_checkpoint", "pose.pth")
            pose_repo  = resolve_path(cfg.get(
                "pose_repo", "vendor/lightweight-human-pose-estimation.pytorch"
            ))

            sys.path.insert(0, str(pose_repo.resolve()))
            from models.with_mobilenet import PoseEstimationWithMobileNet
            from modules.load_state import load_state

            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._device = device
            self._use_amp = bool(cfg.get("pose_use_amp", True))
            self._use_cuda_streams = bool(cfg.get("cuda_streams", True))
            self._cuda_stream = torch.cuda.Stream(device=device) if device == "cuda" and self._use_cuda_streams else None

            net = PoseEstimationWithMobileNet()
            checkpoint = torch.load(str(ckpt_path), map_location="cpu")
            load_state(net, checkpoint)
            net.to(device).eval()
            self._model  = net
            self._input_height = cfg.get("pose_input_height", 256)
            logger.info("OpenPose loaded from %s on %s", ckpt_path.name, device)

        except Exception as exc:
            logger.warning("Pose model load failed (%s). Returning empty skeleton.", exc)
            self._model = None

    def extract(self, frame: np.ndarray, roi_offset=(0, 0)) -> tuple:
        """
        Parameters
        ----------
        frame      : BGR frame (already cropped to bed ROI if applicable)
        roi_offset : (ox, oy) to add back to keypoint coordinates

        Returns
        -------
        skeleton  : dict {keypoints, bbox} or None
        conf_mean : float
        """
        if self._model is None:
            return None, 0.0

        try:
            import torch
            from modules.keypoints import extract_keypoints, group_keypoints
            from val import normalize, pad_width

            h, w = frame.shape[:2]
            scale = self._input_height / h
            scaled = self._resize(frame, self._input_height)
            tensor = self._to_tensor(scaled)

            stream_ctx = torch.cuda.stream(self._cuda_stream) if self._cuda_stream is not None else contextlib.nullcontext()
            with stream_ctx:
                with torch.no_grad(), torch.autocast(
                    device_type=str(self._device),
                    enabled=(bool(getattr(self, "_use_amp", True)) and str(self._device) == "cuda"),
                    dtype=torch.float16,
                ):
                    stages_out = self._model(tensor.to(self._device))
            paf, heatmaps = stages_out[-2], stages_out[-1]
            paf      = paf[0].float().cpu().numpy()
            heatmaps = heatmaps[0].float().cpu().numpy()

            kps_all, _  = extract_keypoints(heatmaps)
            pose_entries, all_kps = group_keypoints(kps_all, paf,
                                                     demo=True)

            if not pose_entries:
                return None, 0.0

            # Pick the most confident pose (highest mean keypoint confidence)
            best_entry = max(pose_entries,
                             key=lambda e: e[N_JOINTS_OPENPOSE])
            ox, oy = roi_offset
            keypoints = []
            confs     = []
            for i in range(N_JOINTS_OPENPOSE):
                idx = int(best_entry[i])
                if idx != -1 and idx < len(all_kps):
                    x, y, c = all_kps[idx, 0], all_kps[idx, 1], all_kps[idx, 2]
                    x = x / scale + ox
                    y = y / scale + oy
                    keypoints.append((float(x), float(y), float(c)))
                    confs.append(float(c))
                else:
                    keypoints.append((0.0, 0.0, 0.0))
                    confs.append(0.0)

            conf_mean = float(np.mean(confs))
            xs = [k[0] for k in keypoints if k[2] > 0.1]
            ys = [k[1] for k in keypoints if k[2] > 0.1]
            bbox = (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, w, h)

            skeleton = {"keypoints": keypoints, "bbox": bbox, "roi_offset": roi_offset}
            return skeleton, conf_mean

        except Exception as exc:
            logger.debug("Pose extract error: %s", exc)
            return None, 0.0

    def _resize(self, frame, target_h):
        h, w = frame.shape[:2]
        scale = target_h / h
        return __import__("cv2").resize(frame, (int(w * scale), target_h))

    def _to_tensor(self, frame):
        import torch
        img = frame.astype(np.float32) / 255.0
        img = (img - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
        return torch.from_numpy(img.transpose(2, 0, 1)).unsqueeze(0)
