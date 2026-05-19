from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, schemas
from ..auth import verify_password, create_access_token

router = APIRouter(prefix='/api/auth', tags=['auth'])

@router.post('/login', response_model=schemas.Token)
def login(request: schemas.LoginRequest, db: Session = Depends(get_db)):
    # Find the doctor by email
    doctor = db.query(models.Doctor).filter(models.Doctor.email == request.email).first()

    # If not found or wrong password, return 401 Unauthorized
    if not doctor or not verify_password(request.password, doctor.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Incorrect email or password'
        )

    # Create a JWT token containing the doctor's ID
    token = create_access_token(data={'sub': doctor.id})
    return {'access_token': token, 'token_type': 'bearer'}
