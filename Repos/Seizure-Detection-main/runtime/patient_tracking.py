"""
patient_tracking.py
--------------------
Patient region manager for the dedicated overhead bed camera.

In the seizure-only deployment the camera is fixed to one bed, so "tracking"
means maintaining the patient crop region rather than multi-person tracking.

Two modes
---------
full_frame : The entire frame is treated as the patient region (default).
bed_roi    : A fixed rectangular ROI is supplied via --bed-roi; only this
             region is fed into pose estimation and VSViG/CJ.

This module is intentionally thin — it exists to make the pipeline extensible
if multi-bed or visitor-discrimination is added later.
"""

import numpy as np
from runtime.utils.logger import get_logger

logger = get_logger(__name__)


class PatientTracker:
    def __init__(self, cfg: dict):
        self._roi = None   # (x1, y1, x2, y2) or None
        logger.info("PatientTracker: full-frame direct-patient mode")

    def set_roi(self, roi: tuple):
        """Set a fixed bed ROI.  Values < 1.0 treated as normalized."""
        self._roi = roi
        logger.info("PatientTracker: bed ROI set to %s", roi)

    def get_crop(self, frame: np.ndarray):
        """
        Returns
        -------
        crop   : np.ndarray  the patient crop
        offset : (ox, oy)    pixel offset for keypoint coordinate recovery
        """
        if self._roi is None:
            return frame, (0, 0)

        x1, y1, x2, y2 = self._roi
        h, w = frame.shape[:2]

        # Support normalised coordinates
        if x1 <= 1.0 and x2 <= 1.0:
            x1, x2 = int(x1 * w), int(x2 * w)
            y1, y2 = int(y1 * h), int(y2 * h)

        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        crop   = frame[y1:y2, x1:x2]
        offset = (x1, y1)
        return crop, offset
