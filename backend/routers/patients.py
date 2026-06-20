"""
Patient records router
-----------------------
CRUD and sub-resource endpoints for patient data, accessible to authenticated
doctors (scoped to their own assigned patients) and nurses.

Endpoints
---------
GET    /api/patients                         — search and filter patient list
POST   /api/patients                         — register a new patient
GET    /api/patients/{patient_id}            — full patient profile
GET    /api/patients/{patient_id}/medications — medication list (active by default)
GET    /api/patients/{patient_id}/labs        — lab results (searchable by test name)
GET    /api/patients/{patient_id}/diagnoses   — diagnosis history
"""

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
    if doctor.role in (models.UserRole.doctor, models.UserRole.nurse):
        q = q.join(models.PatientAssignment).filter(models.PatientAssignment.user_id == doctor.id).distinct()

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
    """
    Register a new patient in the system.

    Any authenticated doctor or nurse can create a patient record;
    role-based visit scoping is applied on read operations.
    """
    new_patient = models.Patient(**patient_in.dict())
    db.add(new_patient)
    db.commit()
    db.refresh(new_patient)
    return new_patient

@router.get('/{patient_id}', response_model=schemas.PatientFullOut)
def get_patient(patient_id: int, db: Session = Depends(get_db),
                 doctor = Depends(get_current_doctor)):
    """Get full patient details including all medical history."""
    q = db.query(models.Patient)
    if doctor.role in (models.UserRole.doctor, models.UserRole.nurse):
        q = q.join(models.PatientAssignment).filter(models.PatientAssignment.user_id == doctor.id)
    patient = q.filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail='Patient not found or not assigned to you')
    return patient

@router.get('/{patient_id}/medications', response_model=List[schemas.MedicationOut])
def get_medications(patient_id: int, active_only: bool = True,
                     db: Session = Depends(get_db),
                     doctor = Depends(get_current_doctor)):
    """
    Return the medication list for a patient.

    By default only active medications are returned; pass ``active_only=false``
    to include discontinued medications.  Doctors are restricted to patients
    assigned to them via a visit record.
    """
    if doctor.role in (models.UserRole.doctor, models.UserRole.nurse):
        assigned = db.query(models.PatientAssignment).filter(
            models.PatientAssignment.patient_id == patient_id,
            models.PatientAssignment.user_id == doctor.id
        ).first()
        if not assigned:
            raise HTTPException(status_code=403, detail='Access Denied: Patient is not assigned to you')
    q = db.query(models.Medication).filter(models.Medication.patient_id == patient_id)
    if active_only:
        q = q.filter(models.Medication.is_active == True)
    return q.all()

@router.get('/{patient_id}/labs', response_model=List[schemas.LabResultOut])
def get_labs(patient_id: int, test_name: str = '',
              db: Session = Depends(get_db),
              doctor = Depends(get_current_doctor)):
    """
    Return lab results for a patient, ordered by test date descending.

    Optionally filter by ``test_name`` (case-insensitive substring match).
    Doctors are restricted to patients assigned to them via a visit record.
    """
    if doctor.role in (models.UserRole.doctor, models.UserRole.nurse):
        assigned = db.query(models.PatientAssignment).filter(
            models.PatientAssignment.patient_id == patient_id,
            models.PatientAssignment.user_id == doctor.id
        ).first()
        if not assigned:
            raise HTTPException(status_code=403, detail='Access Denied: Patient is not assigned to you')
    q = db.query(models.LabResult).filter(models.LabResult.patient_id == patient_id)
    if test_name:
        q = q.filter(models.LabResult.test_name.ilike(f'%{test_name}%'))
    return q.order_by(models.LabResult.test_date.desc()).all()

@router.get('/{patient_id}/diagnoses', response_model=List[schemas.DiagnosisOut])
def get_diagnoses(patient_id: int, db: Session = Depends(get_db),
                   doctor = Depends(get_current_doctor)):
    """
    Return all recorded diagnoses for a patient.

    Doctors are restricted to patients assigned to them via a visit record.
    """
    if doctor.role in (models.UserRole.doctor, models.UserRole.nurse):
        assigned = db.query(models.PatientAssignment).filter(
            models.PatientAssignment.patient_id == patient_id,
            models.PatientAssignment.user_id == doctor.id
        ).first()
        if not assigned:
            raise HTTPException(status_code=403, detail='Access Denied: Patient is not assigned to you')
    return db.query(models.Diagnosis).filter(
        models.Diagnosis.patient_id == patient_id
    ).order_by(models.Diagnosis.diagnosed_on.desc()).all()

@router.get('/{patient_id}/alerts', response_model=List[schemas.AlertOut])
def get_patient_alerts(patient_id: int, db: Session = Depends(get_db),
                       doctor = Depends(get_current_doctor)):
    """
    Return all alerts for a patient.

    Doctors are restricted to patients assigned to them via a visit record.
    Nurses and admins can access alerts for any patient.
    """
    if doctor.role in (models.UserRole.doctor, models.UserRole.nurse):
        assigned = db.query(models.PatientAssignment).filter(
            models.PatientAssignment.patient_id == patient_id,
            models.PatientAssignment.user_id == doctor.id
        ).first()
        if not assigned:
            raise HTTPException(status_code=403, detail='Access Denied: Patient is not assigned to you')

    alerts = db.query(models.Alert).filter(
        models.Alert.patient_id == patient_id
    ).order_by(models.Alert.created_at.desc()).all()

    res = []
    for a in alerts:
        res.append({
            "id": a.id,
            "patient_id": a.patient_id,
            "alert_type": a.alert_type,
            "severity": a.severity,
            "details": a.details,
            "created_at": a.created_at,
            "acknowledged_by": a.acknowledged_by,
            "acknowledged_at": a.acknowledged_at,
            "acknowledged": a.acknowledged_by is not None,
            "patient_name": a.patient.name if a.patient else None
        })
    return res

