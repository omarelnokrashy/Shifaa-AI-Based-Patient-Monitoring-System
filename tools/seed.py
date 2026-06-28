"""
Database seeder
-----------------
Creates one test account per role (doctor, nurse, admin) plus 10 synthetic
patients with realistic medical histories.

Run with:
    python -m backend.seed
"""

import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import SessionLocal, engine, Base
from backend import models
from faker import Faker
from passlib.context import CryptContext
from datetime import date, timedelta
import random

_ROLES_TO_CREATE = [
    {
        "name":      "Dr. Ahmed Hassan",
        "email":     "doctor@hospital.com",
        "password":  "doctor123",
        "role":      "doctor",
        "specialty": "Internal Medicine",
    },
    {
        "name":      "Nurse Sara Mohamed",
        "email":     "nurse@hospital.com",
        "password":  "nurse123",
        "role":      "nurse",
        "specialty": None,
    },
    {
        "name":      "Admin Omar Nour",
        "email":     "admin@hospital.com",
        "password":  "admin123",
        "role":      "admin",
        "specialty": None,
    },
]


def run_seed():
    """
    Populate the database with test data.

    Phase 1 — Users: creates one user per role (doctor, nurse, admin) using the
    credentials defined in ``_ROLES_TO_CREATE``.  Existing users with the same
    e-mail are skipped rather than duplicated.

    Phase 2 — Patients: generates 10 synthetic patients via Faker, each with
    2 random diagnoses, 2 medications, 3 visits, 2 lab results, and optionally
    one allergy.
    """
    Base.metadata.create_all(engine)
    fake    = Faker()
    pwd_ctx = CryptContext(schemes=["bcrypt"])
    db      = SessionLocal()

    # ── Create test users (one per role) ─────────────────────────────────────
    created_users = {}
    for u in _ROLES_TO_CREATE:
        existing = db.query(models.User).filter(models.User.email == u["email"]).first()
        if existing:
            print(f"User already exists: {u['email']} (skipping)")
            created_users[u["role"]] = existing
            continue

        user = models.User(
            name      = u["name"],
            email     = u["email"],
            password  = pwd_ctx.hash(u["password"]),
            role      = u["role"],
            specialty = u["specialty"],
            is_active = True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        created_users[u["role"]] = user
        print(f"Created [{u['role']}]: {u['email']} / {u['password']}")

    doctor = created_users.get("doctor")

    # ── Create 10 synthetic patients ──────────────────────────────────────────
    conditions = [
        ("Type 2 Diabetes Mellitus", "E11"),
        ("Hypertension",             "I10"),
        ("Chronic Kidney Disease",   "N18"),
        ("Asthma",                   "J45"),
        ("Hypothyroidism",           "E03"),
    ]
    meds_list = [
        ("Metformin",         "500mg twice daily"),
        ("Amlodipine",        "5mg once daily"),
        ("Atorvastatin",      "20mg at night"),
        ("Levothyroxine",     "50mcg once daily"),
        ("Salbutamol inhaler","2 puffs as needed"),
        ("Lisinopril",        "10mg once daily"),
    ]
    labs_list = [
        ("HbA1c",                "%",       "4.0-5.6"),
        ("Fasting Blood Glucose","mg/dL",   "70-100"),
        ("Creatinine",           "mg/dL",   "0.6-1.2"),
        ("Hemoglobin",           "g/dL",    "13.5-17.5"),
        ("TSH",                  "mIU/L",   "0.4-4.0"),
    ]

    for i in range(10):
        patient = models.Patient(
            name       = fake.name(),
            dob        = fake.date_of_birth(minimum_age=30, maximum_age=75),
            gender     = random.choice(["Male", "Female"]),
            blood_type = random.choice(["A+","A-","B+","B-","AB+","O+","O-"]),
            phone      = fake.phone_number()[:20],
        )
        db.add(patient)
        db.commit()
        db.refresh(patient)

        for cond, code in random.sample(conditions, 2):
            db.add(models.Diagnosis(
                patient_id   = patient.id,
                description  = cond,
                icd10_code   = code,
                diagnosed_on = fake.date_between(start_date="-3y", end_date="today"),
                is_active    = True,
                severity     = random.choice(["mild","moderate","severe"]),
            ))

        for drug, dose in random.sample(meds_list, 2):
            db.add(models.Medication(
                patient_id = patient.id,
                drug_name  = drug,
                dose       = dose,
                start_date = fake.date_between(start_date="-2y", end_date="-30d"),
                is_active  = True,
            ))

        for _ in range(3):
            db.add(models.Visit(
                patient_id      = patient.id,
                doctor_id       = doctor.id if doctor else None,
                visit_date      = fake.date_between(start_date="-1y", end_date="today"),
                chief_complaint = random.choice([
                    "Routine check-up","Follow-up for diabetes",
                    "Blood pressure control","Fatigue","Shortness of breath",
                ]),
                notes = fake.paragraph(nb_sentences=4),
            ))

        for test, unit, ref in random.sample(labs_list, 2):
            val = round(random.uniform(4.0, 12.0), 1)
            db.add(models.LabResult(
                patient_id  = patient.id,
                test_name   = test,
                value       = val,
                unit        = unit,
                reference   = ref,
                test_date   = fake.date_between(start_date="-6m", end_date="today"),
                is_abnormal = random.choice([True, False]),
            ))

        if random.random() > 0.5:
            db.add(models.Allergy(
                patient_id = patient.id,
                allergen   = random.choice(["Penicillin","Sulfa drugs","Aspirin","Ibuprofen","Latex"]),
                reaction   = random.choice(["Rash","Anaphylaxis","Hives","Angioedema"]),
                severity   = random.choice(["mild","moderate","severe"]),
            ))

        db.commit()
        print(f"Patient {i+1}: {patient.name} (ID: {patient.id})")

    # ── Assign patients to doctors and nurses randomly ───────────────────────
    print("\nCreating random patient assignments...")
    patients = db.query(models.Patient).all()
    doctors = db.query(models.User).filter(models.User.role == "doctor", models.User.is_active == True).all()
    nurses = db.query(models.User).filter(models.User.role == "nurse", models.User.is_active == True).all()

    if patients and (doctors or nurses):
        assignments_created = 0
        def add_assignment(u_id, p_id):
            nonlocal assignments_created
            exists = db.query(models.PatientAssignment).filter(
                models.PatientAssignment.user_id == u_id,
                models.PatientAssignment.patient_id == p_id
            ).first()
            if not exists:
                db.add(models.PatientAssignment(user_id=u_id, patient_id=p_id))
                assignments_created += 1

        if doctors:
            for doc in doctors:
                assigned_pts = random.sample(patients, min(3, len(patients)))
                for p in assigned_pts:
                    add_assignment(doc.id, p.id)

        if nurses:
            for nurse in nurses:
                assigned_pts = random.sample(patients, min(3, len(patients)))
                for p in assigned_pts:
                    add_assignment(nurse.id, p.id)

        if doctors:
            for p in patients:
                has_doc = db.query(models.PatientAssignment).join(models.User).filter(
                    models.PatientAssignment.patient_id == p.id,
                    models.User.role == "doctor"
                ).first()
                if not has_doc:
                    random_doc = random.choice(doctors)
                    add_assignment(random_doc.id, p.id)

        if nurses:
            for p in patients:
                has_nurse = db.query(models.PatientAssignment).join(models.User).filter(
                    models.PatientAssignment.patient_id == p.id,
                    models.User.role == "nurse"
                ).first()
                if not has_nurse:
                    random_nurse = random.choice(nurses)
                    add_assignment(random_nurse.id, p.id)

        db.commit()
        print(f"Created {assignments_created} random patient assignments.")

    db.close()
    print("\n[OK] Seeding complete!")
    print("\nTest credentials:")
    for u in _ROLES_TO_CREATE:
        print(f"  [{u['role']:6s}]  {u['email']}  /  {u['password']}")


if __name__ == "__main__":
    run_seed()
