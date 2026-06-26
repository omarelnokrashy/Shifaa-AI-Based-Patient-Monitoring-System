"""
schemas.py — Pydantic request / response schemas
=================================================
Defines the data-transfer objects (DTOs) used by the API layer.  Each class
describes the shape of JSON data that the API accepts or returns, decoupled
from the underlying SQLAlchemy ORM models.
"""
from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional, List

# ----- Auth -----
class LoginRequest(BaseModel):
    """Payload required to authenticate a user and obtain a JWT."""
    email: str
    password: str

class Token(BaseModel):
    """JWT token returned after a successful login."""
    access_token: str
    token_type: str = 'bearer'

# ----- Patients -----
class PatientBase(BaseModel):
    """Core patient demographics shared by create and read schemas."""
    name: str
    dob: Optional[date]
    gender: Optional[str]
    blood_type: Optional[str]
    phone: Optional[str]

class PatientOut(PatientBase):
    """Patient record returned by the API, including the database-assigned ``id``."""
    id: int
    created_at: Optional[datetime]
    class Config:
        from_attributes = True

# ----- Medical data -----
class DiagnosisOut(BaseModel):
    """Serialised diagnosis record for a patient, including ICD-10 code and severity."""
    id: int
    description: str
    icd10_code: Optional[str]
    diagnosed_on: Optional[date]
    is_active: bool
    severity: Optional[str]
    class Config:
        from_attributes = True

class MedicationOut(BaseModel):
    """Serialised medication record showing drug name, dosage, and active status."""
    id: int
    drug_name: str
    dose: Optional[str]
    start_date: Optional[date]
    end_date: Optional[date]
    is_active: bool
    class Config:
        from_attributes = True

class LabResultOut(BaseModel):
    """Serialised laboratory result including test value, units, and abnormality flag."""
    id: int
    test_name: str
    value: Optional[float]
    unit: Optional[str]
    reference: Optional[str]
    test_date: date
    is_abnormal: bool
    class Config:
        from_attributes = True

class AllergyOut(BaseModel):
    """Serialised allergy record with allergen name, expected reaction, and severity."""
    id: int
    allergen: str
    reaction: Optional[str]
    severity: Optional[str]
    class Config:
        from_attributes = True

class VisitOut(BaseModel):
    """Serialised clinic visit record with date, chief complaint, and clinical notes."""
    id: int
    visit_date: date
    chief_complaint: Optional[str]
    notes: Optional[str]
    class Config:
        from_attributes = True

class AlertOut(BaseModel):
    """Serialised clinical alert including type, severity, patient name, and acknowledgment status."""
    id: int
    patient_id: int
    alert_type: str
    severity: str
    details: Optional[dict] = None
    created_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    acknowledged: bool = False
    patient_name: Optional[str] = None
    alert_id: Optional[int] = None
    class Config:
        from_attributes = True

class PatientFullOut(PatientOut):
    """
    Extended patient response that bundles all related medical records:
    diagnoses, medications, lab results, allergies, and visit history.
    """
    diagnoses:   List[DiagnosisOut]  = []
    medications: List[MedicationOut] = []
    lab_results: List[LabResultOut]  = []
    allergies:   List[AllergyOut]    = []
    visits:      List[VisitOut]      = []

# ----- Chat -----
class ChatRequest(BaseModel):
    """Request body for querying the AI chatbot about a specific patient."""
    query: str
    patient_id: int

class ChatResponse(BaseModel):
    """Response from the AI chatbot containing the answer, detected intent, and source references."""
    answer: str
    intent: str
    sources: List[str]

class ChatLogOut(BaseModel):
    """Serialized format of a single chat database record."""
    id: int
    doctor_id: Optional[int]
    patient_id: Optional[int]
    query: Optional[str]
    response: Optional[str]
    intent_detected: Optional[str]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True

