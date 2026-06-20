"""
Admin user management router
------------------------------
Provides endpoints to list, create, and deactivate system users (doctor / nurse /
admin accounts).  All endpoints are gated to the "admin" role only.

Endpoints
---------
GET    /api/admin/users              → list all users
POST   /api/admin/users              → create a new user account
PATCH  /api/admin/users/{id}/deactivate  → soft-delete (set is_active=False)
PATCH  /api/admin/users/{id}/activate    → re-enable a deactivated account
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from ..database import get_db
from ..auth import require_role
from .. import models

router = APIRouter(prefix="/api/admin", tags=["Admin"])

_admin_only = require_role("admin")


# ── Schemas ────────────────────────────────────────────────────────────────────
class UserCreateRequest(BaseModel):
    """
    Payload for creating a new system user account.

    ``role`` must be one of ``doctor``, ``nurse``, or ``admin``.
    ``specialty`` is optional and relevant only for doctor accounts.
    """
    name:      str
    email:     str           # EmailStr requires email-validator; using plain str for simplicity
    password:  str
    role:      str           # "doctor" | "nurse" | "admin"
    specialty: Optional[str] = None


class UserOut(BaseModel):
    """Serialised user record returned by list and create endpoints."""
    id:         int
    name:       str
    email:      str
    role:       str
    specialty:  Optional[str]
    is_active:  bool
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


# ── GET /api/admin/users ───────────────────────────────────────────────────────
@router.get("/users", response_model=list[UserOut])
def list_users(
    role: Optional[str] = None,
    db: Session = Depends(get_db),
    _admin = Depends(_admin_only),
):
    """Return all user accounts.  Optionally filter by role=doctor|nurse|admin."""
    q = db.query(models.User)
    if role:
        q = q.filter(models.User.role == role)
    return q.order_by(models.User.created_at.desc()).all()


# ── POST /api/admin/users ──────────────────────────────────────────────────────
@router.post("/users", response_model=UserOut)
def create_user(
    req: UserCreateRequest,
    db: Session = Depends(get_db),
    _admin = Depends(_admin_only),
):
    """
    Create a new user account (doctor, nurse, or admin).
    Passwords are bcrypt-hashed before storage.
    """
    if req.role not in ("doctor", "nurse", "admin"):
        raise HTTPException(status_code=422, detail="role must be doctor | nurse | admin")

    # Check email uniqueness
    if db.query(models.User).filter(models.User.email == req.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    from ..auth import hash_password
    user = models.User(
        name      = req.name,
        email     = req.email,
        password  = hash_password(req.password),
        role      = req.role,
        specialty = req.specialty,
        is_active = True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ── PATCH /api/admin/users/{id}/deactivate ────────────────────────────────────
@router.patch("/users/{user_id}/deactivate", response_model=UserOut)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(_admin_only),
):
    """
    Soft-delete a user account.  The user can no longer log in but historical
    data (chat logs, visit records) referencing their ID is preserved.
    Admins cannot deactivate themselves.
    """
    if user_id == current_admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    db.commit()
    db.refresh(user)
    return user


# ── PATCH /api/admin/users/{id}/activate ──────────────────────────────────────
@router.patch("/users/{user_id}/activate", response_model=UserOut)
def activate_user(
    user_id: int,
    db: Session = Depends(get_db),
    _admin = Depends(_admin_only),
):
    """Re-enable a previously deactivated user account."""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = True
    db.commit()
    db.refresh(user)
    return user


# ── POST /api/admin/assign-patients ───────────────────────────────────────────
@router.post("/assign-patients")
def assign_patients(
    db: Session = Depends(get_db),
    _admin = Depends(_admin_only),
):
    """
    Randomly assign patients to all active doctors and nurses.
    Clears all previous assignments first.
    Ensures every active doctor/nurse gets assigned 3 random patients (if available),
    and that every patient is assigned to at least one doctor and one nurse.
    """
    import random

    # Clear all existing assignments
    db.query(models.PatientAssignment).delete()

    patients = db.query(models.Patient).all()
    doctors = db.query(models.User).filter(models.User.role == "doctor", models.User.is_active == True).all()
    nurses = db.query(models.User).filter(models.User.role == "nurse", models.User.is_active == True).all()

    if not patients:
        db.commit()
        return {"message": "No patients found in the database. No assignments created."}

    if not doctors and not nurses:
        db.commit()
        return {"message": "No active doctors or nurses found. No assignments created."}

    assignments_created = 0

    # Helper to create assignment
    def add_assignment(u_id, p_id):
        nonlocal assignments_created
        # Check if already exists
        exists = db.query(models.PatientAssignment).filter(
            models.PatientAssignment.user_id == u_id,
            models.PatientAssignment.patient_id == p_id
        ).first()
        if not exists:
            db.add(models.PatientAssignment(user_id=u_id, patient_id=p_id))
            assignments_created += 1

    # 1. Assign to active doctors
    if doctors:
        for doc in doctors:
            # Choose min(3, len(patients)) random patients
            assigned_pts = random.sample(patients, min(3, len(patients)))
            for p in assigned_pts:
                add_assignment(doc.id, p.id)

    # 2. Assign to active nurses
    if nurses:
        for nurse in nurses:
            assigned_pts = random.sample(patients, min(3, len(patients)))
            for p in assigned_pts:
                add_assignment(nurse.id, p.id)

    # 3. Ensure every patient is assigned to at least one doctor
    if doctors:
        for p in patients:
            has_doc = db.query(models.PatientAssignment).join(models.User).filter(
                models.PatientAssignment.patient_id == p.id,
                models.User.role == "doctor"
            ).first()
            if not has_doc:
                random_doc = random.choice(doctors)
                add_assignment(random_doc.id, p.id)

    # 4. Ensure every patient is assigned to at least one nurse
    if nurses:
        for p in patients:
            has_nurse = db.query(models.PatientAssignment).join(models.User).filter(
                models.PatientAssignment.patient_id == p.id,
                models.User.role == "nurse"
            ).first()
            if not has_nurse:
                random_nurse = random.choice(nurses)
                add_assignment(random_nurse.id, p.id)

    db.commit()
    return {
        "status": "success",
        "message": f"Randomized patient assignments created successfully. Created {assignments_created} assignments."
    }

