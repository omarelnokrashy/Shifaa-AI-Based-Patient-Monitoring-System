"""Joint-centered image patch extraction for VSViG."""

from __future__ import annotations

import cv2
import numpy as np


def _crop_square(frame: np.ndarray, cx: float, cy: float, size: int) -> np.ndarray:
    h, w = frame.shape[:2]
    half = size // 2
    x1, x2 = int(round(cx)) - half, int(round(cx)) + half
    y1, y2 = int(round(cy)) - half, int(round(cy)) + half

    patch = np.zeros((size, size, 3), dtype=frame.dtype)
    sx1, sx2 = max(0, x1), min(w, x2)
    sy1, sy2 = max(0, y1), min(h, y2)
    if sx1 >= sx2 or sy1 >= sy2:
        return patch

    dx1, dy1 = sx1 - x1, sy1 - y1
    patch[dy1:dy1 + (sy2 - sy1), dx1:dx1 + (sx2 - sx1)] = frame[sy1:sy2, sx1:sx2]
    return patch


def extract_gaussian_patches(
    frame: np.ndarray,
    keypoints: list,
    patch_size: int = 64,
    n_joints: int = 18,
) -> np.ndarray:
    """Return joint-centered RGB patches shaped ``(J, 3, H, W)``.

    Keypoints may be absolute frame coordinates. If the caller attached an
    ``roi_offset`` to the skeleton, it should subtract that before passing the
    points here.
    """

    patches = []
    for i in range(n_joints):
        if i < len(keypoints):
            x, y, conf = keypoints[i]
        else:
            x, y, conf = 0.0, 0.0, 0.0

        if conf <= 0:
            patch = np.zeros((patch_size, patch_size, 3), dtype=np.uint8)
        else:
            patch = _crop_square(frame, x, y, patch_size)
            patch = cv2.cvtColor(patch, cv2.COLOR_BGR2RGB)

        patches.append(patch.transpose(2, 0, 1).astype(np.float32) / 255.0)

    return np.stack(patches, axis=0)
