"""
vsvig_classifier.py
--------------------
Lightweight wrapper around the VSViG model for per-frame real-time inference.

VSViG runs synchronously in the main frame loop at the configured patient FPS
cadence (default 5 fps).  It provides the fast temporal signal for the series
gate and is also used as a rescue signal when CJ is in the uncertain zone.

Reference: Xu et al., "VSViG: Real-Time Video-Based Seizure Detection via
Skeleton-Based Spatiotemporal ViG," ECCV 2024.
"""

from pathlib import Path
import numpy as np
from runtime.utils.logger import get_logger
from runtime.utils.paths import resolve_weight

logger = get_logger(__name__)

PATCH_SIZE = 64          # Gaussian joint patch size
N_JOINTS   = 18          # OpenPose-18


class VSViGClassifier:
    """
    Wraps the VSViG model.  Maintains an internal 30-frame ring buffer
    and returns a seizure probability on every call to predict().
    """

    def __init__(self, cfg: dict):
        self._model  = None
        self._device = "cpu"
        self._buffer = []          # ring buffer of patch tensors
        self._max_buf = 30         # 5 s @ 6 fps
        self._load(cfg)

    def _load(self, cfg: dict):
        try:
            import torch
            ckpt_path = resolve_weight(
                cfg, "model_weights_dir", "vsvig_checkpoint", "model_paper_finetuned.pth"
            )

            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._device = device

            from runtime.models.vsvig import VSViG_base

            model = VSViG_base()
            state = torch.load(str(ckpt_path), map_location=device)
            if isinstance(state, dict) and "state_dict" in state:
                state = state["state_dict"]
            model.load_state_dict(state, strict=False)
            model.to(device).eval()
            self._model = model
            logger.info("VSViG loaded from %s on %s", ckpt_path.name, device)

        except Exception as exc:
            logger.warning("VSViG load failed (%s). Running dummy predictor.", exc)
            self._model = None

    def predict(self, skeleton: dict, frame: np.ndarray) -> float:
        """
        Extract Gaussian joint patches, buffer them, run VSViG.

        Returns
        -------
        prob : float in [0, 1]
        """
        if self._model is None:
            return 0.0

        try:
            import torch
            from runtime.utils.patch_ops import extract_gaussian_patches

            ox, oy = skeleton.get("roi_offset", (0, 0))
            local_keypoints = [
                (x - ox, y - oy, conf) for x, y, conf in skeleton["keypoints"]
            ]
            patches = extract_gaussian_patches(
                frame, local_keypoints,
                patch_size=PATCH_SIZE, n_joints=N_JOINTS,
            )   # (N_JOINTS, 3, PATCH_SIZE, PATCH_SIZE)

            self._buffer.append(patches)
            if len(self._buffer) > self._max_buf:
                self._buffer.pop(0)

            if len(self._buffer) < 5:
                return 0.0   # not enough frames yet

            # Stack buffer: (T, N_JOINTS, 3, H, W)
            clip = np.stack(self._buffer, axis=0)
            t    = torch.from_numpy(clip).float().unsqueeze(0).to(self._device)

            with torch.no_grad():
                out  = self._model(t)
                prob = float(torch.sigmoid(out).item())

            return prob

        except Exception as exc:
            logger.debug("VSViG predict error: %s", exc)
            return 0.0
