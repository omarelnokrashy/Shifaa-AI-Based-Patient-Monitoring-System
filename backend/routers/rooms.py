"""
Rooms router — CRUD operations, patient/nurse/service assignments, and room status aggregation
========================================================================================
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from ..database import get_db
from ..auth import require_role, get_current_user
from .. import models

log = logging.getLogger("rooms-router")
router = APIRouter(prefix="/api/rooms", tags=["Rooms"])

# RBAC dependencies
_admin_only = require_role("admin")
_clinical_or_admin = require_role("doctor", "nurse", "admin")
_doctor_or_admin = require_role("doctor", "admin")

# ── Schemas ───────────────────────────────────────────────────────────────────
class RoomServiceCreate(BaseModel):
    service_name: str

class RoomNurseOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    class Config:
        from_attributes = True

class RoomPatientOut(BaseModel):
    id: int
    name: str
    dob: Optional[str] = None
    gender: Optional[str] = None
    blood_type: Optional[str] = None
    class Config:
        from_attributes = True

class RoomServiceOut(BaseModel):
    service_name: str
    class Config:
        from_attributes = True

class RoomOut(BaseModel):
    id: int
    room_number: str
    room_name: Optional[str] = None
    patient_id: Optional[int] = None
    floor: Optional[str] = None
    monitoring_status: str
    created_at: datetime
    updated_at: datetime
    patient: Optional[RoomPatientOut] = None
    services: List[str] = []
    nurses: List[RoomNurseOut] = []
    active_alerts: List[dict] = []
    risk_score: float = 0.0

    class Config:
        from_attributes = True

class RoomCreateRequest(BaseModel):
    room_number: str
    room_name: Optional[str] = None
    floor: Optional[str] = None
    patient_id: Optional[int] = None
    services: List[str] = []  # e.g., ["ecg", "seizure", "fall"]
    nurse_ids: List[int] = []

class RoomUpdateRequest(BaseModel):
    room_number: str
    room_name: Optional[str] = None
    floor: Optional[str] = None
    patient_id: Optional[int] = None
    services: List[str] = []
    nurse_ids: List[int] = []

class AssignPatientRequest(BaseModel):
    patient_id: Optional[int] = None

class AssignNursesRequest(BaseModel):
    nurse_ids: List[int]

class AssignServicesRequest(BaseModel):
    services: List[str]

# ── Helper functions ──────────────────────────────────────────────────────────
def compute_room_status_and_alerts(db: Session, room: models.Room) -> tuple[str, List[dict], float]:
    """
    Computes real-time room status, risk score, and lists active alerts
    for the patient currently assigned to the room.
    """
    if not room.patient_id:
        return "Idle", [], 0.0

    # Get active alerts for the patient
    active_alerts = db.query(models.Alert).filter(
        models.Alert.patient_id == room.patient_id,
        models.Alert.status == "ACTIVE"
    ).all()

    alerts_list = []
    status_str = "Monitoring"
    max_risk = 0.0

    for alert in active_alerts:
        details = alert.details or {}
        # Try to extract risk score / probability
        risk = 0.0
        if alert.alert_type == "fall":
            risk = details.get("fall_probability", 1.0)
        elif alert.alert_type == "seizure":
            risk = details.get("gate_score", 1.0)
        elif alert.alert_type == "arrhythmia":
            risk = details.get("stage1_confidence", 1.0)
        
        max_risk = max(max_risk, risk)
        
        alerts_list.append({
            "id": alert.id,
            "alert_type": alert.alert_type.value if hasattr(alert.alert_type, "value") else str(alert.alert_type),
            "severity": alert.severity.value if hasattr(alert.severity, "value") else str(alert.severity),
            "details": details,
            "created_at": alert.created_at.isoformat() if alert.created_at else None
        })

    # Set overall room status based on alerts and services
    if alerts_list:
        has_critical = any(a["severity"] == "critical" or a["severity"] == "high" for a in alerts_list)
        if has_critical:
            status_str = "Critical Alert"
        else:
            status_str = "Warning"
    else:
        # If no alerts, check if services are enabled
        if not room.services:
            status_str = "Idle"
        else:
            # Check if any monitoring session is initializing (fallback to DB state)
            if room.monitoring_status == "Initializing":
                status_str = "Initializing"
            else:
                status_str = "Monitoring"

    # Handle offline case manually if flagged
    if room.monitoring_status in ["Offline", "Disconnected"]:
        status_str = room.monitoring_status

    return status_str, alerts_list, max_risk

def serialize_room(db: Session, room: models.Room) -> RoomOut:
    status_str, alerts_list, risk = compute_room_status_and_alerts(db, room)
    
    # Map services to flat string list
    flat_services = [s.service_name for s in room.services]
    
    # Map nurses
    nurses_out = [
        RoomNurseOut(id=n.id, name=n.name, email=n.email, role=n.role.value if hasattr(n.role, "value") else str(n.role))
        for n in room.nurses
    ]
    
    # Map patient
    patient_out = None
    if room.patient:
        patient_out = RoomPatientOut(
            id=room.patient.id,
            name=room.patient.name,
            dob=room.patient.dob.isoformat() if room.patient.dob else None,
            gender=room.patient.gender,
            blood_type=room.patient.blood_type
        )

    return RoomOut(
        id=room.id,
        room_number=room.room_number,
        room_name=room.room_name,
        patient_id=room.patient_id,
        floor=room.floor,
        monitoring_status=status_str,
        created_at=room.created_at,
        updated_at=room.updated_at,
        patient=patient_out,
        services=flat_services,
        nurses=nurses_out,
        active_alerts=alerts_list,
        risk_score=risk
    )

# ── REST Endpoints ────────────────────────────────────────────────────────────

@router.get("", response_model=List[RoomOut])
async def list_rooms(
    search: str = "",
    service: str = "",
    nurse_id: Optional[int] = None,
    status_filter: str = "",
    floor: str = "",
    sort_by: str = "room_number",  # room_number, patient_name, alert_priority, recent_alert, highest_risk
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_clinical_or_admin),
):
    """
    List all rooms.
    * Nurses can only see rooms assigned to them.
    * Doctors and Admins can see all rooms.
    * Supports search, filter, and sorting.
    """
    q = db.query(models.Room)

    # 1. Access boundaries: Nurses see only assigned rooms
    if current_user.role == models.UserRole.nurse:
        q = q.join(models.Room.nurses).filter(models.User.id == current_user.id)

    # 2. Search
    if search:
        search_terms = [
            models.Room.room_number.ilike(f"%{search}%"),
            models.Room.room_name.ilike(f"%{search}%")
        ]
        if search.isdigit():
            search_terms.append(models.Room.patient_id == int(search))
        
        # Search by patient name
        search_terms.append(models.Room.patient.has(models.Patient.name.ilike(f"%{search}%")))
        # Search by nurse name
        search_terms.append(models.Room.nurses.any(models.User.name.ilike(f"%{search}%")))
        
        q = q.filter(or_(*search_terms))

    # 3. Filtering
    if service:
        q = q.join(models.Room.services).filter(models.RoomService.service_name == service.lower())
    
    if nurse_id:
        q = q.filter(models.Room.nurses.any(models.User.id == nurse_id))
        
    if floor:
        q = q.filter(models.Room.floor == floor)

    rooms = q.distinct().all()

    # 4. Serialize rooms to calculate active alerts, computed status, and risk scores
    serialized_rooms = [serialize_room(db, r) for r in rooms]

    # Post-filtering for computed status (since status is computed dynamically)
    if status_filter:
        serialized_rooms = [
            r for r in serialized_rooms
            if r.monitoring_status.lower() == status_filter.lower()
        ]

    # 5. Sorting
    def get_status_priority(status_val: str) -> int:
        mapping = {
            "Critical Alert": 4,
            "Warning": 3,
            "Monitoring": 2,
            "Initializing": 1,
            "Idle": 0,
            "Offline": -1,
            "Disconnected": -1
        }
        return mapping.get(status_val, 0)

    if sort_by == "room_number":
        serialized_rooms.sort(key=lambda x: x.room_number)
    elif sort_by == "patient_name":
        serialized_rooms.sort(key=lambda x: (x.patient.name if x.patient else "zzz"))
    elif sort_by == "alert_priority":
        serialized_rooms.sort(key=lambda x: get_status_priority(x.monitoring_status), reverse=True)
    elif sort_by == "highest_risk":
        serialized_rooms.sort(key=lambda x: x.risk_score, reverse=True)
    elif sort_by == "recent_alert":
        def get_recent_alert_time(r: RoomOut):
            if not r.active_alerts:
                return "0"
            times = [a.get("created_at") or "0" for a in r.active_alerts]
            return max(times)
        serialized_rooms.sort(key=get_recent_alert_time, reverse=True)

    return serialized_rooms

@router.get("/{room_id}", response_model=RoomOut)
async def get_room(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_clinical_or_admin),
):
    """Fetch details of a single room."""
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Enforce nurse confidentiality
    if current_user.role == models.UserRole.nurse:
        assigned_nurse = db.query(models.Room).join(models.Room.nurses).filter(
            models.Room.id == room_id,
            models.User.id == current_user.id
        ).first()
        if not assigned_nurse:
            raise HTTPException(status_code=403, detail="Access Denied: Room is not assigned to you")

    return serialize_room(db, room)

@router.post("", response_model=RoomOut, status_code=status.HTTP_201_CREATED)
async def create_room(
    req: RoomCreateRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_admin_only),
):
    """Create a new room configuration (Admin only)."""
    # Check if room number already exists
    existing = db.query(models.Room).filter(models.Room.room_number == req.room_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="Room number already exists")

    # Verify patient exists if provided
    if req.patient_id:
        patient = db.query(models.Patient).filter(models.Patient.id == req.patient_id).first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")

    new_room = models.Room(
        room_number=req.room_number,
        room_name=req.room_name,
        floor=req.floor,
        patient_id=req.patient_id,
        monitoring_status="Idle"
    )
    db.add(new_room)
    db.flush()

    # Assign services
    for s_name in req.services:
        svc = models.RoomService(room_id=new_room.id, service_name=s_name.lower())
        db.add(svc)

    # Assign nurses
    if req.nurse_ids:
        nurses = db.query(models.User).filter(
            models.User.id.in_(req.nurse_ids),
            models.User.role == models.UserRole.nurse
        ).all()
        new_room.nurses.extend(nurses)

    db.commit()
    db.refresh(new_room)

    # Trigger live ws update
    await trigger_room_ws_broadcast(db, new_room)

    return serialize_room(db, new_room)

@router.put("/{room_id}", response_model=RoomOut)
async def update_room(
    room_id: int,
    req: RoomUpdateRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_admin_only),
):
    """Update existing room config (Admin only)."""
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Check number conflict
    if req.room_number != room.room_number:
        conflict = db.query(models.Room).filter(models.Room.room_number == req.room_number).first()
        if conflict:
            raise HTTPException(status_code=400, detail="Room number already exists")

    # Verify patient
    if req.patient_id:
        patient = db.query(models.Patient).filter(models.Patient.id == req.patient_id).first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")

    # Update basic fields
    room.room_number = req.room_number
    room.room_name = req.room_name
    room.floor = req.floor
    room.patient_id = req.patient_id

    # Update services
    db.query(models.RoomService).filter(models.RoomService.room_id == room.id).delete()
    for s_name in req.services:
        svc = models.RoomService(room_id=room.id, service_name=s_name.lower())
        db.add(svc)

    # Update nurses
    room.nurses.clear()
    if req.nurse_ids:
        nurses = db.query(models.User).filter(
            models.User.id.in_(req.nurse_ids),
            models.User.role == models.UserRole.nurse
        ).all()
        room.nurses.extend(nurses)

    db.commit()
    db.refresh(room)

    # Trigger live ws update
    await trigger_room_ws_broadcast(db, room)

    return serialize_room(db, room)

@router.delete("/{room_id}")
async def delete_room(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_admin_only),
):
    """Delete a room (Admin only)."""
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Trigger delete event before deleting
    from ..services.alert_manager import alert_manager
    await alert_manager.broadcast_event(db, room.patient_id or 0, {
        "type": "room_delete",
        "room_id": room.id
    })

    db.delete(room)
    db.commit()
    return {"status": "success", "detail": f"Room {room_id} deleted."}

@router.post("/{room_id}/assign-patient", response_model=RoomOut)
async def assign_patient(
    room_id: int,
    req: AssignPatientRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_doctor_or_admin),
):
    """Assign or change patient assigned to a room (Doctor/Admin)."""
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    if req.patient_id:
        patient = db.query(models.Patient).filter(models.Patient.id == req.patient_id).first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")
        # Remove from any other room first (ensure one patient per room)
        db.query(models.Room).filter(
            models.Room.patient_id == req.patient_id,
            models.Room.id != room_id
        ).update({models.Room.patient_id: None})

    room.patient_id = req.patient_id
    db.commit()
    db.refresh(room)

    # Broadcast updates
    await trigger_room_ws_broadcast(db, room)

    return serialize_room(db, room)

@router.post("/{room_id}/assign-nurses", response_model=RoomOut)
async def assign_nurses(
    room_id: int,
    req: AssignNursesRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_admin_only),
):
    """Assign multiple nurses to a room (Admin only)."""
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    room.nurses.clear()
    if req.nurse_ids:
        nurses = db.query(models.User).filter(
            models.User.id.in_(req.nurse_ids),
            models.User.role == models.UserRole.nurse
        ).all()
        room.nurses.extend(nurses)

    db.commit()
    db.refresh(room)

    # Broadcast updates
    await trigger_room_ws_broadcast(db, room)

    return serialize_room(db, room)

@router.post("/{room_id}/assign-services", response_model=RoomOut)
async def assign_services(
    room_id: int,
    req: AssignServicesRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_admin_only),
):
    """Assign services to a room (Admin only)."""
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    db.query(models.RoomService).filter(models.RoomService.room_id == room.id).delete()
    for s_name in req.services:
        svc = models.RoomService(room_id=room.id, service_name=s_name.lower())
        db.add(svc)

    db.commit()
    db.refresh(room)

    # Broadcast updates
    await trigger_room_ws_broadcast(db, room)

    return serialize_room(db, room)

# ── Live Broadcast helper ─────────────────────────────────────────────────────
async def trigger_room_ws_broadcast(db: Session, room: models.Room):
    """Broadcast real-time room configuration and status updates to all listeners."""
    from ..services.alert_manager import alert_manager
    serialized = serialize_room(db, room)
    
    # Broadcast to websocket clients
    await alert_manager.broadcast_event(db, room.patient_id or 0, {
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
