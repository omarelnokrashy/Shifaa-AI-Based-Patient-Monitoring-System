import os
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

from runtime.utils.paths import resolve_path

pose_repo_path = resolve_path(os.environ.get("POSE_REPO", "third_party/lightweight-human-pose-estimation.pytorch"))
if str(pose_repo_path) not in sys.path:
    sys.path.insert(0, str(pose_repo_path))
from models.with_mobilenet import PoseEstimationWithMobileNet
from modules.load_state import load_state


def load_pose_model(weights_path: str, device: torch.device):
    print(f"Loading PyTorch pose model from {weights_path}")
    net = PoseEstimationWithMobileNet()
    load_state(net, torch.load(weights_path, map_location="cpu"))
    net = net.to(device).eval()
    return net


def openpose_keypoints_from_heatmaps_gpu(heatmaps: torch.Tensor, crop_w: int, crop_h: int, device: torch.device) -> np.ndarray:
    if heatmaps.ndim == 3:
        heatmaps = heatmaps.unsqueeze(0)
    heatmaps = heatmaps.float().to(device)
    hm_w = max(1, int(round(crop_w / 8.0)))
    hm_h = max(1, int(round(crop_h / 8.0)))
    heatmaps = torch.nn.functional.interpolate(
        heatmaps,
        size=(hm_h, hm_w),
        mode="bicubic",
        align_corners=False,
    )[0, :18]
    heatmaps = torch.where(heatmaps >= 0.1, heatmaps, torch.zeros_like(heatmaps))
    pooled = torch.nn.functional.max_pool2d(heatmaps.unsqueeze(1), kernel_size=3, stride=1, padding=1).squeeze(1)
    peaks = (heatmaps == pooled) & (heatmaps > 0.0)

    kpts = torch.zeros((18, 3), dtype=torch.float32, device=device)
    flat_scores = torch.where(peaks, heatmaps, torch.full_like(heatmaps, -1.0)).flatten(1)
    vals, idx = flat_scores.max(dim=1)
    valid = vals > 0.0
    ys = torch.div(idx, hm_w, rounding_mode="floor").float()
    xs = (idx % hm_w).float()
    kpts[:, 0] = torch.where(valid, xs, torch.zeros_like(xs))
    kpts[:, 1] = torch.where(valid, ys, torch.zeros_like(ys))
    kpts[:, 2] = torch.where(valid, vals, torch.zeros_like(vals))
    return kpts.detach().cpu().numpy().astype(np.float32)


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

    with torch.no_grad(), torch.autocast(
        device_type=device.type,
        enabled=(device.type == "cuda"),
        dtype=torch.float16,
    ):
        stages = net(t)

    if device.type == "cuda":
        try:
            return openpose_keypoints_from_heatmaps_gpu(stages[-2], w, h, device)
        except Exception as exc:
            print(f"[WARN] GPU keypoint extraction failed; using CPU path: {exc}")

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


def map_crop_kpts_to_frame(kpts: np.ndarray, box) -> np.ndarray:
    x1, y1, _, _ = box
    mapped = kpts.copy()
    mapped[:, 0] = mapped[:, 0] * 8.0 + x1
    mapped[:, 1] = mapped[:, 1] * 8.0 + y1
    return mapped
