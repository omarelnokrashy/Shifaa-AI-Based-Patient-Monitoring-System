from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional, List

# ----- Auth -----
class LoginRequest(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = 'bearer'

# ----- Patients -----
class PatientBase(BaseModel):
    name: str
    dob: Optional[date]
    gender: Optional[str]
    blood_type: Optional[str]
    phone: Optional[str]

class PatientOut(PatientBase):
    id: int
    created_at: Optional[datetime]
    class Config:
        from_attributes = True

# ----- Medical data -----
class DiagnosisOut(BaseModel):
    id: int
    description: str
    icd10_code: Optional[str]
    diagnosed_on: Optional[date]
    is_active: bool
    severity: Optional[str]
    class Config:
        from_attributes = True

class MedicationOut(BaseModel):
    id: int
    drug_name: str
    dose: Optional[str]
    start_date: Optional[date]
    end_date: Optional[date]
    is_active: bool
    class Config:
        from_attributes = True

class LabResultOut(BaseModel):
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
    id: int
    allergen: str
    reaction: Optional[str]
    severity: Optional[str]
    class Config:
        from_attributes = True

class VisitOut(BaseModel):
    id: int
    visit_date: date
    chief_complaint: Optional[str]
    notes: Optional[str]
    class Config:
        from_attributes = True

class PatientFullOut(PatientOut):
    diagnoses:   List[DiagnosisOut]  = []
    medications: List[MedicationOut] = []
    lab_results: List[LabResultOut]  = []
    allergies:   List[AllergyOut]    = []
    visits:      List[VisitOut]      = []

# ----- Chat -----
class ChatRequest(BaseModel):
    query: str
    patient_id: int

class ChatResponse(BaseModel):
    answer: str
    intent: str
    sources: List[str]
