"""
stream_visualizer.py
---------------------
Renders the live seizure detection overlay onto each frame.

Overlay elements
----------------
- Status banner:  NORMAL (green) / SEIZURE (red)
- Gate score bar: horizontal progress bar
- CJ probability: stepped indicator (holds flat between updates)
- VSViG risk:     fast-updating line indicator
- AP sum:         current rolling accumulation
- Mode label:     safety / monitor / screening
- Skeleton:       joint overlay from OpenPose-18
- Alert latch:    shown when active
- Timestamp:      elapsed video time
"""

import cv2
import numpy as np

# OpenPose-18 limb pairs for skeleton overlay
LIMB_PAIRS = [
    (0, 1), (1, 2), (2, 3), (3, 4),   # right arm
    (1, 5), (5, 6), (6, 7),            # left arm
    (1, 8), (8, 9), (9, 10),           # right leg
    (1, 11), (11, 12), (12, 13),       # left leg
    (0, 14), (14, 16),                 # right eye/ear
    (0, 15), (15, 17),                 # left eye/ear
]

STATUS_COLORS = {
    "NORMAL":  (60, 200, 60),    # green  (BGR)
    "SEIZURE": (30, 30, 240),    # red    (BGR)
}

MODE_COLORS = {
    "safety":    (20, 180, 255),  # amber
    "monitor":   (255, 200, 20),  # blue
    "screening": (180, 60, 255),  # purple
}


class StreamVisualizer:
    def __init__(self, frame_w: int, frame_h: int, mode: str = "monitor"):
        self.W    = frame_w
        self.H    = frame_h
        self.mode = mode
        self.mode_color = MODE_COLORS.get(mode, (255, 255, 255))
        self._font      = cv2.FONT_HERSHEY_SIMPLEX
        self._font_mono = cv2.FONT_HERSHEY_DUPLEX

    def draw(self, frame: np.ndarray, status: str, gate_score: float,
             gate_source: str, cj_prob, vsvig_prob: float, ap_sum: float,
             latched: bool, time_sec: float, skeleton, roi_offset=(0, 0)) -> np.ndarray:

        out = frame.copy()

        # ------------------------------------------------------------------
        # Skeleton overlay
        # ------------------------------------------------------------------
        if skeleton is not None:
            self._draw_skeleton(out, skeleton, roi_offset)

        # ------------------------------------------------------------------
        # Top status banner
        # ------------------------------------------------------------------
        color  = STATUS_COLORS.get(status, (200, 200, 200))
        banner = np.full((56, self.W, 3), color, dtype=np.uint8)
        alpha  = 0.85
        out[:56] = cv2.addWeighted(out[:56], 1 - alpha, banner, alpha, 0)

        latch_str = "  [LATCHED]" if latched else ""
        cv2.putText(out, f"{status}{latch_str}", (14, 40),
                    self._font, 1.2, (255, 255, 255), 2, cv2.LINE_AA)

        # Mode label (top-right)
        mode_label = f"[{self.mode.upper()}]"
        (tw, _), _ = cv2.getTextSize(mode_label, self._font, 0.7, 2)
        cv2.putText(out, mode_label, (self.W - tw - 12, 38),
                    self._font, 0.7, self.mode_color, 2, cv2.LINE_AA)

        # ------------------------------------------------------------------
        # Bottom HUD panel
        # ------------------------------------------------------------------
        panel_h = 110
        panel   = np.zeros((panel_h, self.W, 3), dtype=np.uint8)
        panel[:] = (18, 18, 18)
        alpha   = 0.80
        y0      = self.H - panel_h
        out[y0:] = cv2.addWeighted(out[y0:], 1 - alpha, panel, alpha, 0)

        # Gate score bar
        bar_x, bar_y, bar_w, bar_h = 14, y0 + 14, self.W - 28, 20
        cv2.rectangle(out, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h),
                      (60, 60, 60), -1)
        fill = int(gate_score * bar_w)
        fill_color = STATUS_COLORS[status]
        cv2.rectangle(out, (bar_x, bar_y), (bar_x + fill, bar_y + bar_h),
                      fill_color, -1)
        cv2.putText(out, f"Gate: {gate_score:.3f}  [{gate_source}]",
                    (bar_x, bar_y - 3), self._font, 0.5, (200, 200, 200), 1)

        # Metrics row
        cj_str = f"{cj_prob:.3f}" if cj_prob is not None else "---"
        metrics = (
            f"CJ: {cj_str}    "
            f"VSViG: {vsvig_prob:.3f}    "
            f"AP: {ap_sum:.3f}    "
            f"t={time_sec:.1f}s"
        )
        cv2.putText(out, metrics, (14, y0 + 54),
                    self._font_mono, 0.48, (200, 200, 200), 1, cv2.LINE_AA)

        # Safety info row
        cv2.putText(out, "SEIZURE DETECTION SYSTEM — FOR RESEARCH USE ONLY",
                    (14, y0 + 82),
                    self._font, 0.38, (100, 100, 100), 1, cv2.LINE_AA)

        return out

    def _draw_skeleton(self, frame: np.ndarray, skeleton: dict, offset=(0, 0)):
        """Draw OpenPose joints and limb connections."""
        joints = skeleton.get("keypoints", [])  # list of (x, y, conf)
        ox, oy = offset

        for (a, b) in LIMB_PAIRS:
            if a < len(joints) and b < len(joints):
                xa, ya, ca = joints[a]
                xb, yb, cb = joints[b]
                if ca > 0.1 and cb > 0.1:
                    cv2.line(frame,
                             (int(xa) + ox, int(ya) + oy),
                             (int(xb) + ox, int(yb) + oy),
                             (0, 255, 255), 2, cv2.LINE_AA)

        for j, (x, y, c) in enumerate(joints):
            if c > 0.1:
                cv2.circle(frame, (int(x) + ox, int(y) + oy),
                           5, (0, 128, 255), -1, cv2.LINE_AA)
