"""
Patch extraction utilities for VSViG.

The paper-faithful contract is:
- normalize the full frame once,
- extract Gaussian-weighted 128x128 windows around full-frame keypoints,
- resize each joint patch to 32x32,
- do not re-normalize each patch independently.
"""

import math

import cv2
import numpy as np


_KERNEL_CACHE: dict[tuple[int, float], np.ndarray] = {}


def norm(x: np.ndarray) -> np.ndarray:
    """Min-max normalize an array to [0, 255]. Returns x unchanged if flat."""
    rng = np.max(x) - np.min(x)
    if rng == 0:
        return x
    return ((x - np.min(x)) / rng) * 255


def gen_kernel(size: int, sigma: float) -> np.ndarray:
    """Build a square 2D Gaussian kernel."""
    kernel = np.fromfunction(
        lambda x, y: (1 / (2 * math.pi * sigma ** 2))
        * math.e
        ** (
            (-1 * ((x - (size - 1) / 2) ** 2 + (y - (size - 1) / 2) ** 2))
            / (2 * sigma ** 2)
        ),
        (size, size),
    )
    kernel /= np.sum(kernel)
    kernel = (kernel - np.min(kernel)) / (np.max(kernel) - np.min(kernel))
    return kernel


def _get_kernel(kernel_size: int, kernel_sigma: float) -> np.ndarray:
    key = (int(kernel_size), float(kernel_sigma))
    if key not in _KERNEL_CACHE:
        kernel = gen_kernel(kernel_size, kernel_size * kernel_sigma)
        _KERNEL_CACHE[key] = np.expand_dims(kernel, 2).repeat(3, axis=2)
    return _KERNEL_CACHE[key]


def prepare_patch_context(img: np.ndarray, kernel_size: int = 128) -> tuple[np.ndarray, int, int]:
    """Normalize and pad a frame once so multiple patient tracks can share it."""
    h, w, _ = img.shape
    img_norm = norm(img.astype(np.float32))
    pad = np.zeros((h + kernel_size * 2, w + kernel_size * 2, 3), dtype=np.float32)
    pad[kernel_size:-kernel_size, kernel_size:-kernel_size] = img_norm
    return pad, h, w


def extract_patches_from_context(
    context: tuple[np.ndarray, int, int],
    kpts: np.ndarray,
    kernel_size: int = 128,
    kernel_sigma: float = 0.3,
    scale: float = 1 / 4,
    mode: str = "paper",
) -> np.ndarray:
    """Extract 15 Gaussian-weighted RGB joint patches from a prepared frame."""
    if mode not in {"paper", "confidence"}:
        raise ValueError(f"Unsupported patch mode: {mode}")

    pad, _h, _w = context
    kernel = _get_kernel(kernel_size, kernel_sigma)
    kpts_15 = np.delete(kpts, [1, 16, 17], axis=0)
    out_size = math.ceil(scale * kernel_size)
    patches = np.zeros((15, out_size, out_size, 3), dtype=np.float32)

    for idx in range(15):
        yc = int(kpts_15[idx, 1])
        xc = int(kpts_15[idx, 0])
        conf = float(kpts_15[idx, 2]) if mode == "confidence" else 1.0

        y1 = int(yc + 0.5 * kernel_size)
        y2 = int(yc + 1.5 * kernel_size)
        x1 = int(xc + 0.5 * kernel_size)
        x2 = int(xc + 1.5 * kernel_size)

        if y1 < 0 or x1 < 0 or y2 >= pad.shape[0] or x2 >= pad.shape[1]:
            continue

        tmp = pad[y1:y2, x1:x2] * (kernel * conf)
        patches[idx] = cv2.resize(tmp, (out_size, out_size), interpolation=cv2.INTER_LINEAR)

    return patches


def extract_patches(
    img: np.ndarray,
    kpts: np.ndarray,
    kernel_size: int = 128,
    kernel_sigma: float = 0.3,
    scale: float = 1 / 4,
    mode: str = "paper",
) -> np.ndarray:
    """Backward-compatible one-call patch extraction."""
    context = prepare_patch_context(img, kernel_size)
    return extract_patches_from_context(context, kpts, kernel_size, kernel_sigma, scale, mode)
