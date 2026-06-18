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
from .. import models
from ..services import arrhythmia_client, fall_detection_client, seizure_detection_client

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

_viewers = require_role("doctor", "admin", "nurse")


class AlertCount(BaseModel):
    alert_type: str
    count:      int


class RecentAlert(BaseModel):
    id:         int
    patient_id: int
    alert_type: str
    severity:   str
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class DashboardSummary(BaseModel):
    alert_counts:    list[AlertCount]
    recent_alerts:   list[RecentAlert]
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

    # ── Alert counts (last 24 h) ───────────────────────────────────────────
    counts_raw = (
        db.query(models.Alert.alert_type, func.count(models.Alert.id))
        .filter(models.Alert.created_at >= since)
        .group_by(models.Alert.alert_type)
        .all()
    )
    alert_counts = [AlertCount(alert_type=str(t), count=c) for t, c in counts_raw]

    # ── Recent unacknowledged alerts ───────────────────────────────────────
    recent = (
        db.query(models.Alert)
        .filter(
            models.Alert.created_at >= since,
            models.Alert.acknowledged_by == None,  # noqa: E711
        )
        .order_by(models.Alert.created_at.desc())
        .limit(10)
        .all()
    )

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

    # ── Chat activity in last 24 h ─────────────────────────────────────────
    chat_count = (
        db.query(func.count(models.ChatLog.id))
        .filter(models.ChatLog.created_at >= since)
        .scalar() or 0
    )

    return DashboardSummary(
        alert_counts    = alert_counts,
        recent_alerts   = recent,
        service_health  = {
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
    acknowledged_by: int   # user_id of the acknowledger


@router.patch("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(
    alert_id:  int,
    req:       AcknowledgeRequest,
    db:        Session = Depends(get_db),
    _user = Depends(_viewers),
):
    """Mark an alert as acknowledged by a user."""
    from fastapi import HTTPException
    alert = db.query(models.Alert).filter(models.Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.acknowledged_by = req.acknowledged_by
    alert.acknowledged_at = datetime.utcnow()
    db.commit()
    db.refresh(alert)
    return {"id": alert.id, "acknowledged_by": alert.acknowledged_by, "acknowledged_at": alert.acknowledged_at}
