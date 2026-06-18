"""
Monitoring router — fall + seizure session management and live alert WebSocket
===============================================================================

Endpoints
---------
POST   /api/monitoring/fall/start           → start fall detection for a patient room
DELETE /api/monitoring/fall/{room_id}/stop  → stop fall detection
POST   /api/monitoring/seizure/start        → start seizure detection for a patient
DELETE /api/monitoring/seizure/{sid}/stop   → stop seizure detection
GET    /api/monitoring/status               → aggregated status of all active sessions

WebSocket
---------
WS /api/ws/alerts                           → real-time alert stream (all alert types)
WS /api/ws/camera/{room_id}                 → camera frame ingestion for fall detection
    Client sends binary JPEG frames; server forwards them to the fall service
    and pushes fall events back as JSON.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import require_role, get_current_user
from .. import models
from ..services import fall_detection_client, seizure_detection_client
from ..services.alert_manager import alert_manager

log = logging.getLogger("monitoring-router")
router = APIRouter(prefix="/api", tags=["Monitoring"])

_clinical = require_role("doctor", "nurse")
_any_auth = require_role("doctor", "nurse", "admin")


# ── Request schemas ─────────────────────────────────────────────────────────────
class FallStartRequest(BaseModel):
    room_id:    str      # e.g. "room-4b" or str(patient_id)
    patient_id: int


class SeizureStartRequest(BaseModel):
    patient_id: int
    source:     str      # camera index, file path, RTSP URL
    mode:       str = "monitor"
    bed_roi:    str = ""


# ── Fall detection session management ──────────────────────────────────────────
@router.post("/monitoring/fall/start")
async def start_fall_monitoring(
    req: FallStartRequest,
    db: Session = Depends(get_db),
    _user = Depends(_clinical),
):
    """
    Create a fall detection session on the fall service for the given room.
    The caller (camera client) should then connect to
    WS /api/ws/camera/{room_id} to stream frames.
    """
    # Verify patient exists
    if not db.query(models.Patient).filter(models.Patient.id == req.patient_id).first():
        raise HTTPException(status_code=404, detail="Patient not found")

    result = await fall_detection_client.create_session(req.room_id)
    if result.get("error"):
        raise HTTPException(status_code=503, detail=result["error"])
    return {**result, "patient_id": req.patient_id, "ws_url": f"/api/ws/camera/{req.room_id}"}


@router.delete("/monitoring/fall/{room_id}/stop")
async def stop_fall_monitoring(room_id: str, _user = Depends(_clinical)):
    """Stop a fall detection session."""
    result = await fall_detection_client.delete_session(room_id)
    if result.get("error"):
        raise HTTPException(status_code=503, detail=result["error"])
    return result


# ── Seizure detection session management ───────────────────────────────────────
@router.post("/monitoring/seizure/start")
async def start_seizure_monitoring(
    req: SeizureStartRequest,
    db: Session = Depends(get_db),
    _user = Depends(_clinical),
):
    """
    Start a seizure detection session.  The seizure service will launch a
    subprocess that reads from `source` and writes events to a CSV log.
    A background task is created to subscribe to those events and push alerts.
    """
    if not db.query(models.Patient).filter(models.Patient.id == req.patient_id).first():
        raise HTTPException(status_code=404, detail="Patient not found")

    session_id = str(req.patient_id)
    result = await seizure_detection_client.start_session(
        session_id=session_id,
        source=req.source,
        mode=req.mode,
        bed_roi=req.bed_roi,
    )
    if result.get("error"):
        raise HTTPException(status_code=503, detail=result["error"])

    # Launch a background coroutine that tails the seizure service WebSocket
    # and creates alerts when the status changes to SEIZURE
    asyncio.create_task(
        _seizure_event_relay(session_id=session_id, patient_id=req.patient_id)
    )

    return {**result, "patient_id": req.patient_id}


@router.delete("/monitoring/seizure/{session_id}/stop")
async def stop_seizure_monitoring(session_id: str, _user = Depends(_clinical)):
    """Stop a seizure monitoring session."""
    result = await seizure_detection_client.stop_session(session_id)
    if result.get("error"):
        raise HTTPException(status_code=503, detail=result["error"])
    return result


# ── Aggregated status ────────────────────────────────────────────────────────────
@router.get("/monitoring/status")
async def monitoring_status(_user = Depends(_any_auth)):
    """
    Return the live state of all fall and seizure monitoring sessions,
    plus health checks for the three inference services.
    """
    fall_sessions    = await fall_detection_client.list_sessions()
    seizure_sessions = await seizure_detection_client.list_sessions()
    arr_health  = await __import__("backend.services.arrhythmia_client",   fromlist=["health_check"]).health_check()
    fall_health = await fall_detection_client.health_check()
    seiz_health = await seizure_detection_client.health_check()

    return {
        "services": {
            "arrhythmia": arr_health,
            "fall":       fall_health,
            "seizure":    seiz_health,
        },
        "fall_sessions":    fall_sessions,
        "seizure_sessions": seizure_sessions,
    }


# ── WebSocket: real-time alerts for all connected staff ───────────────────────
@router.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket):
    """
    Live alert stream.  Any connected browser (doctor or nurse dashboard) can
    subscribe here.  JWT token must be sent as a query param: ?token=<jwt>

    The alert_manager broadcasts to all subscribers whenever publish() is called
    from any router (arrhythmia, fall, seizure).
    """
    # Lightweight token validation via query param (WebSocket can't send headers easily)
    from fastapi import Query
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token query parameter")
        return

    try:
        from ..auth import get_current_user_from_token
        from ..database import SessionLocal
        db = SessionLocal()
        get_current_user_from_token(token, db)  # raises if invalid
        db.close()
    except Exception:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    await alert_manager.connect(websocket)
    try:
        while True:
            # Keep-alive: client can send any text (e.g. "ping")
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        alert_manager.disconnect(websocket)


# ── WebSocket: camera frame ingestion for fall detection ─────────────────────
@router.websocket("/ws/camera/{room_id}")
async def ws_camera(websocket: WebSocket, room_id: str):
    """
    Camera feed bridge for fall detection.

    A camera client (RTSP relay, edge device, or browser MediaRecorder) sends
    JPEG frames as binary WebSocket messages.  This bridge:
      1. Forwards each binary frame to the fall detection service via its own
         WebSocket connection.
      2. Receives fall events from the service and forwards them back to the
         camera client AND to all alert subscribers.

    The fall service must have an active session for room_id before connecting.
    Use POST /api/monitoring/fall/start to create one.
    """
    await websocket.accept()
    log.info(f"Camera client connected: room_id={room_id}")

    fall_ws_url = fall_detection_client.get_ws_url(room_id)

    try:
        import websockets as ws_lib
        async with ws_lib.connect(fall_ws_url) as fall_ws:

            async def relay_to_fall():
                """Forward camera JPEG frames → fall service."""
                async for data in websocket.iter_bytes():
                    await fall_ws.send(data)

            async def relay_from_fall():
                """Receive fall events ← fall service, forward to camera client + alert subscribers."""
                async for msg in fall_ws:
                    try:
                        event = json.loads(msg)
                    except json.JSONDecodeError:
                        continue

                    # Forward to the camera client
                    try:
                        await websocket.send_json(event)
                    except Exception:
                        pass

                    # If it's a fall, create a DB alert and broadcast to all subscribers
                    if event.get("fall_detected"):
                        from ..database import SessionLocal
                        db = SessionLocal()
                        try:
                            # room_id is used as patient identifier when it's numeric
                            patient_id = int(room_id) if room_id.isdigit() else None
                            if patient_id:
                                await alert_manager.publish(
                                    db=db,
                                    patient_id=patient_id,
                                    alert_type="fall",
                                    severity="critical",
                                    details=event,
                                )
                        except Exception as exc:
                            log.error(f"Failed to save fall alert: {exc}")
                        finally:
                            db.close()

            # Run both relay coroutines concurrently
            await asyncio.gather(relay_to_fall(), relay_from_fall())

    except WebSocketDisconnect:
        log.info(f"Camera client disconnected: room_id={room_id}")
    except Exception as exc:
        log.error(f"Camera bridge error for room {room_id}: {exc}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ── Background task: relay seizure events → alert manager ────────────────────
async def _seizure_event_relay(session_id: str, patient_id: int):
    """
    Runs as a background asyncio task.
    Subscribes to the seizure service WebSocket and creates DB alerts
    whenever a SEIZURE status is first detected (not on every frame).
    """
    last_status = "INITIALISING"

    async def on_event(event: dict):
        nonlocal last_status
        current_status = event.get("status", "NORMAL")

        # Only fire an alert on the transition into SEIZURE
        if current_status == "SEIZURE" and last_status != "SEIZURE":
            from ..database import SessionLocal
            db = SessionLocal()
            try:
                await alert_manager.publish(
                    db=db,
                    patient_id=patient_id,
                    alert_type="seizure",
                    severity="critical",
                    details=event,
                )
            except Exception as exc:
                log.error(f"Failed to save seizure alert: {exc}")
            finally:
                db.close()

        last_status = current_status

    await seizure_detection_client.subscribe_and_forward(session_id, on_event)
