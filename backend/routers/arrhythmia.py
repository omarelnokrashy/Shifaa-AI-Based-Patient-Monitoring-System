"""
Arrhythmia analysis router
----------------------------
Accepts a 12-lead ECG signal, forwards it to the arrhythmia microservice,
persists the result, and returns the classification to the caller.

Access: doctor and nurse roles.

Endpoints
---------
POST /api/arrhythmia/analyze   → run the two-stage cascade on a submitted ECG
GET  /api/arrhythmia/history/{patient_id}  → recent arrhythmia alerts for a patient
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import require_role
from .. import models
from ..services import arrhythmia_client
from ..services.alert_manager import alert_manager

router = APIRouter(prefix="/api/arrhythmia", tags=["Arrhythmia"])

_clinical = require_role("doctor", "nurse")


# ── Request / Response schemas ─────────────────────────────────────────────────
class ECGAnalyzeRequest(BaseModel):
    """Request body for the ECG analysis endpoint."""
    patient_id: int
    signal: list[list[float]]        # (5000, 12) ECG array
    qrs7:   Optional[list[float]] = None   # Pan-Tompkins 7-feature vector


class ECGAnalyzeResponse(BaseModel):
    """
    Response returned after ECG classification.

    Carries the two-stage cascade results (stage1 = Normal/Abnormal,
    stage2 = specific arrhythmia subtype), the alert ID if one was
    created, and the full probability distribution from the classifier.
    """
    alert_id:           Optional[int]
    patient_id:         int
    stage1:             Optional[str]
    stage1_confidence:  Optional[float]
    stage2_class:       Optional[str]
    stage2_confidence:  Optional[float]
    all_probabilities:  dict
    alert_created:      bool
    error:              Optional[str]


class AlertSummary(BaseModel):
    """Compact alert record used in the arrhythmia history list response."""
    id:         int
    alert_type: str
    severity:   str
    details:    Optional[dict]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


# ── POST /api/arrhythmia/analyze ──────────────────────────────────────────────
@router.post("/analyze", response_model=ECGAnalyzeResponse)
async def analyze_ecg(
    req: ECGAnalyzeRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_clinical),
):
    """
    Submit a 12-lead ECG signal (5000 × 12 float32 array) for arrhythmia
    classification.

    If the result is Abnormal, an alert is automatically persisted in the DB
    and broadcast to all connected WebSocket clients.
    """
    # Validate patient exists
    patient = db.query(models.Patient).filter(models.Patient.id == req.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    if current_user.role in (models.UserRole.doctor, models.UserRole.nurse):
        assigned = db.query(models.PatientAssignment).filter(
            models.PatientAssignment.patient_id == req.patient_id,
            models.PatientAssignment.user_id == current_user.id
        ).first()
        if not assigned:
            raise HTTPException(status_code=403, detail="Access Denied: Patient is not assigned to you")

    # Call the inference microservice
    result = await arrhythmia_client.predict_ecg(req.signal, req.qrs7)

    if result.get("error"):
        return ECGAnalyzeResponse(
            alert_id=None, patient_id=req.patient_id,
            stage1=None, stage1_confidence=None,
            stage2_class=None, stage2_confidence=None,
            all_probabilities={}, alert_created=False,
            error=result["error"],
        )

    # Decide severity based on classification result
    alert_created = False
    alert_id = None
    if result.get("stage1") == "Abnormal":
        severity = _arrhythmia_severity(result.get("stage2_class"), result.get("stage1_confidence", 0))
        saved = await alert_manager.publish(
            db=db,
            patient_id=req.patient_id,
            alert_type="arrhythmia",
            severity=severity,
            details={
                "stage1":            result.get("stage1"),
                "stage2_class":      result.get("stage2_class"),
                "stage1_confidence": result.get("stage1_confidence"),
                "stage2_confidence": result.get("stage2_confidence"),
                "probabilities":     result.get("all_probabilities", {}),
                "submitted_by":      current_user.id,
            },
        )
        alert_id = saved.id
        alert_created = True

    return ECGAnalyzeResponse(
        alert_id          = alert_id,
        patient_id        = req.patient_id,
        stage1            = result.get("stage1"),
        stage1_confidence = result.get("stage1_confidence"),
        stage2_class      = result.get("stage2_class"),
        stage2_confidence = result.get("stage2_confidence"),
        all_probabilities = result.get("all_probabilities", {}),
        alert_created     = alert_created,
        error             = None,
    )


# ── GET /api/arrhythmia/history/{patient_id} ──────────────────────────────────
@router.get("/history/{patient_id}", response_model=list[AlertSummary])
def get_arrhythmia_history(
    patient_id: int,
    limit: int = 20,
    db: Session = Depends(get_db),
    _user = Depends(_clinical),
):
    """Return the most recent arrhythmia alerts for a patient."""
    if _user.role in (models.UserRole.doctor, models.UserRole.nurse):
        assigned = db.query(models.PatientAssignment).filter(
            models.PatientAssignment.patient_id == patient_id,
            models.PatientAssignment.user_id == _user.id
        ).first()
        if not assigned:
            raise HTTPException(status_code=403, detail='Access Denied: Patient is not assigned to you')

    return (
        db.query(models.Alert)
        .filter(
            models.Alert.patient_id == patient_id,
            models.Alert.alert_type == "arrhythmia",
        )
        .order_by(models.Alert.created_at.desc())
        .limit(limit)
        .all()
    )


def _arrhythmia_severity(stage2_class: Optional[str], confidence: float) -> str:
    """
    Map the arrhythmia type to a clinical severity level.
    AF is considered high-risk; IAVB is medium; others depend on confidence.
    """
    if stage2_class == "AF":
        return "high"
    if stage2_class == "IAVB":
        return "medium"
    if confidence >= 0.90:
        return "high"
    return "medium"
