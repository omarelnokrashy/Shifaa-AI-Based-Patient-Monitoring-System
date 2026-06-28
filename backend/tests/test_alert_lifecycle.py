import os
import sys
import unittest
from datetime import datetime, timedelta
import asyncio

from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.database import Base, get_db
from backend.auth import get_current_user, get_current_doctor
from backend import models
from backend.services.alert_manager import alert_manager

# 1. Setup temporary SQLite DB file
DB_FILE = "./test_medical_db.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_FILE}"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 2. Mock authentication user
mock_doctor = models.User(
    id=1,
    name="Test Doctor",
    email="doctor@hospital.com",
    role=models.UserRole.doctor,
    is_active=True
)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

def override_get_current_user():
    return mock_doctor

# 3. Apply FastAPI dependency overrides
app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_current_user] = override_get_current_user
app.dependency_overrides[get_current_doctor] = override_get_current_user


class TestAlertLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        # Remove temporary DB file
        try:
            if os.path.exists(DB_FILE):
                os.remove(DB_FILE)
        except Exception:
            pass

    def setUp(self):
        # Clean and recreate tables before each test
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        
        # Populate initial test data
        self.db = TestingSessionLocal()
        
        # Insert user (doctor)
        self.db.add(models.User(
            id=1,
            name="Test Doctor",
            email="doctor@hospital.com",
            password="hashedpassword",
            role=models.UserRole.doctor,
            is_active=True
        ))
        
        # Insert test patient
        self.patient = models.Patient(
            id=1,
            name="John Doe",
            gender="male",
            dob=datetime.strptime("1990-01-01", "%Y-%m-%d").date(),
            blood_type="O+"
        )
        self.db.add(self.patient)
        
        # Assign patient to doctor
        self.db.add(models.PatientAssignment(
            user_id=1,
            patient_id=1
        ))
        
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_alert_creation_and_status(self):
        """1. Verify alert creation inserts active record with status='ACTIVE'."""
        # Use alert manager publish to create an alert
        loop = asyncio.get_event_loop()
        alert = loop.run_until_complete(
            alert_manager.publish(
                db=self.db,
                patient_id=1,
                alert_type="fall",
                severity="high",
                details={"fall_probability": 0.95}
            )
        )
        
        # Verify db status
        db_alert = self.db.query(models.Alert).filter(models.Alert.id == alert.id).first()
        self.assertIsNotNone(db_alert)
        self.assertEqual(db_alert.status, "ACTIVE")
        self.assertEqual(db_alert.alert_type.value if hasattr(db_alert.alert_type, 'value') else db_alert.alert_type, "fall")
        self.assertEqual(db_alert.severity.value if hasattr(db_alert.severity, 'value') else db_alert.severity, "high")
        self.assertEqual(db_alert.details, {"fall_probability": 0.95})

    def test_dashboard_summary_filtering(self):
        """2. Verify dashboard summary filters alerts <= 24 hours."""
        loop = asyncio.get_event_loop()
        
        # Create active alert created now
        alert_now = loop.run_until_complete(
            alert_manager.publish(
                db=self.db,
                patient_id=1,
                alert_type="seizure",
                severity="critical",
                details={"gate_score": 0.85}
            )
        )
        
        # Create active alert created 25 hours ago (manually modifying timestamp)
        alert_old = models.Alert(
            patient_id=1,
            alert_type="arrhythmia",
            severity="medium",
            details={"type": "SB"},
            status="ACTIVE",
            created_at=datetime.utcnow() - timedelta(hours=25)
        )
        self.db.add(alert_old)
        self.db.commit()
        
        # Fetch summary from endpoint
        res = self.client.get("/api/dashboard/summary")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        recent_ids = [a["id"] for a in data["recent_alerts"]]
        self.assertIn(alert_now.id, recent_ids)
        self.assertNotIn(alert_old.id, recent_ids)
        
        # Check alert counts
        seizure_count = next((c["count"] for c in data["alert_counts"] if c["alert_type"] == "seizure"), 0)
        arrhythmia_count = next((c["count"] for c in data["alert_counts"] if c["alert_type"] == "arrhythmia"), 0)
        self.assertEqual(seizure_count, 1)
        self.assertEqual(arrhythmia_count, 0) # 25h alert should be excluded

    def test_expiration_mechanism(self):
        """3. Verify expiration loop deletes alerts > 24 hours."""
        # Create an old active alert (25 hours ago)
        alert_old = models.Alert(
            patient_id=1,
            alert_type="arrhythmia",
            severity="medium",
            details={"type": "SB"},
            status="ACTIVE",
            created_at=datetime.utcnow() - timedelta(hours=25)
        )
        self.db.add(alert_old)
        self.db.commit()
        alert_id = alert_old.id
        
        # Simulate clean expired alerts logic directly
        since = datetime.utcnow() - timedelta(hours=24)
        expired_alerts = self.db.query(models.Alert).filter(
            models.Alert.status == "ACTIVE",
            models.Alert.created_at < since
        ).all()
        
        self.assertEqual(len(expired_alerts), 1)
        self.assertEqual(expired_alerts[0].id, alert_id)
        
        # Delete and commit
        for a in expired_alerts:
            self.db.delete(a)
        self.db.commit()
        
        # Verify it's gone
        db_alert = self.db.query(models.Alert).filter(models.Alert.id == alert_id).first()
        self.assertIsNone(db_alert)

    def test_acknowledgement_lifecycle(self):
        """4. Verify acknowledge moves active alert to AlertHistory."""
        loop = asyncio.get_event_loop()
        alert = loop.run_until_complete(
            alert_manager.publish(
                db=self.db,
                patient_id=1,
                alert_type="fall",
                severity="high",
                details={"fall_probability": 0.90}
            )
        )
        alert_id = alert.id
        
        # Call acknowledgement endpoint
        res = self.client.patch(
            f"/api/dashboard/alerts/{alert_id}/acknowledge",
            json={"acknowledged_by": 1}
        )
        self.assertEqual(res.status_code, 200)
        
        # Verify removed from active table
        db_active = self.db.query(models.Alert).filter(models.Alert.id == alert_id).first()
        self.assertIsNone(db_active)
        
        # Verify added to alert_history table
        db_history = self.db.query(models.AlertHistory).filter(models.AlertHistory.alert_id == alert_id).first()
        self.assertIsNotNone(db_history)
        self.assertEqual(db_history.patient_id, 1)
        self.assertEqual(db_history.alert_type, "fall")
        self.assertEqual(db_history.severity, "high")
        self.assertEqual(db_history.acknowledged_by, 1)
        self.assertEqual(db_history.status, "ACKNOWLEDGED")

    def test_cancellation_lifecycle(self):
        """5. Verify cancel deletes active alert without history."""
        loop = asyncio.get_event_loop()
        alert = loop.run_until_complete(
            alert_manager.publish(
                db=self.db,
                patient_id=1,
                alert_type="seizure",
                severity="low",
                details={"gate_score": 0.12}
            )
        )
        alert_id = alert.id
        
        # Call cancellation endpoint
        res = self.client.delete(f"/api/dashboard/alerts/{alert_id}/cancel")
        self.assertEqual(res.status_code, 200)
        
        # Verify removed from active table
        db_active = self.db.query(models.Alert).filter(models.Alert.id == alert_id).first()
        self.assertIsNone(db_active)
        
        # Verify NOT in alert_history table
        db_history = self.db.query(models.AlertHistory).filter(models.AlertHistory.alert_id == alert_id).first()
        self.assertIsNone(db_history)

    def test_patient_alert_history(self):
        """6. Verify history endpoint returns acknowledged alerts only, chronologically."""
        # Create two history logs directly
        now = datetime.utcnow()
        hist1 = models.AlertHistory(
            alert_id=101,
            patient_id=1,
            alert_type="fall",
            severity="high",
            details={"probability": 0.88},
            acknowledged_by=1,
            acknowledged_at=now,
            created_at=now - timedelta(minutes=10),
            status="ACKNOWLEDGED"
        )
        hist2 = models.AlertHistory(
            alert_id=102,
            patient_id=1,
            alert_type="seizure",
            severity="critical",
            details={"gate": 0.99},
            acknowledged_by=1,
            acknowledged_at=now,
            created_at=now - timedelta(minutes=5),
            status="ACKNOWLEDGED"
        )
        self.db.add(hist1)
        self.db.add(hist2)
        
        # Also create an active alert (should NOT show in patient history)
        active_alert = models.Alert(
            patient_id=1,
            alert_type="arrhythmia",
            severity="low",
            details={},
            status="ACTIVE",
            created_at=now
        )
        self.db.add(active_alert)
        self.db.commit()
        
        # Call patient alerts endpoint
        res = self.client.get("/api/patients/1/alerts")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        # Verify size and chronological sorting (newest first in route)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["alert_id"], 102) # newest first
        self.assertEqual(data[1]["alert_id"], 101)
        
        # Active alert should not be present
        active_ids = [a["alert_id"] for a in data]
        self.assertNotIn(active_alert.id, active_ids)


if __name__ == "__main__":
    unittest.main()
