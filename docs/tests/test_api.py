"""
API Integration Tests
======================
Tests all REST API endpoints against a running backend instance.

Requirements:
    pip install pytest httpx

Usage:
    # Start the backend first: uvicorn backend.main:app --port 8000
    python -m pytest docs/tests/test_api.py -v

    # With custom URL:
    BASE_URL=http://localhost:8000 python -m pytest docs/tests/test_api.py -v
"""

import sys
import os
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
DOCTOR_EMAIL = os.getenv("DOCTOR_EMAIL", "doctor@hospital.com")
DOCTOR_PASSWORD = os.getenv("DOCTOR_PASSWORD", "doctor123")


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    if not HTTPX_AVAILABLE:
        pytest.skip("httpx not installed: pip install httpx")
    return httpx.Client(base_url=BASE_URL, timeout=30.0)


@pytest.fixture(scope="module")
def auth_token(client):
    """Get a JWT token for all authenticated tests."""
    resp = client.post("/api/auth/login", json={
        "email": DOCTOR_EMAIL,
        "password": DOCTOR_PASSWORD
    })
    if resp.status_code != 200:
        pytest.skip(f"Cannot authenticate — backend may not be running at {BASE_URL}")
    return resp.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture(scope="module")
def first_patient_id(client, auth_headers):
    """Get the ID of the first patient in the system."""
    resp = client.get("/api/patients", headers=auth_headers)
    if resp.status_code != 200 or not resp.json():
        pytest.skip("No patients in database — seed first: python -m backend.seed")
    return resp.json()[0]["id"]


# ─── Health Check ─────────────────────────────────────────────────────────────

class TestHealthCheck:
    def test_root_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_root_has_message(self, client):
        resp = client.get("/")
        data = resp.json()
        assert "message" in data
        assert "Medical Chatbot" in data["message"]


# ─── Authentication Tests ──────────────────────────────────────────────────────

