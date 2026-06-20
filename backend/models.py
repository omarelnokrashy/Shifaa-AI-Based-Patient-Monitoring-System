"""
ORM Models — Medical Monitoring System
========================================
Covers:
  - Original chatbot tables (Doctor → now User with role, Patient, Visit, …)
  - New tables: User (replaces Doctor with RBAC), Alert, VitalSign
  - Doctor is kept as a SQLAlchemy alias / view of User where role='doctor'
    for backwards compatibility with existing routers.

Schema evolution notes:
  - The `doctors` table is RENAMED to `users` in new deployments.
    Existing deployments can run `backend/migrate_doctor_to_user.py` (provided
    separately) which does:  ALTER TABLE doctors RENAME TO users;
                             ALTER TABLE users ADD COLUMN role VARCHAR(10) DEFAULT 'doctor';
  - All FK references in visits / chat_logs that previously pointed at
    `doctors.id` now point at `users.id`; the column name stays doctor_id so
    existing queries continue to work.
"""

from sqlalchemy import (
    Column, Integer, String, Text, Date, DateTime, Float,
    ForeignKey, Boolean, JSON, Enum, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base
import enum


# ── Enumerations ──────────────────────────────────────────────────────────────
class UserRole(str, enum.Enum):
    """Permitted role values for a user account, used to gate API access."""
    doctor = "doctor"
    nurse  = "nurse"
    admin  = "admin"


class AlertType(str, enum.Enum):
    """Classifier label for an AI-generated clinical alert."""
    arrhythmia = "arrhythmia"
    fall       = "fall"
    seizure    = "seizure"


class AlertSeverity(str, enum.Enum):
    """Clinical severity level assigned to an alert by the inference engine."""
    low      = "low"
    medium   = "medium"
    high     = "high"
    critical = "critical"


# ── User (replaces the old Doctor table, adds role column) ────────────────────
class User(Base):
    """
    Unified user table for doctors, nurses, and admins.
    Previously called 'Doctor'; the table is now 'users' and includes a `role`
    column that gates access to specific API endpoints.
    """
    __tablename__ = "users"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String(100), nullable=False)
    email      = Column(String(100), unique=True, nullable=False, index=True)
    password   = Column(String(200), nullable=False)   # bcrypt hash
    specialty  = Column(String(100))                   # relevant for doctors
    role       = Column(
        Enum(UserRole, name="user_role"),
        nullable=False,
        default=UserRole.doctor,
        index=True,
    )
    is_active  = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    chat_logs    = relationship("ChatLog", back_populates="doctor",
                                foreign_keys="ChatLog.doctor_id")
    visits       = relationship("Visit",   back_populates="doctor",
                                foreign_keys="Visit.doctor_id")
    acknowledged = relationship("Alert",   back_populates="acknowledger",
                                foreign_keys="Alert.acknowledged_by")


# Backwards-compat alias: existing code that imports `models.Doctor` still works.
Doctor = User


# ── Patient ────────────────────────────────────────────────────────────────────
class Patient(Base):
    """
    Core patient demographic record.  All clinical sub-tables (diagnoses,
    medications, lab results, allergies, visits, alerts, and vital signs)
    reference this table via ``patient_id``.
    """
    __tablename__ = "patients"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String(100), nullable=False)
    dob        = Column(Date)
    gender     = Column(String(10))
    blood_type = Column(String(5))
    phone      = Column(String(20))
    created_at = Column(DateTime, server_default=func.now())

    visits      = relationship("Visit",      back_populates="patient")
    diagnoses   = relationship("Diagnosis",  back_populates="patient")
    medications = relationship("Medication", back_populates="patient")
    lab_results = relationship("LabResult",  back_populates="patient")
    allergies   = relationship("Allergy",    back_populates="patient")
    alerts      = relationship("Alert",      back_populates="patient")
    vital_signs = relationship("VitalSign",  back_populates="patient")


# ── Visit ──────────────────────────────────────────────────────────────────────
class Visit(Base):
    """
    A single clinical encounter between a patient and a doctor.
    Records the date, chief complaint, and free-text clinical notes.
    """
    __tablename__ = "visits"

    id              = Column(Integer, primary_key=True, index=True)
    patient_id      = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id       = Column(Integer, ForeignKey("users.id"))
    visit_date      = Column(Date, nullable=False)
    chief_complaint = Column(String(300))
    notes           = Column(Text)
    created_at      = Column(DateTime, server_default=func.now())

    patient = relationship("Patient", back_populates="visits")
    doctor  = relationship("User",    back_populates="visits",
                           foreign_keys=[doctor_id])


# ── Diagnosis ──────────────────────────────────────────────────────────────────
class Diagnosis(Base):
    """
    A clinical diagnosis linked to a patient, optionally coded with an ICD-10 code.
    ``is_active`` distinguishes current from resolved conditions.
    """
    __tablename__ = "diagnoses"

    id           = Column(Integer, primary_key=True, index=True)
    patient_id   = Column(Integer, ForeignKey("patients.id"), nullable=False)
    icd10_code   = Column(String(50))
    description  = Column(Text, nullable=False)
    diagnosed_on = Column(Date)
    is_active    = Column(Boolean, default=True)
    severity     = Column(String(20))

    patient = relationship("Patient", back_populates="diagnoses")


