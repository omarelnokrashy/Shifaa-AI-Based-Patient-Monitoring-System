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

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, File, UploadFile
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


def _parse_patient_id(room_id: str) -> Optional[int]:
    """Parse patient_id from a room_id string. Supports purely numeric IDs and 'sandbox_{patient_id}' formats."""
    if room_id.isdigit():
        return int(room_id)
    if room_id.startswith("sandbox_"):
        suffix = room_id[len("sandbox_"):]
        if suffix.isdigit():
            return int(suffix)
    return None


# ── Request schemas ─────────────────────────────────────────────────────────────
class FallStartRequest(BaseModel):
    """Request body to start a fall detection monitoring session for a patient room."""
    room_id:    str      # e.g. "room-4b" or str(patient_id)
    patient_id: int


class SeizureStartRequest(BaseModel):
    """
    Request body to start a seizure detection monitoring session.

    ``source`` may be a camera index (e.g. ``"0"``), a local file path,
    or an RTSP stream URL.  ``bed_roi`` optionally constrains detection
    to a bounding-box region in the frame (JSON-encoded coordinates).
    """
    patient_id: int
    source:     str      # camera index, file path, RTSP URL
    mode:       str = "monitor"
    bed_roi:    str = ""


class SeizureTriggerAlertRequest(BaseModel):
    patient_id: int
    details: dict


async def _update_room_monitoring_status(db: Session, room_ref: str, status_val: str):
    room = None
    if room_ref.isdigit():
        room = db.query(models.Room).filter(models.Room.id == int(room_ref)).first()
    if not room:
        room = db.query(models.Room).filter(models.Room.room_number == room_ref).first()
    if room:
        room.monitoring_status = status_val
        db.commit()
        from backend.routers.rooms import trigger_room_ws_broadcast
        await trigger_room_ws_broadcast(db, room)

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

    if _user.role in (models.UserRole.doctor, models.UserRole.nurse):
        assigned = db.query(models.PatientAssignment).filter(
            models.PatientAssignment.patient_id == req.patient_id,
            models.PatientAssignment.user_id == _user.id
        ).first()
        if not assigned:
            raise HTTPException(status_code=403, detail="Access Denied: Patient is not assigned to you")

    result = await fall_detection_client.create_session(req.room_id)
    if result.get("error"):
        raise HTTPException(status_code=503, detail=result["error"])
    
    await _update_room_monitoring_status(db, req.room_id, "Monitoring")
    return {**result, "patient_id": req.patient_id, "ws_url": f"/api/ws/camera/{req.room_id}"}


@router.delete("/monitoring/fall/{room_id}/stop")
async def stop_fall_monitoring(room_id: str, db: Session = Depends(get_db), _user = Depends(_clinical)):
    """Stop a fall detection session."""
    if _user.role in (models.UserRole.doctor, models.UserRole.nurse):
        patient_id = _parse_patient_id(room_id)
        if patient_id:
            assigned = db.query(models.PatientAssignment).filter(
                models.PatientAssignment.patient_id == patient_id,
                models.PatientAssignment.user_id == _user.id
            ).first()
            if not assigned:
                raise HTTPException(status_code=403, detail="Access Denied: Patient is not assigned to you")
    result = await fall_detection_client.delete_session(room_id)
    if result.get("error"):
        raise HTTPException(status_code=503, detail=result["error"])
    
    await _update_room_monitoring_status(db, room_id, "Idle")
    return result


