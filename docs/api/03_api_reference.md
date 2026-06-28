# 03 — API Reference

Base URL: `http://localhost:8000`  
Interactive Docs: `http://localhost:8000/docs` (Swagger UI)  
Alternative Docs: `http://localhost:8000/redoc`

---

## Authentication

All endpoints (except `/api/auth/login`) require the following header:

```
Authorization: Bearer <JWT_TOKEN>
```

---

## 3.1 Auth Endpoints

### `POST /api/auth/login`

Authenticate a doctor and receive a JWT token.

**Request Body:**
```json
{
  "email": "doctor@hospital.com",
  "password": "doctor123"
}
```

**Response `200 OK`:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR...",
  "token_type": "bearer"
}
```

**Response `401 Unauthorized`:**
```json
{
  "detail": "Incorrect email or password"
}
```

---

## 3.2 Patient Endpoints

### `GET /api/patients`

List all patients. Supports optional name search.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `search` | string | `""` | Partial name match (case-insensitive) |

**Response `200 OK`:**
```json
[
  {
    "id": 1,
    "name": "Ahmad Hassan",
    "dob": "1978-04-12",
    "gender": "Male",
    "blood_type": "O+",
    "phone": "555-0101",
    "created_at": "2025-01-15T10:30:00"
  }
]
```

---

### `POST /api/patients`

Register a new patient.

**Request Body:**
```json
{
  "name": "Sara Ahmed",
  "dob": "1990-06-20",
  "gender": "Female",
  "blood_type": "A+",
  "phone": "555-0202"
}
```

**Response `200 OK`:** Returns the created `PatientOut` object with its new `id`.

---

### `GET /api/patients/{patient_id}`

Get full patient details including all medical history.

**Response `200 OK`:**
```json
{
  "id": 1,
  "name": "Ahmad Hassan",
  "dob": "1978-04-12",
  "gender": "Male",
  "blood_type": "O+",
  "phone": "555-0101",
  "created_at": "2025-01-15T10:30:00",
  "diagnoses": [
    {
      "id": 5,
      "description": "Type 2 Diabetes Mellitus",
      "icd10_code": "E11",
      "diagnosed_on": "2022-03-10",
      "is_active": true,
      "severity": "moderate"
    }
  ],
  "medications": [...],
  "lab_results": [...],
  "allergies": [...],
  "visits": [...]
}
```

**Response `404 Not Found`:**
```json
{ "detail": "Patient not found" }
```

---

### `GET /api/patients/{patient_id}/medications`

Get a patient's medications.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `active_only` | boolean | `true` | If true, returns only active (current) medications |

**Response `200 OK`:** List of `MedicationOut` objects.

---

### `GET /api/patients/{patient_id}/labs`

Get a patient's lab results, ordered by most recent first.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `test_name` | string | `""` | Filter by test name (case-insensitive substring match) |

**Response `200 OK`:** List of `LabResultOut` objects.

---

### `GET /api/patients/{patient_id}/diagnoses`

Get all diagnoses for a patient.

**Response `200 OK`:** List of `DiagnosisOut` objects.

---

## 3.3 Chat Endpoints

### `POST /api/chat`

Synchronous (blocking) chat endpoint. Waits for the full LLM response before returning.

**Request Body:**
```json
{
  "query": "What medications is this patient currently on?",
  "patient_id": 1
}
```

**Response `200 OK`:**
```json
{
  "answer": "The patient is currently on:\n- Metformin 500mg twice daily (since 2023-01-10)\n- Amlodipine 5mg once daily (since 2022-08-15)",
  "intent": "medication_check",
  "sources": [
    "Medication record #3: Metformin 500mg",
    "Medication record #7: Amlodipine 5mg"
  ]
}
```

---

### `WebSocket /api/ws/chat`

Streaming chat endpoint. Streams the LLM response token-by-token for low perceived latency.

**Connection:** `ws://localhost:8000/api/ws/chat`

**Send (JSON):**
```json
{
  "query": "Show me the last HbA1c result",
  "patient_id": 1,
  "token": "eyJhbGciOiJIUzI1NiIsInR..."
}
```

**Receive — streaming chunks:**
```json
{ "chunk": "The last", "done": false }
{ "chunk": " HbA1c result", "done": false }
{ "chunk": " was 8.1%", "done": false }
```

**Receive — final message:**
```json
{
  "chunk": "",
  "done": true,
  "intent": "lab_results",
  "sources": ["Lab #12: HbA1c = 8.1 % on 2025-11-20"]
}
```

**Receive — error:**
```json
{ "error": "Patient not found" }
```

---

## 3.4 Root Endpoint

### `GET /`

Health check.

**Response `200 OK`:**
```json
{
  "message": "Medical Chatbot API is running",
  "docs": "/docs"
}
```

---

## 3.5 Schema Reference

### PatientBase
| Field | Type | Required |
|-------|------|----------|
| name | string | ✅ |
| dob | date | optional |
| gender | string | optional |
| blood_type | string | optional |
| phone | string | optional |

### DiagnosisOut
| Field | Type |
|-------|------|
| id | int |
| description | string |
| icd10_code | string? |
| diagnosed_on | date? |
| is_active | bool |
| severity | string? |

### MedicationOut
| Field | Type |
|-------|------|
| id | int |
| drug_name | string |
| dose | string? |
| start_date | date? |
| end_date | date? |
| is_active | bool |

### LabResultOut
| Field | Type |
|-------|------|
| id | int |
| test_name | string |
| value | float? |
| unit | string? |
| reference | string? |
| test_date | date |
| is_abnormal | bool |

### AllergyOut
| Field | Type |
|-------|------|
| id | int |
| allergen | string |
| reaction | string? |
| severity | string? |

---

*Next: [Data Model →](04_data_model.md)*