# ── Medication ─────────────────────────────────────────────────────────────────
class Medication(Base):
    """
    A medication prescribed to a patient, with dosage and active/inactive status.
    ``end_date`` is ``NULL`` for ongoing prescriptions.
    """
    __tablename__ = "medications"

    id         = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    drug_name  = Column(Text, nullable=False)
    dose       = Column(String(50))
    start_date = Column(Date)
    end_date   = Column(Date, nullable=True)
    is_active  = Column(Boolean, default=True)

    patient = relationship("Patient", back_populates="medications")


# ── LabResult ──────────────────────────────────────────────────────────────────
class LabResult(Base):
    """
    A single laboratory test result for a patient.
    ``is_abnormal`` is set by the importing process based on the reference range.
    """
    __tablename__ = "lab_results"

    id          = Column(Integer, primary_key=True, index=True)
    patient_id  = Column(Integer, ForeignKey("patients.id"), nullable=False)
    test_name   = Column(Text, nullable=False)
    value       = Column(Float)
    unit        = Column(String(30))
    reference   = Column(String(50))
    test_date   = Column(Date, nullable=False)
    is_abnormal = Column(Boolean, default=False)

    patient = relationship("Patient", back_populates="lab_results")


# ── Allergy ────────────────────────────────────────────────────────────────────
class Allergy(Base):
    """
    A known drug or substance allergy for a patient, including the expected
    reaction and its severity.
    """
    __tablename__ = "allergies"

    id         = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    allergen   = Column(Text, nullable=False)
    reaction   = Column(String(200))
    severity   = Column(String(20))

    patient = relationship("Patient", back_populates="allergies")


# ── ChatLog ────────────────────────────────────────────────────────────────────
class ChatLog(Base):
    """
    Persistent log of every chatbot interaction.  Stores the raw query,
    the generated response, and the intent label detected by the NLU layer.
    """
    __tablename__ = "chat_logs"

    id              = Column(Integer, primary_key=True, index=True)
    doctor_id       = Column(Integer, ForeignKey("users.id"))
    patient_id      = Column(Integer, ForeignKey("patients.id"))
    query           = Column(Text)
    response        = Column(Text)
    intent_detected = Column(String(50))
    created_at      = Column(DateTime, server_default=func.now())

    doctor = relationship("User",    back_populates="chat_logs",
                          foreign_keys=[doctor_id])


# ── Alert ──────────────────────────────────────────────────────────────────────
class Alert(Base):
    """
    Stores every clinical alert generated by the AI monitoring modules.
    `details` is a free-form JSON blob containing the raw inference output
    (probabilities, gate scores, fall probabilities, etc.) so that the
    data is never lost even if the schema evolves.
    """
    __tablename__ = "alerts"

    id              = Column(Integer, primary_key=True, index=True)
    patient_id      = Column(Integer, ForeignKey("patients.id"), nullable=False)
    alert_type      = Column(
        Enum(AlertType, name="alert_type"),
        nullable=False,
    )
    severity        = Column(
        Enum(AlertSeverity, name="alert_severity"),
        nullable=False,
        default=AlertSeverity.medium,
    )
    details         = Column(JSON, nullable=True)        # raw inference output
    acknowledged_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    created_at      = Column(DateTime, server_default=func.now())

    patient     = relationship("Patient", back_populates="alerts")
    acknowledger = relationship("User",   back_populates="acknowledged",
                                foreign_keys=[acknowledged_by])


# Composite indexes for the most common alert queries
Index("idx_alerts_patient_created", Alert.patient_id, Alert.created_at)
Index("idx_alerts_type_severity",   Alert.alert_type, Alert.severity)


# ── VitalSign ──────────────────────────────────────────────────────────────────
class VitalSign(Base):
    """
    Time-series vital sign readings linked to a patient.
    Each row represents one measurement from a device or inference engine.
    `source` identifies the device class (ecg, camera, sensor_hub, etc.).
    """
    __tablename__ = "vital_signs"

    id          = Column(Integer, primary_key=True, index=True)
    patient_id  = Column(Integer, ForeignKey("patients.id"), nullable=False)
    source      = Column(String(50), nullable=False)        # e.g. "ecg", "camera", "sensor"
    metric      = Column(String(50), nullable=False)        # e.g. "heart_rate", "spo2"
    value       = Column(Float, nullable=True)
    unit        = Column(String(20), nullable=True)
    raw_payload = Column(JSON, nullable=True)               # full inference output for audit
    recorded_at = Column(DateTime, server_default=func.now())

    patient = relationship("Patient", back_populates="vital_signs")


# Composite index for time-series queries
Index("idx_vitals_patient_metric_time", VitalSign.patient_id, VitalSign.metric, VitalSign.recorded_at)


# ── PatientAssignment ─────────────────────────────────────────────────────────
class PatientAssignment(Base):
    """
    Tracks assignments of patients to doctors/nurses.
    Provides data confidentiality partitioning.
    """
    __tablename__ = "patient_assignments"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    patient_id  = Column(Integer, ForeignKey("patients.id"), nullable=False)
    assigned_at = Column(DateTime, server_default=func.now())

    user        = relationship("User", backref="assignments")
    patient     = relationship("Patient", backref="assignments")