@router.post("/monitoring/fall/{room_id}/reset-latch")
async def reset_fall_latch(room_id: str, db: Session = Depends(get_db), _user = Depends(_clinical)):
    """Reset the fall alert latch for the given room."""
    if _user.role in (models.UserRole.doctor, models.UserRole.nurse):
        patient_id = _parse_patient_id(room_id)
        if patient_id:
            assigned = db.query(models.PatientAssignment).filter(
                models.PatientAssignment.patient_id == patient_id,
                models.PatientAssignment.user_id == _user.id
            ).first()
            if not assigned:
                raise HTTPException(status_code=403, detail="Access Denied: Patient is not assigned to you")
    result = await fall_detection_client.reset_latch(room_id)
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

    if _user.role in (models.UserRole.doctor, models.UserRole.nurse):
        assigned = db.query(models.PatientAssignment).filter(
            models.PatientAssignment.patient_id == req.patient_id,
            models.PatientAssignment.user_id == _user.id
        ).first()
        if not assigned:
            raise HTTPException(status_code=403, detail="Access Denied: Patient is not assigned to you")

    session_id = str(req.patient_id)
    result = await seizure_detection_client.start_session(
        session_id=session_id,
        source=req.source,
        mode=req.mode,
        bed_roi=req.bed_roi,
    )
    if result.get("error"):
        raise HTTPException(status_code=503, detail=result["error"])

    # Update room status to Initializing (since seizure detection subprocess is launching)
    room = db.query(models.Room).filter(models.Room.patient_id == req.patient_id).first()
    if room:
        room.monitoring_status = "Initializing"
        db.commit()
        from backend.routers.rooms import trigger_room_ws_broadcast
        await trigger_room_ws_broadcast(db, room)

    # Launch a background coroutine that tails the seizure service WebSocket
    # and creates alerts when the status changes to SEIZURE
    is_video = not req.source.isdigit() and ("/" in req.source or "\\" in req.source or req.source.endswith(".mp4") or req.source.endswith(".avi"))
    asyncio.create_task(
        _seizure_event_relay(session_id=session_id, patient_id=req.patient_id, is_video=is_video)
    )

    return {**result, "patient_id": req.patient_id}


@router.delete("/monitoring/seizure/{session_id}/stop")
async def stop_seizure_monitoring(session_id: str, db: Session = Depends(get_db), _user = Depends(_clinical)):
    """Stop a seizure monitoring session."""
    if _user.role in (models.UserRole.doctor, models.UserRole.nurse):
        patient_id = int(session_id) if session_id.isdigit() else None
        if patient_id:
            assigned = db.query(models.PatientAssignment).filter(
                models.PatientAssignment.patient_id == patient_id,
                models.PatientAssignment.user_id == _user.id
            ).first()
            if not assigned:
                raise HTTPException(status_code=403, detail="Access Denied: Patient is not assigned to you")
    result = await seizure_detection_client.stop_session(session_id)
    if result.get("error"):
        raise HTTPException(status_code=503, detail=result["error"])

    # Update room status to Idle
    patient_id = int(session_id) if session_id.isdigit() else None
    if patient_id:
        room = db.query(models.Room).filter(models.Room.patient_id == patient_id).first()
        if room:
            room.monitoring_status = "Idle"
            db.commit()
            from backend.routers.rooms import trigger_room_ws_broadcast
            await trigger_room_ws_broadcast(db, room)

    return result


@router.post("/monitoring/seizure/{session_id}/reset-latch")
async def reset_seizure_latch(session_id: str, db: Session = Depends(get_db), _user = Depends(_clinical)):
    """Reset the seizure alert latch for the given session."""
    if _user.role in (models.UserRole.doctor, models.UserRole.nurse):
        patient_id = int(session_id) if session_id.isdigit() else _parse_patient_id(session_id)
        if patient_id:
            assigned = db.query(models.PatientAssignment).filter(
                models.PatientAssignment.patient_id == patient_id,
                models.PatientAssignment.user_id == _user.id
            ).first()
            if not assigned:
                raise HTTPException(status_code=403, detail="Access Denied: Patient is not assigned to you")
    result = await seizure_detection_client.reset_latch(session_id)
    if result.get("error"):
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@router.post("/monitoring/seizure/trigger-alert")
async def trigger_seizure_alert(
    req: SeizureTriggerAlertRequest,
    db: Session = Depends(get_db),
    _user = Depends(_clinical),
):
    """Trigger and save a seizure alert (used by frontend sandbox during video testing)."""
    if _user.role in (models.UserRole.doctor, models.UserRole.nurse):
        assigned = db.query(models.PatientAssignment).filter(
            models.PatientAssignment.patient_id == req.patient_id,
            models.PatientAssignment.user_id == _user.id
        ).first()
        if not assigned:
            raise HTTPException(status_code=403, detail="Access Denied: Patient is not assigned to you")
            
    alert = await alert_manager.publish(
        db=db,
        patient_id=req.patient_id,
        alert_type="seizure",
        severity="critical",
        details=req.details,
    )
    return {"status": "success", "alert_id": alert.id}
