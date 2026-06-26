"""
Admin dashboard summary router
--------------------------------
Provides a single aggregated endpoint for the admin / doctor home screen:
  - Active alert counts per type and severity
  - Recent unacknowledged alerts
  - Inference service health status
  - Recent chat activity summary

Access: doctor and admin roles (nurses see the alert panel directly via WebSocket).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import require_role
from .. import models, schemas
from ..services import arrhythmia_client, fall_detection_client, seizure_detection_client

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

_viewers = require_role("doctor", "admin", "nurse")


class AlertCount(BaseModel):
    """Alert frequency aggregated by type for the last 24 hours."""
    alert_type: str
    count:      int


class RecentAlert(BaseModel):
    """Lightweight alert snapshot shown in the dashboard feed."""
    id:         int
    patient_id: int
    alert_type: str
    severity:   str
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class DashboardSummary(BaseModel):
    """
    Aggregated payload returned by ``GET /api/dashboard/summary``.

    Combines alert counts, the most recent unacknowledged alerts,
    inference service health statuses, active monitoring sessions,
    and the number of chat queries issued in the last 24 hours.
    """
    alert_counts:    list[AlertCount]
    recent_alerts:   list[schemas.AlertOut]
    service_health:  dict
    active_sessions: dict
    chat_count_24h:  int


@router.get("/summary", response_model=DashboardSummary)
async def get_summary(
    db: Session = Depends(get_db),
    _user = Depends(_viewers),
):
    """
    Aggregated dashboard data.  Designed to be polled every 30 seconds by the
    frontend to refresh the home screen without needing a persistent WebSocket.
    """
    since = datetime.utcnow() - timedelta(hours=24)

    # Resolve assigned patient IDs for doctors and nurses
    assigned_ids = None
    if _user.role in (models.UserRole.doctor, models.UserRole.nurse):
        assigned_ids = [
            a.patient_id
            for a in db.query(models.PatientAssignment.patient_id)
            .filter(models.PatientAssignment.user_id == _user.id)
            .all()
        ]

    # ── Alert counts (last 24 h) ───────────────────────────────────────────
    q_active_counts = db.query(models.Alert.alert_type, func.count(models.Alert.id)).filter(
        models.Alert.status == "ACTIVE",
        models.Alert.created_at >= since
    )
    if assigned_ids is not None:
        q_active_counts = q_active_counts.filter(models.Alert.patient_id.in_(assigned_ids))
    active_counts_raw = q_active_counts.group_by(models.Alert.alert_type).all()

    q_hist_counts = db.query(models.AlertHistory.alert_type, func.count(models.AlertHistory.id)).filter(
        models.AlertHistory.created_at >= since
    )
    if assigned_ids is not None:
        q_hist_counts = q_hist_counts.filter(models.AlertHistory.patient_id.in_(assigned_ids))
    hist_counts_raw = q_hist_counts.group_by(models.AlertHistory.alert_type).all()

    counts_map = {}
    for t, c in active_counts_raw:
        t_str = t.value if hasattr(t, 'value') else str(t)
        counts_map[t_str] = counts_map.get(t_str, 0) + c
    for t, c in hist_counts_raw:
        t_str = t.value if hasattr(t, 'value') else str(t)
        counts_map[t_str] = counts_map.get(t_str, 0) + c

    alert_counts = [AlertCount(alert_type=t, count=c) for t, c in counts_map.items()]

    # ── Recent unacknowledged + acknowledged alerts ─────────────────────────
    q_active = db.query(models.Alert).filter(
        models.Alert.status == "ACTIVE",
        models.Alert.created_at >= since
    )
    if assigned_ids is not None:
        q_active = q_active.filter(models.Alert.patient_id.in_(assigned_ids))
    active_list = q_active.all()

    q_hist = db.query(models.AlertHistory).filter(
        models.AlertHistory.created_at >= since
    )
    if assigned_ids is not None:
        q_hist = q_hist.filter(models.AlertHistory.patient_id.in_(assigned_ids))
    hist_list = q_hist.all()

    res_recent = []
    for a in active_list:
        res_recent.append({
            "id": a.id,
            "patient_id": a.patient_id,
            "alert_type": a.alert_type.value if hasattr(a.alert_type, 'value') else str(a.alert_type),
            "severity": a.severity.value if hasattr(a.severity, 'value') else str(a.severity),
            "details": a.details,
            "created_at": a.created_at,
            "acknowledged": False,
            "patient_name": a.patient.name if a.patient else None,
            "alert_id": a.id
        })
    for a in hist_list:
        res_recent.append({
            "id": a.id,
            "patient_id": a.patient_id,
            "alert_type": a.alert_type,
            "severity": a.severity,
            "details": a.details,
            "created_at": a.created_at,
            "acknowledged_by": a.acknowledger.name if a.acknowledger else (str(a.acknowledged_by) if a.acknowledged_by else None),
            "acknowledged_at": a.acknowledged_at,
            "acknowledged": True,
            "patient_name": a.patient.name if a.patient else None,
            "alert_id": a.alert_id
        })

    res_recent.sort(key=lambda x: x["created_at"] or datetime.min, reverse=True)
    recent = res_recent[:20]

    # ── Service health (parallel) ──────────────────────────────────────────
    import asyncio
    arr_h, fall_h, seiz_h = await asyncio.gather(
        arrhythmia_client.health_check(),
        fall_detection_client.health_check(),
        seizure_detection_client.health_check(),
    )

    # ── Active monitoring sessions ─────────────────────────────────────────
    fall_sess  = await fall_detection_client.list_sessions()
    seiz_sess  = await seizure_detection_client.list_sessions()

    if assigned_ids is not None:
        # Filter fall sessions: room_id is patient_id if digit-only, or patient_id is present
        filtered_fall = []
        for s in fall_sess:
            pid = s.get("patient_id")
            if pid is None and s.get("room_id", "").isdigit():
                pid = int(s["room_id"])
            if pid in assigned_ids:
                filtered_fall.append(s)
        fall_sess = filtered_fall

        # Filter seizure sessions: session_id is patient_id
        filtered_seiz = []
        for s in seiz_sess:
            pid = s.get("patient_id")
            if pid is None:
                sid = s.get("session_id", "")
                if sid.isdigit():
                    pid = int(sid)
            if pid in assigned_ids:
                filtered_seiz.append(s)
        seiz_sess = filtered_seiz

    # ── Chat activity in last 24 h ─────────────────────────────────────────
    q_chat = db.query(func.count(models.ChatLog.id)).filter(models.ChatLog.created_at >= since)
    if _user.role in (models.UserRole.doctor, models.UserRole.nurse):
        q_chat = q_chat.filter(models.ChatLog.doctor_id == _user.id)
    chat_count = q_chat.scalar() or 0

    return DashboardSummary(
        alert_counts    = alert_counts,
        recent_alerts   = recent,
        service_health  = {
            "main":       {"status": "ok"},
            "arrhythmia": arr_h,
            "fall":       fall_h,
            "seizure":    seiz_h,
        },
        active_sessions = {
            "fall":    fall_sess,
            "seizure": seiz_sess,
        },
        chat_count_24h  = chat_count,
    )


# ── Acknowledge an alert ───────────────────────────────────────────────────────
from pydantic import BaseModel as _Base

class AcknowledgeRequest(_Base):
    """Request body for the alert acknowledgement PATCH endpoint."""
    acknowledged_by: int   # user_id of the acknowledger


@router.patch("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id:  int,
    req:       AcknowledgeRequest,
    db:        Session = Depends(get_db),
    _user = Depends(_viewers),
):
    """Mark an alert as acknowledged by a user (moves to AlertHistory and deletes from Alert)."""
    from fastapi import HTTPException
    from backend.services.alert_manager import alert_manager
    
    alert = db.query(models.Alert).filter(models.Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    patient_id = alert.patient_id

    # Create historical entry
    history_entry = models.AlertHistory(
        alert_id=alert.id,
        patient_id=alert.patient_id,
        alert_type=alert.alert_type.value if hasattr(alert.alert_type, 'value') else str(alert.alert_type),
        severity=alert.severity.value if hasattr(alert.severity, 'value') else str(alert.severity),
        details=alert.details,
        acknowledged_by=req.acknowledged_by,
        acknowledged_at=datetime.utcnow(),
        created_at=alert.created_at or datetime.utcnow(),
        status="ACKNOWLEDGED"
    )
    db.add(history_entry)

    # Delete from active alerts
    db.delete(alert)
    db.commit()

    # Broadcast status change
    await alert_manager.broadcast_event(db, patient_id, {
        "type": "acknowledge",
        "id": alert_id,
        "patient_id": patient_id
    })

    return {"id": alert_id, "status": "ACKNOWLEDGED"}


# ── Cancel an alert ────────────────────────────────────────────────────────────
@router.delete("/alerts/{alert_id}/cancel")
async def cancel_alert(
    alert_id: int,
    db:        Session = Depends(get_db),
    _user = Depends(_viewers),
):
    """Cancel / delete an active alert entirely (no history saved)."""
    from fastapi import HTTPException
    from backend.services.alert_manager import alert_manager

    alert = db.query(models.Alert).filter(models.Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    patient_id = alert.patient_id

    # Delete the alert
    db.delete(alert)
    db.commit()

    # Broadcast status change
    await alert_manager.broadcast_event(db, patient_id, {
        "type": "cancel",
        "id": alert_id,
        "patient_id": patient_id
    })

    return {"id": alert_id, "status": "CANCELLED"}
