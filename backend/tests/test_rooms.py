import os
import sys
import unittest
from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.main import app
from backend.database import Base, get_db
from backend.auth import get_current_user
from backend import models
from backend.routers.rooms import serialize_room

# Setup temporary SQLite DB file
DB_FILE = "./test_rooms_db.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_FILE}"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Active mock user (will be dynamically mutated per test case to simulate roles)
active_mock_user = models.User(
    id=1,
    name="System Administrator",
    email="admin@hospital.com",
    role=models.UserRole.admin,
    is_active=True
)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

def override_get_current_user():
    return active_mock_user

# Apply FastAPI overrides
app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_current_user] = override_get_current_user


class TestRoomsAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        try:
            if os.path.exists(DB_FILE):
                os.remove(DB_FILE)
        except Exception:
            pass

    def setUp(self):
        global active_mock_user
        # Reset current mock user to Admin by default
        active_mock_user = models.User(
            id=1,
            name="System Administrator",
            email="admin@hospital.com",
            role=models.UserRole.admin,
            is_active=True
        )

        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.db = TestingSessionLocal()

        # Seed users (1 Admin, 1 Doctor, 2 Nurses)
        self.admin_user = models.User(id=1, name="System Admin", email="admin@h.com", role=models.UserRole.admin, password="x")
        self.doctor_user = models.User(id=2, name="Dr. Ahmed", email="doctor@h.com", role=models.UserRole.doctor, password="x")
        self.nurse_1 = models.User(id=3, name="Nurse Sara", email="nurse1@h.com", role=models.UserRole.nurse, password="x")
        self.nurse_2 = models.User(id=4, name="Nurse Mona", email="nurse2@h.com", role=models.UserRole.nurse, password="x")
        
        self.db.add_all([self.admin_user, self.doctor_user, self.nurse_1, self.nurse_2])

        # Seed patients
        self.p1 = models.Patient(id=1, name="John Doe", dob=datetime.strptime("1990-01-01", "%Y-%m-%d").date(), gender="male")
        self.p2 = models.Patient(id=2, name="Jane Smith", dob=datetime.strptime("1992-05-10", "%Y-%m-%d").date(), gender="female")
        self.db.add_all([self.p1, self.p2])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_create_and_read_room(self):
        """Verify Admin can create and retrieve rooms."""
        # Post request to create Room 101
        payload = {
            "room_number": "101",
            "room_name": "ICU Bed 1",
            "floor": "1",
            "patient_id": 1,
            "services": ["ecg", "seizure"],
            "nurse_ids": [3]
        }
        res = self.client.post("/api/rooms", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["room_number"], "101")
        self.assertEqual(data["patient_id"], 1)
        self.assertIn("ecg", data["services"])
        self.assertEqual(len(data["nurses"]), 1)
        self.assertEqual(data["nurses"][0]["id"], 3)

        # GET single room details
        res_get = self.client.get(f"/api/rooms/{data['id']}")
        self.assertEqual(res_get.status_code, 200)
        self.assertEqual(res_get.json()["room_name"], "ICU Bed 1")

    def test_nurse_gated_visibility(self):
        """Verify Nurses can ONLY see rooms they are explicitly assigned to."""
        # Create Room 101 assigned to Nurse 1 (Sara)
        room_101 = models.Room(id=1, room_number="101", floor="1", patient_id=1)
        room_101.nurses.append(self.nurse_1)
        
        # Create Room 102 assigned to Nurse 2 (Mona)
        room_102 = models.Room(id=2, room_number="102", floor="1", patient_id=2)
        room_102.nurses.append(self.nurse_2)

        self.db.add_all([room_101, room_102])
        self.db.commit()

        # Switch context to Nurse 1 (Sara)
        global active_mock_user
        active_mock_user = self.nurse_1

        # Retrieve room list
        res = self.client.get("/api/rooms")
        self.assertEqual(res.status_code, 200)
        rooms_list = res.json()
        
        # Nurse 1 should see exactly 1 room (101), and NOT room 102
        self.assertEqual(len(rooms_list), 1)
        self.assertEqual(rooms_list[0]["room_number"], "101")

        # Trying to fetch details of unassigned room 102 direct should throw 403 Access Denied
        res_detail = self.client.get("/api/rooms/2")
        self.assertEqual(res_detail.status_code, 403)

    def test_doctor_clearance(self):
        """Verify Doctors can see all rooms in the ward."""
        room_101 = models.Room(id=1, room_number="101", patient_id=1)
        room_102 = models.Room(id=2, room_number="102", patient_id=2)
        self.db.add_all([room_101, room_102])
        self.db.commit()

        # Switch context to Doctor
        global active_mock_user
        active_mock_user = self.doctor_user

        # Retrieve room list
        res = self.client.get("/api/rooms")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()), 2)

    def test_many_to_many_nurses(self):
        """Verify many-to-many mapping: multiple nurses per room, multiple rooms per nurse."""
        room_101 = models.Room(id=1, room_number="101")
        room_102 = models.Room(id=2, room_number="102")
        self.db.add_all([room_101, room_102])
        self.db.commit()

        # Assign Nurse 1 to BOTH rooms
        room_101.nurses.append(self.nurse_1)
        room_102.nurses.append(self.nurse_1)
        # Assign Nurse 2 to Room 101 as well (so room 101 has multiple nurses)
        room_101.nurses.append(self.nurse_2)
        self.db.commit()

        # Check Room 101 nurses count
        self.assertEqual(len(room_101.nurses), 2)
        # Check Nurse 1 assigned rooms count
        self.assertEqual(len(self.nurse_1.rooms), 2)

    def test_patient_assignment_does_not_affect_services(self):
        """Changing the patient must never affect room services or nurse configuration."""
        room = models.Room(id=1, room_number="101", patient_id=1)
        svc = models.RoomService(room_id=1, service_name="ecg")
        room.nurses.append(self.nurse_1)
        self.db.add_all([room, svc])
        self.db.commit()

        # Update patient assignment
        res = self.client.post("/api/rooms/1/assign-patient", json={"patient_id": 2})
        self.assertEqual(res.status_code, 200)
        
        # Verify patient is updated but services and nurses remain untouched
        data = res.json()
        self.assertEqual(data["patient_id"], 2)
        self.assertIn("ecg", data["services"])
        self.assertEqual(len(data["nurses"]), 1)
        self.assertEqual(data["nurses"][0]["id"], 3)

    def test_alert_severity_status_escalation(self):
        """Verify room status updates to 'Critical Alert' when an active alert triggers."""
        room = models.Room(id=1, room_number="101", patient_id=1)
        svc = models.RoomService(room_id=1, service_name="ecg")
        self.db.add_all([room, svc])
        self.db.commit()

        # Initial serialized state should be Monitoring (since a patient is assigned and no alerts)
        serialized = serialize_room(self.db, room)
        self.assertEqual(serialized.monitoring_status, "Monitoring")

        # Create active critical seizure alert for Patient 1
        alert = models.Alert(
            patient_id=1,
            alert_type=models.AlertType.seizure,
            severity=models.AlertSeverity.critical,
            status="ACTIVE"
        )
        self.db.add(alert)
        self.db.commit()

        # Serialized state should now automatically escalate to Critical Alert
        serialized = serialize_room(self.db, room)
        self.assertEqual(serialized.monitoring_status, "Critical Alert")
        self.assertEqual(len(serialized.active_alerts), 1)

        # Deleting/Acknowledging the alert should return room to Monitoring status
        self.db.delete(alert)
        self.db.commit()
        
        serialized = serialize_room(self.db, room)
        self.assertEqual(serialized.monitoring_status, "Monitoring")
        self.assertEqual(len(serialized.active_alerts), 0)


if __name__ == "__main__":
    unittest.main()
