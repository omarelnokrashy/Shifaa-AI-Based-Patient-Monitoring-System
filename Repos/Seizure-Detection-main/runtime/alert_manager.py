"""
alert_manager.py
-----------------
Manages seizure alert state with clinical safety latching.

Safeguards implemented
----------------------
1. Alert latch (default 30 s)
   Once a SEIZURE alert fires, it remains active for at least `hold_sec`
   regardless of subsequent gate scores. This prevents occlusion-induced
   false cancellations during an active seizure.

2. AP rolling window (3 s)
   Accumulates gate scores over a 3-second window; decision is made on
   the accumulated sum rather than a single-frame score. This smooths
   transient noise.

3. Mode threshold
   Selectable at runtime via --mode {safety|monitor|screening}.
"""

import time
from collections import deque
from runtime.utils.logger import get_logger

logger = get_logger(__name__)

AP_WINDOW_SEC   = 3.0   # rolling accumulation window
AP_STEP_SEC     = 1.0   # one score per decision step


class AlertManager:
    def __init__(self, hold_sec: float = 30.0, mode_threshold: float = 0.49):
        self.hold_sec        = hold_sec
        self.mode_threshold  = mode_threshold
        self._ap_buffer      = deque()
        self._ap_sum         = 0.0
        self._latched        = False
        self._latch_until    = 0.0
        self._status         = "NORMAL"

    @property
    def status(self) -> str:
        return self._status

    @property
    def latched(self) -> bool:
        return self._latched

    def update(self, gate_score: float, gate_source: str) -> tuple:
        """
        Parameters
        ----------
        gate_score  : fused score from SeriesGate
        gate_source : label string for logging

        Returns
        -------
        ap_sum   : float
        status   : str    "NORMAL" or "SEIZURE"
        latched  : bool
        """
        now = time.time()

        # Add new score to rolling buffer
        self._ap_buffer.append(gate_score)
        self._ap_sum += gate_score
        # Keep only the last AP_WINDOW_SEC / AP_STEP_SEC entries
        max_len = int(AP_WINDOW_SEC / AP_STEP_SEC)
        while len(self._ap_buffer) > max_len:
            self._ap_sum -= self._ap_buffer.popleft()
        self._ap_sum = max(0.0, self._ap_sum)  # numerical guard

        alarm = self._ap_sum > self.mode_threshold

        # Latch logic
        if alarm:
            self._latched    = True
            self._latch_until = now + self.hold_sec
            self._status     = "SEIZURE"
            logger.info(
                "SEIZURE ALERT  ap_sum=%.3f  source=%s  latch_until=+%.0fs",
                self._ap_sum, gate_source, self.hold_sec,
            )
        elif self._latched:
            if now < self._latch_until:
                self._status = "SEIZURE"  # still within latch window
            else:
                self._latched = False
                self._status  = "NORMAL"
        else:
            self._status = "NORMAL"

        return self._ap_sum, self._status, self._latched

    def reset(self):
        """Hard-reset the alert state (useful for unit tests)."""
        self._ap_buffer.clear()
        self._ap_sum    = 0.0
        self._latched   = False
        self._latch_until = 0.0
        self._status    = "NORMAL"
