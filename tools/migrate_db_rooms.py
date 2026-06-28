"""
Migration & Seeding Script for Rooms, Services, and Nurses Tables.
=================================================================
Creates tables 'rooms', 'room_services', and 'room_nurses' if they don't exist
and populates them with initial mock ward configurations.
"""

import os
import sys
from pathlib import Path

# Add the project root to python path to resolve 'backend' package imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from backend.database import Base, engine, SessionLocal
from backend import models

def migrate_and_seed():
    print("Starting database migration for Rooms...")
    
    # 1. Create tables
    Base.metadata.create_all(bind=engine)
    print("[OK] Created tables: rooms, room_services, room_nurses.")

    db = SessionLocal()
    try:
        # 2. Query existing nurses and patients to seed relationships
        nurses = db.query(models.User).filter(models.User.role == models.UserRole.nurse).all()
        patients = db.query(models.Patient).all()

        print(f"Found {len(nurses)} nurses and {len(patients)} patients in the database.")

        # Helper to get nurse by index safely
        def get_nurse(idx):
            return [nurses[idx]] if idx < len(nurses) else []

        # Helper to get patient ID safely
        def get_patient_id(idx):
            return patients[idx].id if idx < len(patients) else None

        # 3. Define default room templates
        default_rooms = [
            {
                "room_number": "101",
                "room_name": "ICU Bed A",
                "floor": "1",
                "patient_id": get_patient_id(0),
                "services": ["ecg", "seizure"],
                "nurses": get_nurse(0),
                "status": "Monitoring"
            },
            {
                "room_number": "102",
                "room_name": "ICU Bed B",
                "floor": "1",
                "patient_id": get_patient_id(1),
                "services": ["fall"],
                "nurses": get_nurse(1) if len(nurses) > 1 else get_nurse(0),
                "status": "Monitoring"
            },
            {
                "room_number": "103",
                "room_name": "Ward Room A",
                "floor": "1",
                "patient_id": None,
                "services": ["ecg"],
                "nurses": [],
                "status": "Idle"
            },
            {
                "room_number": "201",
                "room_name": "Neurology Suite",
                "floor": "2",
                "patient_id": get_patient_id(2),
                "services": ["ecg", "seizure", "fall"],
                "nurses": nurses[:2], # assign first two nurses
                "status": "Monitoring"
            },
            {
                "room_number": "202",
                "room_name": "General Ward A",
                "floor": "2",
                "patient_id": get_patient_id(3),
                "services": ["seizure"],
                "nurses": get_nurse(0),
                "status": "Monitoring"
            },
            {
                "room_number": "203",
                "room_name": "General Ward B",
                "floor": "2",
                "patient_id": None,
                "services": ["fall"],
                "nurses": get_nurse(1) if len(nurses) > 1 else get_nurse(0),
                "status": "Idle"
            }
        ]

        # 4. Insert rooms if they don't already exist
        for r_data in default_rooms:
            existing = db.query(models.Room).filter(models.Room.room_number == r_data["room_number"]).first()
            if existing:
                print(f"Room {r_data['room_number']} already exists, skipping seeding.")
                continue

            room = models.Room(
                room_number=r_data["room_number"],
                room_name=r_data["room_name"],
                floor=r_data["floor"],
                patient_id=r_data["patient_id"],
                monitoring_status=r_data["status"]
            )
            db.add(room)
            db.flush() # gets room.id

            # Add services
            for s_name in r_data["services"]:
                svc = models.RoomService(room_id=room.id, service_name=s_name)
                db.add(svc)

            # Add nurses
            for nurse in r_data["nurses"]:
                room.nurses.append(nurse)

            print(f"[OK] Seeded Room {room.room_number} ({room.room_name}) with services {r_data['services']}.")

        db.commit()
        print("Database migration & seeding completed successfully!")

    except Exception as exc:
        print(f"[ERROR] Migration failed: {exc}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    migrate_and_seed()
