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
    name:      str
    email:     str           # EmailStr requires email-validator; using plain str for simplicity
    password:  str
    role:      str           # "doctor" | "nurse" | "admin"
    specialty: Optional[str] = None


class UserOut(BaseModel):
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