@router.post("/monitoring/seizure/upload-test-video")
async def upload_seizure_test_video(
    file: UploadFile = File(...),
    _user = Depends(_clinical),
):
    """
    Upload a video file to be used as a source for seizure detection testing.
    Saves it to a temporary path and returns the absolute file path.
    """
    import os
    import time
    import shutil
    from pathlib import Path

    upload_dir = Path("uploads/seizure_test")
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Use a safe file name or timestamp
    file_path = upload_dir / f"test_{int(time.time())}_{file.filename}"
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {"file_path": str(file_path.resolve())}



# ── Aggregated status ────────────────────────────────────────────────────────────
@router.get("/monitoring/status")
async def monitoring_status(db: Session = Depends(get_db), _user = Depends(_any_auth)):
    """
    Return the live state of all fall and seizure monitoring sessions,
    plus health checks for the three inference services.
    """
    fall_sessions    = await fall_detection_client.list_sessions()
    seizure_sessions = await seizure_detection_client.list_sessions()
    
    if _user.role in (models.UserRole.doctor, models.UserRole.nurse):
        assigned_ids = {
            a.patient_id
            for a in db.query(models.PatientAssignment.patient_id)
            .filter(models.PatientAssignment.user_id == _user.id)
            .all()
        }
        
        # Filter fall sessions: room_id is patient_id if digit-only, or patient_id is present
        filtered_fall = []
        for s in fall_sessions:
            pid = s.get("patient_id")
            if pid is None and s.get("room_id", "").isdigit():
                pid = int(s["room_id"])
            if pid in assigned_ids:
                filtered_fall.append(s)
        fall_sessions = filtered_fall

        # Filter seizure sessions: session_id is patient_id
        filtered_seiz = []
        for s in seizure_sessions:
            pid = s.get("patient_id")
            if pid is None:
                sid = s.get("session_id", "")
                if sid.isdigit():
                    pid = int(sid)
            if pid in assigned_ids:
                filtered_seiz.append(s)
        seizure_sessions = filtered_seiz

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
        user = get_current_user_from_token(token, db)  # raises if invalid
        db.close()
    except Exception:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    await alert_manager.connect(websocket, user)
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
                last_fall_detected = False
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
                    current_fall_detected = event.get("fall_detected", False)
                    if current_fall_detected and not last_fall_detected:
                        from ..database import SessionLocal
                        db = SessionLocal()
                        try:
                            patient_id = _parse_patient_id(room_id)
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
                    last_fall_detected = current_fall_detected

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
async def _seizure_event_relay(session_id: str, patient_id: int, is_video: bool = False):
    """
    Runs as a background asyncio task.
    Subscribes to the seizure service WebSocket and creates DB alerts
    whenever a SEIZURE status is first detected (not on every frame).
    """
    last_status = "INITIALISING"

    async def on_event(event: dict):
        """
        Callback invoked for every frame-level event received from the seizure
        detection service.  Fires a DB alert and broadcasts to all WebSocket
        subscribers only on the first frame that transitions into SEIZURE status,
        avoiding alert storms for sustained seizure episodes.
        """
        nonlocal last_status
        current_status = event.get("status", "NORMAL")

        # Sync room status dynamically based on current_status
        from ..database import SessionLocal
        db_session = SessionLocal()
        try:
            room = db_session.query(models.Room).filter(models.Room.patient_id == patient_id).first()
            if room:
                target_status = "Monitoring"
                if current_status == "INITIALISING":
                    target_status = "Initializing"
                elif current_status == "SEIZURE":
                    target_status = "Critical Alert"
                
                if room.monitoring_status != target_status:
                    room.monitoring_status = target_status
                    db_session.commit()
                    from backend.routers.rooms import trigger_room_ws_broadcast
                    await trigger_room_ws_broadcast(db_session, room)
        except Exception as e:
            log.error(f"Error syncing room status in seizure relayer: {e}")
        finally:
            db_session.close()

        # Only fire an alert on the transition into SEIZURE
        if current_status == "SEIZURE" and last_status != "SEIZURE":
            if not is_video:
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
