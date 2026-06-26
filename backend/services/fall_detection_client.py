"""
Fall detection service client
-------------------------------
Manages sessions and WebSocket connections to the fall detection microservice
(port 8002).

Responsibilities:
  - Create / delete monitoring sessions (REST).
  - Return the WebSocket URL for a room so the monitoring router can forward it.
  - Health check for the admin dashboard.

The actual WebSocket bridging (camera feed → fall service → alert manager) is
handled by the monitoring router which calls connect_room_ws() and forwards
incoming binary camera frames.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("fall-detection-client")

_BASE_URL   = os.getenv("FALL_DETECTION_SERVICE_URL", "http://localhost:8002")
_WS_BASE    = _BASE_URL.replace("http://", "ws://").replace("https://", "wss://")
_TIMEOUT    = httpx.Timeout(timeout=10.0)

_client = httpx.AsyncClient(base_url=_BASE_URL, timeout=_TIMEOUT)


async def health_check() -> dict:
    """Return the fall detection service health dict, or an error dict if unreachable."""
    try:
        resp = await _client.get("/health")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning(f"Fall detection service unreachable: {exc}")
        return {"status": "unreachable", "error": str(exc)}


async def create_session(room_id: str) -> dict:
    """
    Create (or retrieve) a named monitoring session on the fall detection service.

    Returns the session info dict from the service, or an error dict.
    """
    try:
        resp = await _client.post("/sessions", json={"room_id": room_id})
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        msg = f"Could not create fall detection session for room {room_id}: {exc}"
        log.error(msg)
        return {"error": msg}


async def delete_session(room_id: str) -> dict:
    """Stop and remove a monitoring session from the fall detection service."""
    try:
        resp = await _client.delete(f"/sessions/{room_id}")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        msg = f"Could not delete fall detection session {room_id}: {exc}"
        log.error(msg)
        return {"error": msg}


async def list_sessions() -> list[dict]:
    """Return all active sessions from the fall detection service."""
    try:
        resp = await _client.get("/sessions")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning(f"Could not list fall sessions: {exc}")
        return []


def get_ws_url(room_id: str) -> str:
    """Return the WebSocket URL for streaming frames to a room."""
    return f"{_WS_BASE}/ws/{room_id}"


async def reset_latch(room_id: str) -> dict:
    """Reset the fall alert latch for the given room."""
    try:
        resp = await _client.post(f"/sessions/{room_id}/reset-latch")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        msg = f"Could not reset fall alert latch for room {room_id}: {exc}"
        log.error(msg)
        return {"error": msg}
