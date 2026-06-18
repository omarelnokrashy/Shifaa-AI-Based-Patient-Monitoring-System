from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, schemas
from ..auth import verify_password, create_access_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=schemas.Token)
def login(request: schemas.LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate a user (doctor, nurse, or admin) and return a signed JWT.

    The JWT payload includes:
      - sub  : user id (as string, per JWT spec)
      - role : "doctor" | "nurse" | "admin"
      - name : display name (used by the frontend header)

    This enriched payload is needed by the RBAC dependency (require_role)
    and by the frontend to show the correct navigation options per role.
    """
    # Look up by email in the unified users table
    user = (
        db.query(models.User)
        .filter(models.User.email == request.email, models.User.is_active == True)  # noqa: E712
        .first()
    )

    if not user or not verify_password(request.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    # Include role and name in the JWT so the frontend and RBAC layer can use them
    token = create_access_token(data={
        "sub":  user.id,
        "role": user.role.value,
        "name": user.name,
    })
    return {"access_token": token, "token_type": "bearer"}
