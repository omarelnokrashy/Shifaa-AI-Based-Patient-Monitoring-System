"""
RBAC-extended authentication module
=====================================
Extends the original auth.py with:
  - JWT payload that includes `user_id`, `role`, and `name`.
  - A reusable `require_role(*allowed_roles)` dependency factory that any
    router can use to gate endpoints by role.
  - `get_current_user()` as the new central dependency (replaces get_current_doctor).
  - `get_current_doctor()` is kept as an alias for backwards compat.

Role responsibilities (enforced at the router level):
  - doctor : full chat, patient data, view/acknowledge alerts, AI results
  - nurse  : view vitals/alerts, acknowledge alerts, limited chat
  - admin  : user management, system health, no clinical chat
"""

from datetime import datetime, timedelta
from typing import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
import os

from dotenv import load_dotenv
from .database import get_db
from . import models

load_dotenv()

SECRET_KEY   = os.getenv("SECRET_KEY")
ALGORITHM    = os.getenv("ALGORITHM", "HS256")
TOKEN_EXPIRE = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60))

pwd_ctx       = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ── Password helpers ───────────────────────────────────────────────────────────
def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)


def hash_password(plain: str) -> str:
    return pwd_ctx.hash(plain)


# ── Token creation ─────────────────────────────────────────────────────────────
def create_access_token(data: dict) -> str:
    """
    Create a signed JWT.  The `data` dict MUST include at least:
      - "sub"  : str(user_id)
      - "role" : user role string
      - "name" : display name
    """
    to_encode = data.copy()
    to_encode["sub"] = str(to_encode["sub"])
    to_encode["exp"] = datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRE)
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# ── Core dependency: get the currently authenticated user ──────────────────────
def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    """
    FastAPI dependency.  Decodes the Bearer JWT and returns the User ORM object.
    Raises 401 if the token is invalid, expired, or the user no longer exists/is inactive.
    """
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload  = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id  = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise exc

    user = db.query(models.User).filter(
        models.User.id == user_id,
        models.User.is_active == True,  # noqa: E712 — SQLAlchemy needs == not is
    ).first()
    if user is None:
        raise exc
    return user


# ── Role-based access dependency factory ──────────────────────────────────────
def require_role(*allowed_roles: str) -> Callable:
    """
    Returns a FastAPI dependency that ensures the current user's role is in
    the allowed list.  Usage in a router:

        @router.get("/admin/users")
        def list_users(user = Depends(require_role("admin"))):
            ...

        @router.post("/api/arrhythmia/analyze")
        def analyze(user = Depends(require_role("doctor", "nurse"))):
            ...
    """
    def _check(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role.value not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role.value}' is not permitted for this action. "
                       f"Required: {list(allowed_roles)}",
            )
        return user
    return _check


# ── Backwards-compatibility alias ─────────────────────────────────────────────
# Existing routers that call Depends(get_current_doctor) continue to work.
get_current_doctor = get_current_user


def get_current_user_from_token(token: str, db: Session) -> models.User:
    """
    Non-dependency version: accepts a raw JWT string.
    Used by multipart form endpoints (e.g. image upload) that cannot use
    the standard Bearer extraction mechanism.
    """
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError, TypeError):
        raise exc

    user = db.query(models.User).filter(
        models.User.id == user_id,
        models.User.is_active == True,  # noqa: E712
    ).first()
    if user is None:
        raise exc
    return user


# Backwards-compat alias for uploads router
get_current_doctor_from_token = get_current_user_from_token
