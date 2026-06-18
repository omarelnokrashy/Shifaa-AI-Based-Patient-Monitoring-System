"""
series_gate.py
--------------
CJ + VSViG series gate: the primary novel clinical contribution.

Gate policy (validation-frozen parameters):
    CJ >= 0.50           -> trust CJ seizure signal
    0.20 <= CJ < 0.50   -> blend: gate_score = alpha*CJ + (1-alpha)*VSViG_AP
    CJ < 0.20           -> trust CJ non-seizure signal

When CJ is unavailable (worker still warming up or result too stale),
the gate falls back to VSViG-only AP mode.

Default parameters:
    gate      = 0.20
    alpha     = 0.30   (CJ blend weight inside the uncertain zone)
    threshold = 0.4945 (full-dataset deployment fit)
    held-out validation-frozen threshold = 0.3081087228480716
"""

from runtime.utils.logger import get_logger

logger = get_logger(__name__)

# Maximum CJ age before result is considered too stale
CJ_MAX_AGE_NORMAL_SEC = 15.0
CJ_MAX_AGE_ALERT_SEC  = 60.0


class SeriesGate:
    """
    Combines VSViG probability and async Cross-Joint probability into a single
    gate score for downstream threshold comparison.
    """

    def __init__(self, cfg: dict, gate: float = 0.20, alpha: float = 0.30,
                 threshold: float = 0.4945):
        self.gate      = cfg.get("gate_lower_bound", gate)
        self.alpha     = cfg.get("gate_alpha",       alpha)
        self.threshold = cfg.get("gate_threshold",   threshold)
        self._in_alert = False

        logger.info(
            "SeriesGate init: gate=%.2f  alpha=%.2f  threshold=%.4f",
            self.gate, self.alpha, self.threshold,
        )

    def set_alert_state(self, in_alert: bool):
        """Called by AlertManager so gate uses the right CJ staleness limit."""
        self._in_alert = in_alert

    def decide(self, vsvig_ap: float, cj_prob, cj_age_sec) -> tuple:
        """
        Returns
        -------
        gate_score : float   the fused score to compare against threshold
        source     : str     one of CJ / CJ_RESCUE / CJ_LOW / VSVIG_AP / CJ_PENDING
        """
        max_age = CJ_MAX_AGE_ALERT_SEC if self._in_alert else CJ_MAX_AGE_NORMAL_SEC

        cj_valid = (
            cj_prob is not None
            and cj_age_sec is not None
            and cj_age_sec <= max_age
        )

        if not cj_valid:
            # CJ not yet available or too stale — use VSViG AP alone
            return vsvig_ap, "CJ_PENDING" if cj_prob is None else "VSVIG_AP"

        if cj_prob >= 0.50:
            return cj_prob, "CJ"

        if cj_prob >= self.gate:
            # Uncertain zone: blend CJ with raw VSViG AP.
            blended = self.alpha * cj_prob + (1.0 - self.alpha) * vsvig_ap
            return max(0.0, blended), "CJ_BLEND"

        # CJ confidently non-seizure
        return cj_prob, "CJ_LOW"
