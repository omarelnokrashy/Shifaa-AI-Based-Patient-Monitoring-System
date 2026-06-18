"""
event_aggregator.py
-------------------
Aggregates per-frame NORMAL / SEIZURE status transitions into discrete
seizure episodes with duration, peak gate score, and timing metadata.

Emits a seizure_started event when the status transitions NORMAL -> SEIZURE
and a seizure_ended event when SEIZURE -> NORMAL (after latch expires).

These events are the primary artifact for backend API integration.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from runtime.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SeizureEvent:
    event_id:        int
    start_sec:       float
    end_sec:         Optional[float] = None
    duration_sec:    Optional[float] = None
    peak_gate_score: float = 0.0
    peak_source:     str   = ""
    detected:        bool  = True


class EventAggregator:
    """
    Tracks status transitions and emits seizure episode records.
    Thread-safe for read access; writes should be from the main loop only.
    """

    def __init__(self, window_sec: float = 3.0):
        self.window_sec = window_sec
        self._events: List[SeizureEvent] = []
        self._active: Optional[SeizureEvent] = None
        self._prev_status = "NORMAL"
        self._event_counter = 0

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def update(self, status: str, gate_score: float,
               gate_source: str, time_sec: float) -> Optional[dict]:
        """
        Call once per decision step.

        Returns a dict if an event boundary was crossed (started or ended),
        otherwise None.
        """
        event_dict = None

        if status == "SEIZURE" and self._prev_status == "NORMAL":
            # Seizure started
            self._event_counter += 1
            self._active = SeizureEvent(
                event_id   = self._event_counter,
                start_sec  = time_sec,
                peak_gate_score = gate_score,
                peak_source     = gate_source,
            )
            self._events.append(self._active)
            event_dict = {
                "type":       "seizure_started",
                "event_id":   self._active.event_id,
                "start_sec":  time_sec,
                "gate_score": gate_score,
                "source":     gate_source,
            }
            logger.warning("SEIZURE STARTED  t=%.1fs  event_id=%d",
                           time_sec, self._active.event_id)

        elif status == "NORMAL" and self._prev_status == "SEIZURE":
            # Seizure ended
            if self._active is not None:
                self._active.end_sec     = time_sec
                self._active.duration_sec = time_sec - self._active.start_sec
                event_dict = {
                    "type":         "seizure_ended",
                    "event_id":     self._active.event_id,
                    "start_sec":    self._active.start_sec,
                    "end_sec":      time_sec,
                    "duration_sec": self._active.duration_sec,
                    "peak_gate_score": self._active.peak_gate_score,
                }
                logger.info("SEIZURE ENDED  duration=%.1fs  event_id=%d",
                            self._active.duration_sec, self._active.event_id)
                self._active = None

        # Update peak within active episode
        if self._active is not None and gate_score > self._active.peak_gate_score:
            self._active.peak_gate_score = gate_score
            self._active.peak_source     = gate_source

        self._prev_status = status
        return event_dict

    @property
    def all_events(self) -> List[SeizureEvent]:
        return list(self._events)

    @property
    def n_events(self) -> int:
        return len(self._events)

    def summary(self) -> dict:
        completed = [e for e in self._events if e.end_sec is not None]
        return {
            "total_events":    self.n_events,
            "completed_events": len(completed),
            "mean_duration_sec": (
                sum(e.duration_sec for e in completed) / len(completed)
                if completed else None
            ),
        }
