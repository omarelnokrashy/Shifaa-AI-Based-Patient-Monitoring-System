from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from ..database import get_db
from ..auth import get_current_doctor
from .. import models, schemas

router = APIRouter(prefix='/api/patients', tags=['patients'])

@router.get('', response_model=List[schemas.PatientOut])
def list_patients(
    search:     str           = '',
    gender:     Optional[str] = None,
    blood_type: Optional[str] = None,
    limit:      int           = 50,
    offset:     int           = 0,
    db:         Session       = Depends(get_db),
    doctor                    = Depends(get_current_doctor)
):
    """Search and filter patients. Supports name search, gender, and blood_type filters."""
    q = db.query(models.Patient)
    if search:
        q = q.filter(models.Patient.name.ilike(f'%{search}%'))
    if gender:
        q = q.filter(models.Patient.gender == gender)
    if blood_type:
        q = q.filter(models.Patient.blood_type == blood_type)
    return q.order_by(models.Patient.name).offset(offset).limit(limit).all()
@router.post('', response_model=schemas.PatientOut)
def create_patient(patient_in: schemas.PatientBase, db: Session = Depends(get_db),
                   doctor = Depends(get_current_doctor)):
    new_patient = models.Patient(**patient_in.dict())
    db.add(new_patient)
    db.commit()
    db.refresh(new_patient)
    return new_patient

@router.get('/{patient_id}', response_model=schemas.PatientFullOut)
def get_patient(patient_id: int, db: Session = Depends(get_db),
                doctor = Depends(get_current_doctor)):
    """Get full patient details including all medical history."""
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail='Patient not found')
    return patient

@router.get('/{patient_id}/medications', response_model=List[schemas.MedicationOut])
def get_medications(patient_id: int, active_only: bool = True,
                    db: Session = Depends(get_db),
                    doctor = Depends(get_current_doctor)):
    q = db.query(models.Medication).filter(models.Medication.patient_id == patient_id)
    if active_only:
        q = q.filter(models.Medication.is_active == True)
    return q.all()

@router.get('/{patient_id}/labs', response_model=List[schemas.LabResultOut])
def get_labs(patient_id: int, test_name: str = '',
             db: Session = Depends(get_db),
             doctor = Depends(get_current_doctor)):
    q = db.query(models.LabResult).filter(models.LabResult.patient_id == patient_id)
    if test_name:
        q = q.filter(models.LabResult.test_name.ilike(f'%{test_name}%'))
    return q.order_by(models.LabResult.test_date.desc()).all()

@router.get('/{patient_id}/diagnoses', response_model=List[schemas.DiagnosisOut])
def get_diagnoses(patient_id: int, db: Session = Depends(get_db),
                  doctor = Depends(get_current_doctor)):
    return db.query(models.Diagnosis).filter(
        models.Diagnosis.patient_id == patient_id
    ).all()
