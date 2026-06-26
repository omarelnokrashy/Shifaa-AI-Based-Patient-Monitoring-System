"""
Central Alert Manager
-----------------------
Receives detection results from any of the three AI inference services
(arrhythmia, fall, seizure), writes them to the `alerts` DB table, and
broadcasts real-time alert JSON to all subscribed WebSocket clients.

Usage pattern (from routers):
    from backend.services.alert_manager import alert_manager
    await alert_manager.publish(db, patient_id=1, alert_type="fall",
                                 severity="high", details={...})

Subscription pattern (WebSocket endpoint):
    await alert_manager.connect(websocket)
    try:
        await websocket.receive_text()  # keep alive
    finally:
        alert_manager.disconnect(websocket)
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import WebSocket
from sqlalchemy.orm import Session

from backend import models
from backend.database import SessionLocal

log = logging.getLogger("alert-manager")


class AlertManager:
    """
    Singleton-style manager (one shared instance imported by all routers).

    Connected WebSockets are stored in a plain set; the event loop broadcasts
    to every connected client whenever an alert fires.  A disconnected client
    is silently dropped from the set.
    """

    def __init__(self):
        """Initialise the manager with an empty dict of WebSocket subscribers to User objects."""
        self._clients: dict[WebSocket, models.User] = {}

    # ── WebSocket subscription management ─────────────────────────────────
    async def connect(self, websocket: WebSocket, user: models.User) -> None:
        """Accept and register a new alert subscriber."""
        await websocket.accept()
        self._clients[websocket] = user
        log.info(f"Alert subscriber connected. Total: {len(self._clients)}")

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a subscriber (called in finally blocks)."""
        self._clients.pop(websocket, None)
        log.info(f"Alert subscriber disconnected. Total: {len(self._clients)}")

    # ── Core publish method ────────────────────────────────────────────────
    async def publish(
        self,
        db: Session,
        patient_id: int,
        alert_type: str,
        severity: str,
        details: dict[str, Any],
    ) -> models.Alert:
        """
        Persist an alert to the database and broadcast it to all live clients.

        Parameters
        ----------
        db            : SQLAlchemy session (caller manages commit lifecycle)
        patient_id    : FK reference to patients.id
        alert_type    : "arrhythmia" | "fall" | "seizure"
        severity      : "low" | "medium" | "high" | "critical"
        details       : arbitrary JSON-serialisable dict with inference output

        Returns
        -------
        The saved Alert ORM object.
        """
        alert = models.Alert(
            patient_id      = patient_id,
            alert_type      = alert_type,
            severity        = severity,
            details         = details,
            status          = "ACTIVE",
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)
        log.warning(f"ALERT [{alert_type}] patient={patient_id} severity={severity} id={alert.id}")

        # Broadcast to all live WebSocket subscribers
        await self._broadcast(db, patient_id, {
            "type":       "alert",
            "id":         alert.id,
            "patient_id": patient_id,
            "alert_type": alert_type,
            "severity":   severity,
            "details":    details,
            "created_at": alert.created_at.isoformat() if alert.created_at else None,
        })

        return alert

    # ── Custom Event Broadcast ────────────────────────────────────────────
    async def broadcast_event(self, db: Session, patient_id: int, payload: dict) -> None:
        """Expose _broadcast publicly for custom events like acknowledge, cancel, or expire."""
        await self._broadcast(db, patient_id, payload)

    # ── Expiration loop ───────────────────────────────────────────────────
    async def clean_expired_alerts_loop(self) -> None:
        """Background task that runs periodically to remove active alerts older than 24 hours."""
        log.info("Starting clean_expired_alerts_loop background worker...")
        while True:
            try:
                await asyncio.sleep(60)  # Check once every minute
                since = datetime.utcnow() - timedelta(hours=24)
                db = SessionLocal()
                try:
                    expired_alerts = db.query(models.Alert).filter(
                        models.Alert.status == "ACTIVE",
                        models.Alert.created_at < since
                    ).all()
                    for alert in expired_alerts:
                        patient_id = alert.patient_id
                        alert_id = alert.id
                        log.warning(f"Alert {alert_id} expired (older than 24h). Deleting from active alerts.")
                        db.delete(alert)
                        db.commit()
                        # Broadcast status change
                        await self._broadcast(db, patient_id, {
                            "type": "expire",
                            "id": alert_id,
                            "patient_id": patient_id
                        })
                except Exception as e:
                    log.error(f"Error executing expiration query: {e}")
                    db.rollback()
                finally:
                    db.close()
            except asyncio.CancelledError:
                log.info("clean_expired_alerts_loop was cancelled.")
                break
            except Exception as e:
                log.error(f"Error in clean_expired_alerts_loop iteration: {e}")

    # ── Internal broadcast ────────────────────────────────────────────────
    async def _broadcast(self, db: Session, patient_id: int, payload: dict) -> None:
        """Send a JSON payload to every connected subscriber, dropping dead connections and filtering by PatientAssignment/RoomAssignment."""
        # 1. If this is a clinical event (alert, ack, etc.) and there is an associated room,
        # also broadcast the updated room card state to everyone.
        if payload.get("type") not in ("room_update", "room_delete") and patient_id:
            try:
                room = db.query(models.Room).filter(models.Room.patient_id == patient_id).first()
                if room:
                    from backend.routers.rooms import serialize_room
                    serialized = serialize_room(db, room)
                    # Broadcast room update event as well
                    await self._broadcast(db, patient_id, {
                        "type": "room_update",
                        "room_id": room.id,
                        "patient_id": room.patient_id,
                        "status": serialized.monitoring_status,
                        "services": serialized.services,
                        "nurses": [n.id for n in serialized.nurses],
                        "alerts": serialized.active_alerts,
                        "risk_score": serialized.risk_score,
                        "connection_state": "connected" if serialized.monitoring_status != "Offline" else "disconnected",
                        "timestamp": datetime.utcnow().isoformat(),
                        "room_data": serialized.dict()
                    })
            except Exception as e:
                log.error(f"Failed to auto-broadcast room update for patient {patient_id}: {e}")

        if not self._clients:
            return

        dead: list[WebSocket] = []
        for ws, user in list(self._clients.items()):
            # Enforce data confidentiality for nurses based on Room assignments
            if user.role == models.UserRole.nurse:
                # Find if room exists for this patient/room_id
                room = None
                room_id = payload.get("room_id")
                if room_id:
                    room = db.query(models.Room).filter(models.Room.id == room_id).first()
                elif patient_id:
                    room = db.query(models.Room).filter(models.Room.patient_id == patient_id).first()

                if room:
                    # Nurse must be assigned to this room
                    assigned_nurse = db.query(models.Room).join(models.Room.nurses).filter(
                        models.Room.id == room.id,
                        models.User.id == user.id
                    ).first()
                    if not assigned_nurse:
                        continue
                else:
                    # Fallback to legacy patient assignment if no room exists
                    assigned = db.query(models.PatientAssignment).filter(
                        models.PatientAssignment.patient_id == patient_id,
                        models.PatientAssignment.user_id == user.id
                    ).first()
                    if not assigned:
                        continue

            elif user.role == models.UserRole.doctor:
                # Doctors can view all rooms. If they fetch a patient-specific endpoint we can keep it open.
                pass

            try:
                # Send the JSON payload
                raw = json.dumps(payload, default=str)
                await ws.send_text(raw)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self._clients.pop(ws, None)


# ── Module-level singleton ────────────────────────────────────────────────────
# All routers import this one shared instance.
alert_manager = AlertManager()
