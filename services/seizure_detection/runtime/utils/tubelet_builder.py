"""Cross-Joint tubelet assembly backed by the paper repository implementation."""

from __future__ import annotations

import sys

import cv2
import numpy as np
import torch

from runtime.utils.paths import PROJECT_ROOT


VENDOR_PATH = PROJECT_ROOT / "third_party" / "joint-attention-seizure-detection"
if str(VENDOR_PATH) not in sys.path:
    sys.path.insert(0, str(VENDOR_PATH))


class _Pose:
    __slots__ = ("keypoints",)

    def __init__(self, kpts18: np.ndarray):
        coords = np.asarray(kpts18, dtype=np.float32)[:, :2].copy()
        conf = np.asarray(kpts18, dtype=np.float32)[:, 2]
        coords[(~np.isfinite(coords).all(axis=1)) | (conf <= 0.0)] = -1.0
        self.keypoints = coords


def build_tubelets(frames: list, n_joints: int = 14, patch_size: int = 120, sample_fps: int = 6):
    """Build CJ tubelets and position tensors from buffered frame/skeleton rows.

    Returns torch tensors:
    - tubelets: ``(1, J, T, 3, P, P)``
    - pos: ``(1, J, T, 3)``
    """

    from seizure_classifier.pose import build_joint_tubelets_from_poses

    frames_rgb = []
    poses = []
    for item in frames:
        frame = item["frame"]
        skeleton = item["skeleton"]
        ox, oy = skeleton.get("roi_offset", (0, 0))
        kpts = np.asarray(skeleton["keypoints"], dtype=np.float32).copy()
        if kpts.size:
            kpts[:, 0] -= ox
            kpts[:, 1] -= oy
        frames_rgb.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        poses.append(_Pose(kpts))

    tubelets, pos = build_joint_tubelets_from_poses(
        np.stack(frames_rgb, axis=0).astype(np.uint8),
        poses,
        P=patch_size,
    )
    tube_t = torch.tensor(tubelets[:n_joints], dtype=torch.float32)
    pos_t = torch.tensor(pos[:n_joints], dtype=torch.float32)
    return tube_t.unsqueeze(0), pos_t.unsqueeze(0)
