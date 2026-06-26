"""
Arrhythmia service client
--------------------------
Thin async wrapper around the arrhythmia microservice (port 8001).
All callers in the main backend import this module and call predict_ecg().

Design principles:
  - One shared httpx.AsyncClient per process (created at import time).
  - Timeout is intentionally short (10 s) — ECG inference is fast.
  - On any network / service error the function returns a degraded result
    dict with "error" set, so callers can log it and continue rather than
    raising a 500 to the doctor's browser.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("arrhythmia-client")

# URL is configurable via .env so the service can be moved to another host
_BASE_URL = os.getenv("ARRHYTHMIA_SERVICE_URL", "http://localhost:8001")
_TIMEOUT  = httpx.Timeout(timeout=15.0)  # ECG inference is fast; 15 s is generous

# One shared client per process (connection pooling, keep-alive)
_client = httpx.AsyncClient(base_url=_BASE_URL, timeout=_TIMEOUT)


async def health_check() -> dict:
    """
    Returns the arrhythmia service health dict, or an error dict if unreachable.
    Used by the admin dashboard endpoint.
    """
    try:
        resp = await _client.get("/health")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning(f"Arrhythmia service unreachable: {exc}")
        return {"status": "unreachable", "error": str(exc)}


async def predict_ecg(
    signal: list[list[float]],
    qrs7: Optional[list[float]] = None,
) -> dict:
    """
    Call the arrhythmia service with a preprocessed 12-lead ECG signal.

    Parameters
    ----------
    signal : list of 5000 lists, each with 12 float values.
             Shape after service conversion: (5000, 12) float32.
    qrs7   : Optional 7-element Pan-Tompkins feature vector.
             If None, the service uses zeros (safe default).

    Returns
    -------
    On success:
        {
            "stage1":             "Normal" | "Abnormal",
            "stage1_confidence":  float,
            "stage2_class":       str | None,
            "stage2_confidence":  float | None,
            "all_probabilities":  dict,
            "error":              None
        }

    On service error / timeout:
        {
            "stage1":             None,
            "stage1_confidence":  None,
            "stage2_class":       None,
            "stage2_confidence":  None,
            "all_probabilities":  {},
            "error":              "description of what went wrong"
        }
    """
    payload: dict = {"signal": signal}
    if qrs7 is not None:
        payload["qrs7"] = qrs7

    try:
        resp = await _client.post("/predict", json=payload)
        resp.raise_for_status()
        data = resp.json()
        data["error"] = None
        return data
    except httpx.TimeoutException:
        msg = "Arrhythmia service timed out"
        log.error(msg)
        return _error_response(msg)
    except httpx.HTTPStatusError as exc:
        msg = f"Arrhythmia service returned {exc.response.status_code}: {exc.response.text}"
        log.error(msg)
        return _error_response(msg)
    except Exception as exc:
        msg = f"Arrhythmia service unreachable: {exc}"
        log.error(msg)
        return _error_response(msg)


def _error_response(msg: str) -> dict:
    """
    Build a degraded result dict when the arrhythmia service is unreachable or returns an error.

    All prediction fields are set to ``None`` / empty so callers can treat the
    response uniformly without extra ``None`` checks.  The ``error`` key carries
    the human-readable failure description for logging and API responses.

    Parameters
    ----------
    msg : str
        Description of the error that occurred.

    Returns
    -------
    dict
        ``{'stage1': None, 'stage1_confidence': None, 'stage2_class': None,
           'stage2_confidence': None, 'all_probabilities': {}, 'error': msg}``
    """
    return {
        "stage1":            None,
        "stage1_confidence": None,
        "stage2_class":      None,
        "stage2_confidence": None,
        "all_probabilities": {},
        "error":             msg,
    }
