from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from .database import get_db
import os
from . import models
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY  = os.getenv('SECRET_KEY')
ALGORITHM   = os.getenv('ALGORITHM', 'HS256')
TOKEN_EXPIRE= int(os.getenv('ACCESS_TOKEN_EXPIRE_MINUTES', 60))

pwd_ctx = CryptContext(schemes=['bcrypt'], deprecated='auto')

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='/api/auth/login')

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    if 'sub' in to_encode:
        to_encode['sub'] = str(to_encode['sub'])
    expire = datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRE)
    to_encode.update({'exp': expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)



def get_current_doctor(token: str = Depends(oauth2_scheme),
                        db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail='Invalid or expired token',
        headers={'WWW-Authenticate': 'Bearer'},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        doctor_id_val = payload.get('sub')
        if doctor_id_val is None:
            raise credentials_exception
        doctor_id = int(doctor_id_val)
    except (JWTError, ValueError):
        raise credentials_exception




    doctor = db.query(models.Doctor).filter(models.Doctor.id == doctor_id).first()
    if doctor is None:
        raise credentials_exception
    return doctor


def get_current_doctor_from_token(token: str, db: Session):
    """Non-dependency version: accepts a raw JWT string. Used by multipart form endpoints."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail='Invalid or expired token',
    )
    try:
        payload   = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        doctor_id = int(payload.get('sub'))
    except (JWTError, ValueError, TypeError):
        raise credentials_exception
    doctor = db.query(models.Doctor).filter(models.Doctor.id == doctor_id).first()
    if doctor is None:
        raise credentials_exception
    return doctor