class TestAuthentication:
    def test_login_success(self, client):
        resp = client.post("/api/auth/login", json={
            "email": DOCTOR_EMAIL,
            "password": DOCTOR_PASSWORD
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert len(data["access_token"]) > 20

    def test_login_wrong_password(self, client):
        resp = client.post("/api/auth/login", json={
            "email": DOCTOR_EMAIL,
            "password": "wrongpassword"
        })
        assert resp.status_code == 401

    def test_login_wrong_email(self, client):
        resp = client.post("/api/auth/login", json={
            "email": "nobody@example.com",
            "password": "whatever"
        })
        assert resp.status_code == 401

    def test_login_missing_fields(self, client):
        resp = client.post("/api/auth/login", json={"email": DOCTOR_EMAIL})
        assert resp.status_code == 422  # Pydantic validation error


# ─── Patient Endpoint Tests ────────────────────────────────────────────────────

class TestPatientListEndpoint:
    def test_requires_auth(self, client):
        resp = client.get("/api/patients")
        assert resp.status_code == 401

    def test_list_patients_returns_200(self, client, auth_headers):
        resp = client.get("/api/patients", headers=auth_headers)
        assert resp.status_code == 200

    def test_list_patients_returns_list(self, client, auth_headers):
        resp = client.get("/api/patients", headers=auth_headers)
        data = resp.json()
        assert isinstance(data, list)

    def test_patient_has_required_fields(self, client, auth_headers):
        resp = client.get("/api/patients", headers=auth_headers)
        patients = resp.json()
        if not patients:
            pytest.skip("No patients in database")
        patient = patients[0]
        for field in ["id", "name"]:
            assert field in patient, f"Missing required field: {field}"

    def test_search_by_name(self, client, auth_headers):
        resp = client.get("/api/patients", headers=auth_headers)
        patients = resp.json()
        if not patients:
            pytest.skip("No patients in database")
        # Search for first letter of first patient's name
        first_letter = patients[0]["name"][0]
        resp2 = client.get(f"/api/patients?search={first_letter}", headers=auth_headers)
        assert resp2.status_code == 200
        results = resp2.json()
        assert all(first_letter.lower() in p["name"].lower() for p in results)

    def test_search_no_results(self, client, auth_headers):
        resp = client.get("/api/patients?search=ZZZZNOTAREALNAME", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []


class TestPatientCreateEndpoint:
    def test_create_patient_success(self, client, auth_headers):
        resp = client.post("/api/patients", headers=auth_headers, json={
            "name": "Test Patient API",
            "gender": "Male",
            "blood_type": "O+",
            "phone": "555-0000"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Patient API"
        assert "id" in data
        assert data["id"] > 0

    def test_create_patient_requires_name(self, client, auth_headers):
        resp = client.post("/api/patients", headers=auth_headers, json={
            "gender": "Male",
            "blood_type": "A+"
        })
        assert resp.status_code == 422  # validation error

    def test_create_patient_requires_auth(self, client):
        resp = client.post("/api/patients", json={"name": "Unauthorized"})
        assert resp.status_code == 401


class TestPatientDetailEndpoint:
    def test_get_patient_by_id(self, client, auth_headers, first_patient_id):
        resp = client.get(f"/api/patients/{first_patient_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == first_patient_id

    def test_patient_detail_has_medical_history_fields(self, client, auth_headers, first_patient_id):
        resp = client.get(f"/api/patients/{first_patient_id}", headers=auth_headers)
        data = resp.json()
        for field in ["diagnoses", "medications", "lab_results", "allergies", "visits"]:
            assert field in data, f"Missing medical history field: {field}"
            assert isinstance(data[field], list)

    def test_patient_not_found(self, client, auth_headers):
        resp = client.get("/api/patients/99999999", headers=auth_headers)
        assert resp.status_code == 404

    def test_get_medications(self, client, auth_headers, first_patient_id):
        resp = client.get(f"/api/patients/{first_patient_id}/medications",
                          headers=auth_headers)
        assert resp.status_code == 200
        meds = resp.json()
        assert isinstance(meds, list)
        for med in meds:
            assert "drug_name" in med
            assert med["is_active"] == True  # default active_only=True

    def test_get_labs(self, client, auth_headers, first_patient_id):
        resp = client.get(f"/api/patients/{first_patient_id}/labs",
                          headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_diagnoses(self, client, auth_headers, first_patient_id):
        resp = client.get(f"/api/patients/{first_patient_id}/diagnoses",
                          headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ─── Chat Endpoint Tests ───────────────────────────────────────────────────────

class TestChatEndpoint:
    def test_chat_requires_auth(self, client, first_patient_id):
        resp = client.post("/api/chat", json={
            "query": "What medications is the patient on?",
            "patient_id": first_patient_id
        })
        assert resp.status_code == 401

    def test_chat_returns_answer(self, client, auth_headers, first_patient_id):
        resp = client.post("/api/chat", headers=auth_headers, json={
            "query": "What medications is this patient taking?",
            "patient_id": first_patient_id
        }, timeout=60.0)  # LLM can be slow
        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert "intent" in data
        assert "sources" in data
        assert len(data["answer"]) > 0

    def test_chat_returns_valid_intent(self, client, auth_headers, first_patient_id):
        resp = client.post("/api/chat", headers=auth_headers, json={
            "query": "What medications is this patient taking?",
            "patient_id": first_patient_id
        }, timeout=60.0)
        data = resp.json()
        valid_intents = [
            'history_lookup', 'medication_check', 'lab_results', 'allergy_check',
            'visit_summary', 'diagnosis_check', 'risk_flag', 'general_question'
        ]
        assert data["intent"] in valid_intents

    def test_chat_invalid_patient(self, client, auth_headers):
        resp = client.post("/api/chat", headers=auth_headers, json={
            "query": "Test query",
            "patient_id": 99999999
        })
        assert resp.status_code == 404

    def test_docs_endpoint_accessible(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200


# ─── Token Validation Tests ────────────────────────────────────────────────────

class TestTokenValidation:
    def test_expired_token_rejected(self, client):
        # Use a clearly invalid / malformed token
        headers = {"Authorization": "Bearer invalid.token.here"}
        resp = client.get("/api/patients", headers=headers)
        assert resp.status_code == 401

    def test_missing_bearer_prefix_rejected(self, client, auth_token):
        headers = {"Authorization": auth_token}  # missing "Bearer " prefix
        resp = client.get("/api/patients", headers=headers)
        assert resp.status_code == 401
