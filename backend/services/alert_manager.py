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
from datetime import datetime
from typing import Any

from fastapi import WebSocket
from sqlalchemy.orm import Session

from backend import models

log = logging.getLogger("alert-manager")


class AlertManager:
    """
    Singleton-style manager (one shared instance imported by all routers).

    Connected WebSockets are stored in a plain set; the event loop broadcasts
    to every connected client whenever an alert fires.  A disconnected client
    is silently dropped from the set.
    """

    def __init__(self):
        self._clients: set[WebSocket] = set()

    # ── WebSocket subscription management ─────────────────────────────────
    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new alert subscriber."""
        await websocket.accept()
        self._clients.add(websocket)
        log.info(f"Alert subscriber connected. Total: {len(self._clients)}")

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a subscriber (called in finally blocks)."""
        self._clients.discard(websocket)
        log.info(f"Alert subscriber disconnected. Total: {len(self._clients)}")

    # ── Core publish method ────────────────────────────────────────────────
    async def publish(
        self,
        db: Session,
        patient_id: int,
        alert_type: str,
        severity: str,
        details: dict[str, Any],
        acknowledged_by: int | None = None,
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
        acknowledged_by : optional user_id who acknowledged immediately (rare)

        Returns
        -------
        The saved Alert ORM object.
        """
        alert = models.Alert(
            patient_id      = patient_id,
            alert_type      = alert_type,
            severity        = severity,
            details         = details,
            acknowledged_by = acknowledged_by,
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)
        log.warning(f"ALERT [{alert_type}] patient={patient_id} severity={severity} id={alert.id}")

        # Broadcast to all live WebSocket subscribers
        await self._broadcast({
            "type":       "alert",
            "id":         alert.id,
            "patient_id": patient_id,
            "alert_type": alert_type,
            "severity":   severity,
            "details":    details,
            "created_at": alert.created_at.isoformat() if alert.created_at else None,
        })

        return alert

    # ── Internal broadcast ────────────────────────────────────────────────
    async def _broadcast(self, payload: dict) -> None:
        """Send a JSON payload to every connected subscriber, dropping dead connections."""
        if not self._clients:
            return
        raw = json.dumps(payload, default=str)
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_text(raw)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)


# ── Module-level singleton ────────────────────────────────────────────────────
# All routers import this one shared instance.
alert_manager = AlertManager()
