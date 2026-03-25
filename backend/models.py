from sqlalchemy import Column, Integer, String, Text, Date, DateTime, Float, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base

class Doctor(Base):
    __tablename__ = 'doctors'

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String(100), nullable=False)
    email      = Column(String(100), unique=True, nullable=False)
    password   = Column(String(200), nullable=False)  # stored as bcrypt hash
    specialty  = Column(String(100))
    created_at = Column(DateTime, server_default=func.now())

class Patient(Base):
    __tablename__ = 'patients'

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String(100), nullable=False)
    dob        = Column(Date)
    gender     = Column(String(10))
    blood_type = Column(String(5))
    phone      = Column(String(20))
    created_at = Column(DateTime, server_default=func.now())

    visits      = relationship('Visit',      back_populates='patient')
    diagnoses   = relationship('Diagnosis',  back_populates='patient')
    medications = relationship('Medication', back_populates='patient')
    lab_results = relationship('LabResult',  back_populates='patient')
    allergies   = relationship('Allergy',    back_populates='patient')

class Visit(Base):
    __tablename__ = 'visits'

    id              = Column(Integer, primary_key=True, index=True)
    patient_id      = Column(Integer, ForeignKey('patients.id'), nullable=False)
    doctor_id       = Column(Integer, ForeignKey('doctors.id'))
    visit_date      = Column(Date, nullable=False)
    chief_complaint = Column(String(300))
    notes           = Column(Text)
    created_at      = Column(DateTime, server_default=func.now())

    patient = relationship('Patient', back_populates='visits')

class Diagnosis(Base):
    __tablename__ = 'diagnoses'

    id          = Column(Integer, primary_key=True, index=True)
    patient_id  = Column(Integer, ForeignKey('patients.id'), nullable=False)
    icd10_code  = Column(String(50))
    description = Column(Text, nullable=False)
    diagnosed_on= Column(Date)
    is_active   = Column(Boolean, default=True)
    severity    = Column(String(20))

    patient = relationship('Patient', back_populates='diagnoses')

class Medication(Base):
    __tablename__ = 'medications'

    id         = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey('patients.id'), nullable=False)
    drug_name  = Column(Text, nullable=False)
    dose       = Column(String(50))
    start_date = Column(Date)
    end_date   = Column(Date, nullable=True)
    is_active  = Column(Boolean, default=True)

    patient = relationship('Patient', back_populates='medications')

class LabResult(Base):
    __tablename__ = 'lab_results'

    id          = Column(Integer, primary_key=True, index=True)
    patient_id  = Column(Integer, ForeignKey('patients.id'), nullable=False)
    test_name   = Column(Text, nullable=False)
    value       = Column(Float)
    unit        = Column(String(30))
    reference   = Column(String(50))
    test_date   = Column(Date, nullable=False)
    is_abnormal = Column(Boolean, default=False)

    patient = relationship('Patient', back_populates='lab_results')

class Allergy(Base):
    __tablename__ = 'allergies'

    id         = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey('patients.id'), nullable=False)
    allergen   = Column(Text, nullable=False)
    reaction   = Column(String(200))
    severity   = Column(String(20))

    patient = relationship('Patient', back_populates='allergies')

class ChatLog(Base):
    __tablename__ = 'chat_logs'

    id               = Column(Integer, primary_key=True, index=True)
    doctor_id        = Column(Integer, ForeignKey('doctors.id'))
    patient_id       = Column(Integer, ForeignKey('patients.id'))
    query            = Column(Text)
    response         = Column(Text)
    intent_detected  = Column(String(50))
    created_at       = Column(DateTime, server_default=func.now())
