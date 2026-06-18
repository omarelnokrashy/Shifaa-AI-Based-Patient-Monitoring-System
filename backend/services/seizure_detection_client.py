"""
Seizure detection service client
-----------------------------------
Manages sessions on the seizure detection microservice (port 8003) and
subscribes to its real-time WebSocket event stream.

Responsibilities:
  - Start / stop monitoring sessions (REST).
  - Subscribe to a session's WebSocket and forward events to the alert manager.
  - Health check for the admin dashboard.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import httpx
import websockets
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("seizure-detection-client")

_BASE_URL = os.getenv("SEIZURE_DETECTION_SERVICE_URL", "http://localhost:8003")
_WS_BASE  = _BASE_URL.replace("http://", "ws://").replace("https://", "wss://")
_TIMEOUT  = httpx.Timeout(timeout=10.0)

_client = httpx.AsyncClient(base_url=_BASE_URL, timeout=_TIMEOUT)


async def health_check() -> dict:
    """Return the seizure service health dict, or an error dict if unreachable."""
    try:
        resp = await _client.get("/health")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning(f"Seizure service unreachable: {exc}")
        return {"status": "unreachable", "error": str(exc)}


async def start_session(
    session_id: str,
    source: str,
    mode: str = "monitor",
    bed_roi: str = "",
) -> dict:
    """
    Tell the seizure service to start a pipeline for the given camera source.

    session_id : unique identifier — typically patient_id as a string.
    source     : camera index, file path, or RTSP URL.
    mode       : "safety" | "monitor" | "screening".
    bed_roi    : optional "x1,y1,x2,y2" in pixels or [0,1] fractions.
    """
    payload = {"session_id": session_id, "source": source, "mode": mode, "bed_roi": bed_roi}
    try:
        resp = await _client.post("/sessions", json=payload)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        msg = f"Could not start seizure session {session_id}: {exc}"
        log.error(msg)
        return {"error": msg}


async def stop_session(session_id: str) -> dict:
    """Stop a running seizure monitoring session."""
    try:
        resp = await _client.delete(f"/sessions/{session_id}")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        msg = f"Could not stop seizure session {session_id}: {exc}"
        log.error(msg)
        return {"error": msg}


async def list_sessions() -> list[dict]:
    try:
        resp = await _client.get("/sessions")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning(f"Could not list seizure sessions: {exc}")
        return []


async def subscribe_and_forward(session_id: str, on_event) -> None:
    """
    Connect to the seizure service WebSocket for session_id and call
    on_event(event_dict) for every incoming event.

    This coroutine runs until the session ends or the connection drops.
    It is designed to be run as a background asyncio task by the monitoring router.

    on_event : async callable(event: dict) → None
    """
    ws_url = f"{_WS_BASE}/ws/{session_id}"
    log.info(f"Subscribing to seizure events: {ws_url}")
    try:
        async with websockets.connect(ws_url) as ws:
            async for raw in ws:
                import json
                try:
                    event = json.loads(raw)
                    await on_event(event)
                except Exception as exc:
                    log.debug(f"Event parse error: {exc}")
    except Exception as exc:
        log.warning(f"Seizure WebSocket disconnected for session {session_id}: {exc}")
