"""
Database seeder
-----------------
Creates one test account per role (doctor, nurse, admin) plus 10 synthetic
patients with realistic medical histories.

Run with:
    python -m backend.seed
"""

from .database import SessionLocal, engine, Base
from . import models
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

    db.close()
    print("\n✅ Seeding complete!")
    print("\nTest credentials:")
    for u in _ROLES_TO_CREATE:
        print(f"  [{u['role']:6s}]  {u['email']}  /  {u['password']}")


if __name__ == "__main__":
    run_seed()
