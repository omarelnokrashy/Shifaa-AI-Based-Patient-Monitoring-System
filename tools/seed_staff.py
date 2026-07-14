"""
Script to create 5 new Doctors and 6 new Nurses, and assign them patients & rooms.
"""

import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import SessionLocal
from backend import models
from passlib.context import CryptContext
import random

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

DOCTORS_DATA = [
    {"name": "Dr. Sarah Al-Mansoor", "email": "drsarah@hospital.com", "password": "doctor123", "specialty": "Cardiology"},
    {"name": "Dr. Tariq Ziad", "email": "drtariq@hospital.com", "password": "doctor123", "specialty": "Neurology"},
    {"name": "Dr. Layla Mahmoud", "email": "drlayla@hospital.com", "password": "doctor123", "specialty": "Critical Care"},
    {"name": "Dr. Youssef Nader", "email": "dryoussef@hospital.com", "password": "doctor123", "specialty": "Internal Medicine"},
    {"name": "Dr. Mona El-Sayed", "email": "drmona@hospital.com", "password": "doctor123", "specialty": "Pulmonology"},
]

NURSES_DATA = [
    {"name": "Nurse Salma Khaled", "email": "nursesalma@hospital.com", "password": "nurse123"},
    {"name": "Nurse Karim Adel", "email": "nursekarim@hospital.com", "password": "nurse123"},
    {"name": "Nurse Hoda Tawfik", "email": "nursehoda@hospital.com", "password": "nurse123"},
    {"name": "Nurse Omar Farouk", "email": "nurseomar@hospital.com", "password": "nurse123"},
    {"name": "Nurse Dina Sherif", "email": "nursedina@hospital.com", "password": "nurse123"},
    {"name": "Nurse Rania Mostafa", "email": "nurserania@hospital.com", "password": "nurse123"},
]

def seed_staff_and_assign():
    db = SessionLocal()
    try:
        print("Creating 5 Doctors...")
        new_doctors = []
        for d in DOCTORS_DATA:
            existing = db.query(models.User).filter(models.User.email == d["email"]).first()
            if not existing:
                doc = models.User(
                    name=d["name"],
                    email=d["email"],
                    password=pwd_context.hash(d["password"]),
                    role=models.UserRole.doctor,
                    specialty=d["specialty"]
                )
                db.add(doc)
                db.flush()
                new_doctors.append(doc)
                print(f"  [OK] Created Doctor: {doc.name} ({doc.email})")
            else:
                new_doctors.append(existing)
                print(f"  [EXISTS] Doctor: {existing.name}")

        print("\nCreating 6 Nurses...")
        new_nurses = []
        for n in NURSES_DATA:
            existing = db.query(models.User).filter(models.User.email == n["email"]).first()
            if not existing:
                nurse = models.User(
                    name=n["name"],
                    email=n["email"],
                    password=pwd_context.hash(n["password"]),
                    role=models.UserRole.nurse,
                    specialty=None
                )
                db.add(nurse)
                db.flush()
                new_nurses.append(nurse)
                print(f"  [OK] Created Nurse: {nurse.name} ({nurse.email})")
            else:
                new_nurses.append(existing)
                print(f"  [EXISTS] Nurse: {existing.name}")

        db.commit()

        # Get all patients for assignments
        patients = db.query(models.Patient).all()
        print(f"\nDistributing assignments across {len(patients)} patients...")

        # Assign 20-30 random patients to each new doctor and nurse
        all_staff = new_doctors + new_nurses
        assignment_count = 0

        for staff in all_staff:
            assigned_patients = random.sample(patients, min(50, len(patients)))
            for patient in assigned_patients:
                # check existing assignment
                exists = db.query(models.PatientAssignment).filter(
                    models.PatientAssignment.user_id == staff.id,
                    models.PatientAssignment.patient_id == patient.id
                ).first()
                if not exists:
                    pa = models.PatientAssignment(user_id=staff.id, patient_id=patient.id)
                    db.add(pa)
                    assignment_count += 1

        print(f"  [OK] Added {assignment_count} new patient assignments.")

        # Assign nurses to active rooms
        rooms = db.query(models.Room).all()
        print(f"\nAssigning new nurses to {len(rooms)} hospital rooms...")
        for i, room in enumerate(rooms):
            assigned_nurse = new_nurses[i % len(new_nurses)]
            if assigned_nurse not in room.nurses:
                room.nurses.append(assigned_nurse)
                print(f"  [OK] Assigned {assigned_nurse.name} to Room {room.room_number}")

        db.commit()
        print("\n[SUCCESS] Doctor and Nurse generation and assignments completed!")

    except Exception as e:
        print(f"[ERROR] Seeding staff failed: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_staff_and_assign()
