# Deployment Audit: Documentation vs Implementation vs Runtime Reality

Audit date: 2026-06-25  
Workspace: `F:\GP\Deployment\Medical-History-Chatbot`

## Executive Verdict

The deployed system is a strong demo / pilot prototype, not a production candidate. The main backend, React frontend, SQLite database, and microservice source trees are present. The React production build succeeds, the main FastAPI app imports and serves root endpoints, and the three inference microservices import and answer `/health` in-process.

However, the documentation is split between an older "medical history chatbot" design and a newer "medical monitoring system" implementation. Several major implemented features are undocumented in the primary API/data docs. Several documented claims are stale or false at runtime: PostgreSQL is documented but SQLite is deployed; `/api/ws/chat` is documented but `/api/chat/stream` is implemented; docs describe visit-based doctor assignment while runtime uses `patient_assignments`; and the deployed inference service processes were not running when queried through the main backend.

Most serious runtime finding: seizure service startup expects `Repos\seizure_detection\runtime\build\Release\seizure_runtime_cpp.exe`, but the executable present is `Repos\seizure_detection\runtime\build\seizure_runtime_cpp.exe`. That makes the documented live seizure pipeline likely fail when started through the FastAPI service, despite model weights and demo videos being present.

## Evidence Collected

- Read all files under `docs`, including markdown docs, test files, and test result logs.
- Enumerated backend routers, frontend routes/API calls, config files, startup scripts, service clients, model weights, and SQLite schema.
- Ran `python -m compileall backend Repos\seizure_detection\service.py Repos\Arrythmia-Detection-master\service.py Repos\Patient-fall-detection-system-main\service.py`: passed.
- Ran `npm.cmd run build` in `frontend-react`: passed with Vite bundle-size warnings.
- Ran main backend TestClient using `C:\Users\omars\miniconda3\envs\medical_chatbot\python.exe`: `/` and documented/demo logins work; protected endpoints enforce role gates.
- Checked backend service health through the main app: arrhythmia, fall, and seizure services were unreachable on ports 8001-8003.
- Imported each microservice directly with TestClient: all `/health` endpoints returned 200 in-process.
- Queried `medical_db.db` live schema and row counts.

## Traceability Matrix

| Feature | Documented | Implemented | Reachable | Tested | Matches Docs |
| ------- | ---------- | ----------- | --------- | ------ | ------------ |
| JWT login | Yes: `docs/03_api_reference.md`, `docs/07_setup_guide.md` | Yes: `backend/routers/auth.py`, `backend/auth.py` | Yes: `/api/auth/login` | Yes: doctor/nurse/admin login 200 with documented passwords | Mostly; docs understate nurse/admin roles |
| Doctor-only medical chat | Yes | Yes: `backend/routers/chat.py`, `ChatPanel.jsx` | Yes for doctor only | Static + route smoke; LLM not run | Partial; docs endpoint drift |
| Streaming chat | Yes: documented as `WebSocket /api/ws/chat` | Yes: implemented as `/api/chat/stream` | Yes if doctor token and LLM backend available | Static verified; not E2E LLM-tested | No: endpoint path mismatch |
| Synchronous chat | Yes: `POST /api/chat` | Yes | Yes for assigned doctor/patient | Static; no LLM E2E due no Ollama check | Mostly, but assignment model differs |
| General medical chat | Yes in overview | Yes: `mode: general` in `/api/chat/stream` | Yes for doctor | Static | Mostly |
| Intent classification | Yes | Yes: `backend/services/intent.py` | Used by chat | Compile/static | Unknown runtime; requires Ollama/OpenAI-style local endpoint |
| NER | Yes | Yes: `backend/services/ner.py` | Used by chat | Compile/static | Unknown runtime; requires Ollama/OpenAI-style local endpoint |
| DB retrieval/RAG | Yes | Yes: `backend/services/retriever.py` | Used by chat | Compile/static | Mostly |
| Source-cited answers | Yes | Partially: sources returned from retriever | Reachable through chat | Static | Partial; citations depend on prompt/output |
| Image/PDF/multimodal upload | Yes: uploads/image analysis and MedGemma doc | Image upload implemented at `/api/chat/analyze-image`; PDF ingestion/knowledge-base ingestion not found | UI upload exists in chat panel | Static | Partial; image yes, PDF ingestion no |
| Patient list/search | Yes | Yes: `/api/patients`, `PatientListPage.jsx` | Yes for assigned users/admin | TestClient 200 | Partial; docs omit assignment table and pagination/filter additions |
| Patient creation | Yes | Yes: `/api/patients`, modal UI | Yes | Static | Mostly |
| Patient full history | Yes | Yes: `/api/patients/{id}` includes relationships | Yes for assigned users/admin | Static | Mostly |
| Medication/lab/diagnosis endpoints | Yes | Yes | Yes | Static | Mostly |
| Allergy endpoint | Data documented | No standalone `/allergies` endpoint; included in full patient | Reachable via full patient | Static | Partial |
| Chat history persistence | Data model documents `chat_logs`; API docs omit endpoint | Yes: `/api/chat/history/{patient_id}` | Yes for doctor assigned patient | Static | Hidden/underdocumented |
| PostgreSQL deployment | Yes, repeatedly | Runtime `.env` uses `sqlite:///./medical_db.db` | Yes via SQLite | DB inspected | No |
| Synthea dataset | Yes | Yes: large SQLite data loaded; loader exists | Yes through API | DB counts: 2,415 patients; 1,446,327 labs | Mostly; docs cite ~1,000+ patients, runtime has 2,415 |
| Doctor-patient isolation | Yes: visit-based in docs | Yes, but implemented via `patient_assignments` | Yes | TestClient scoped endpoints 200 | No: enforcement mechanism changed |
| Nurse role | Partly in architecture/front docs | Yes | Yes | Login and protected endpoints tested | Under-documented in API/data model |
| Admin role/user management | Front/integration docs mention; API docs omit | Yes: `/api/admin/users`, assign patients | Yes admin only | TestClient admin 200, doctor/nurse 403 | Under-documented |
| Dashboard | Architecture/frontend docs mention | Yes: `/api/dashboard/summary`, dashboards | Yes | TestClient 200 | Under-documented in API reference |
| Alerts | Architecture/data docs mention | Yes: `alerts` table, alert feed, WS `/api/ws/alerts` | Yes if token; live only when services publish | Static + DB counts | Under-documented in API reference |
| Alert acknowledgement | Frontend implemented | Yes: `PATCH /api/dashboard/alerts/{id}/acknowledge` | Yes | Static | Hidden in primary API docs |
| Vital signs | Architecture/data docs mention | Table exists | Not populated; no ingest endpoint found | DB count 0 | Partial/dead for current deployment |
| Arrhythmia detection | Architecture/frontend/login docs mention | Yes: router, service, model files | Backend endpoint reachable; service not running on port | Direct service `/health` 200 in-process; main health says unreachable | Partial deployment |
| ECG frontend | Yes in newer frontend docs | Yes, but uses random generated ECG | Reachable in patient detail | Static | Partial/placeholder input |
| Fall detection | Architecture/frontend docs mention | Yes: service, backend bridge, sandbox UI | Not running on port 8002; direct import OK | Direct service `/health` 200 in-process | Partial deployment |
| Fall live camera upload | Yes | Yes: `/api/ws/camera/{room_id}` browser frame bridge | Reachable if fall service running | Static | Partial runtime |
| Seizure detection | Yes in `README((salama).md)` and architecture docs | Yes: service, C++ runtime source, weights, frontend sandbox | Not running on port 8003; likely start path defect | Direct service `/health` 200 in-process; executable path mismatch found | Partial/broken deployment path |
| Seizure live camera/video playback | Yes | Yes in SandboxTestPage and service session APIs | UI reachable; backend depends on service process | Static | Partial |
| WebSocket updates for monitoring | Yes | Alerts WS, fall camera WS, seizure service WS | Reachable if services running | Static | Partial runtime |
| Notifications/audio alerts | Frontend behavior documented lightly | Yes: `alertsStore`, alarm playback | UI reachable | Static | Under-documented |
| Monitoring service health | Architecture/frontend docs mention | Yes: `/api/monitoring/status`, dashboard service health | Yes | TestClient 200, services unreachable | Matches intent; shows degraded state |
| Tests/benchmarks | Yes | Test files exist under docs | Pytest missing in conda env | `python -m pytest` failed: no pytest | Partial deployment |
| Production startup scripts | Yes | `start_all_services.ps1`/`.sh` | Present | Static | Partial; does not start React; seizure exe path mismatch remains |
| Legacy static frontend | Not primary docs | `frontend/index.html` exists | Reachable as static file only | Static | Hidden/legacy |

## Feature Mapping

### Medical History Chatbot

Docs: `01_project_overview.md`, `02_system_architecture.md`, `03_api_reference.md`, `05_ai_pipeline.md`, `06_frontend_guide.md`  
Backend: `backend/routers/chat.py`, `backend/services/intent.py`, `ner.py`, `retriever.py`, `llm.py`  
Frontend: `frontend-react/src/components/chat/ChatPanel.jsx`, `useChatStream.js`, patient/global chat pages  
Database: `patients`, `diagnoses`, `medications`, `lab_results`, `allergies`, `chat_logs`  
Deployment: main FastAPI port 8000, LLM dependency at Ollama `localhost:11434`

Status: implemented and reachable for doctors, but streaming endpoint is renamed from docs and LLM runtime was not validated.

### Patient Management

Docs: patient hub and API docs  
Backend: `patients.py`, `schemas.py`, `models.py`  
Frontend: patient list/detail/add modal  
Database: `patients` plus clinical tables  
Deployment: main backend only

Status: implemented and reachable. Runtime uses `patient_assignments` for doctor/nurse isolation, not the documented visit-based rule.

### Monitoring Platform

Docs: architecture/frontend/integration docs; not fully reflected in primary API reference  
Backend: `monitoring.py`, `dashboard.py`, `arrhythmia.py`, service clients  
Frontend: dashboards, monitoring page, sandbox, alert feed, alert WebSocket hook  
Database: `alerts`, `vital_signs`, `patient_assignments`  
Deployment: main backend plus microservices on ports 8001-8003

Status: implemented at code level; current deployed service URLs are unreachable unless `start_all_services` is run successfully.

## Missing Features Report

| Documented Feature | Evidence | Runtime Impact |
| ------------------ | -------- | -------------- |
| `WebSocket /api/ws/chat` | Docs list `/api/ws/chat`; backend implements `/api/chat/stream`; legacy `frontend/index.html` uses `/api/ws/chat` | Legacy/static frontend chat stream is broken against current backend |
| PostgreSQL production DB | Docs/setup use PostgreSQL; `.env` uses SQLite; live DB is `medical_db.db` | Deployment does not match documented architecture/scalability model |
| PDF ingestion / knowledge-base ingestion | User brief examples and multimodal docs imply document ingestion; only image analysis upload route found | No real PDF ingestion workflow found |
| Standalone allergy endpoint | Data model documents allergies; API reference omits endpoint; no `/api/patients/{id}/allergies` | Available only inside full patient payload |
| Vital-sign ingestion/API | Architecture shows `/api/ws/vitals`, `vital_signs`; no `/api/ws/vitals`; table has 0 rows | Vitals are modeled but not operational |
| API docs for admin/dashboard/monitoring/arrhythmia | Routes exist but `docs/03_api_reference.md` only covers auth/patients/chat/root/schema | Implemented features are invisible to API consumers |
| Frontend deployment startup | `start_all_services.ps1` starts backend/microservices only; no Vite or built frontend serving | Full app startup is incomplete unless frontend started separately |

## Partial Implementations Report

| Feature | Partial State | Evidence |
| ------- | ------------- | -------- |
| ECG/arrhythmia workflow | Backend endpoint and microservice exist, but patient detail sends random generated ECG samples | `PatientDetailPage.jsx` says random signal is generated as placeholder |
| Inference microservices | Import and `/health` work in-process; not running on deployed ports during audit | `/api/monitoring/status` returned all three services as unreachable |
| Seizure runtime | Models and source exist, but service expects wrong executable path | `service.py` expects `runtime/build/Release/seizure_runtime_cpp.exe`; actual file is `runtime/build/seizure_runtime_cpp.exe` |
| Test suite | Test files exist; pytest is not installed in configured conda env | `python -m pytest ...` failed with `No module named pytest` |
| Image analysis | Endpoint and UI exist; auth is form-token based and upload content is not persisted except chat log | `uploads.py`; no file validation/storage lifecycle beyond bytes read |
| Mock/live frontend mode | Useful for demos, but default frontend `.env.example` is `VITE_DATA_MODE=mock` | Live backend can be bypassed silently in demo mode |
| Monitoring dashboard sessions | UI polls dashboard summary, but service sessions are empty/unreachable unless microservices are running | TestClient dashboard 200, service health unreachable |

## Broken Integrations Report

| Integration | Finding | Evidence |
| ----------- | ------- | -------- |
| Docs -> chat streaming | Documented `/api/ws/chat` does not exist in backend | `docs/03_api_reference.md` vs `backend/routers/chat.py` |
| Legacy static frontend -> backend | `frontend/index.html` connects to `/api/ws/chat` | Current backend only provides `/api/chat/stream` |
| Main backend -> inference services | Health checks returned `unreachable` for arrhythmia/fall/seizure | TestClient `/api/monitoring/status` |
| Seizure service -> C++ executable | Expected path absent; actual executable is one directory higher | `Test-Path runtime\build\Release\...` false; found `runtime\build\seizure_runtime_cpp.exe` |
| Docs data model -> runtime schema | Docs table `doctors`; runtime table `users`; docs omit `patient_assignments` | SQLite schema inspection |
| API docs -> implemented API | Admin/dashboard/monitoring/arrhythmia/history endpoints missing from API reference | Router enumeration |
| Deployment docs -> runtime DB | Docs say PostgreSQL; `.env` says SQLite | `.env`, `backend/database.py`, DB inspection |

## Hidden Features Report

| Hidden Feature | Location | Risk |
| -------------- | -------- | ---- |
| Admin user management | `backend/routers/users.py`, `UserManagementPage.jsx` | Undocumented RBAC/admin surface; security review may miss it |
| Random patient assignment | `POST /api/admin/assign-patients` | Destructive to assignment table; not documented as a data-changing admin operation |
| Alert acknowledgement | `PATCH /api/dashboard/alerts/{id}/acknowledge` | Clinical audit trail behavior underdocumented |
| Arrhythmia history endpoint | `GET /api/arrhythmia/history/{patient_id}` | API consumers will not know it exists |
| Chat history endpoint | `GET /api/chat/history/{patient_id}` | Privacy/audit retention not described in API docs |
| Seizure manual trigger endpoint | `POST /api/monitoring/seizure/trigger-alert` | Can create critical alerts manually; should be documented and restricted/audited |
| Test-video upload endpoint | `POST /api/monitoring/seizure/upload-test-video` | Accepts arbitrary video filename and returns absolute server path |
| Legacy static frontend | `frontend/index.html` | Uses stale endpoint and may be mistaken for supported UI |
| Mock-mode demo system | `frontend-react/src/mock/data.js`, `api/client.js` | Can make nonfunctional backend paths appear functional |

## Seizure Detection Deployment Audit

| Item | Status | Evidence |
| ---- | ------ | -------- |
| OpenPose | Present | `model_weights/pose.onnx`, `pose.pth`, vendor lightweight pose repo, C++ `extract_openpose_keypoints` |
| VSViG | Present | `model_weights/vsvig_protogcn.onnx`, C++ `vsvig_session` and patch extraction |
| ViViT | Present as Python sidecar | `service.py` loads `google/vivit-b-16x2-kinetics400` and uses `vivit_joint_tokens_forward_chunked` |
| Cross-Joint/CJ | Present | `cj_final.onnx`, C++ IPC thread, CJ telemetry |
| Gate | Present | `runtime/include/seizure_gate.hpp` with thresholds/latch |
| Alert logic | Present | CSV tailing maps `SEIZURE`/latch events and backend publishes alerts |
| Service API | Present | `/health`, `/sessions`, `/ws/{session_id}` in `Repos\seizure_detection\service.py` |
| Frontend upload | Present | Sandbox video upload and source selection |
| Live camera | Present | Browser webcam source for sandbox; main backend camera WS is fall-specific, seizure service reads source directly |
| Video playback | Present | Sandbox buffers events and syncs UI status to playhead |
| WebSocket updates | Present | Service WS plus backend event relay |
| Deployment integration | Broken/fragile | Service process not running; executable path mismatch; startup script does not validate model/runtime readiness |
| Documentation parity | Partial | README salama describes VSViG risk scoring; runtime is hybrid OpenPose + VSViG + ViViT/CJ gate; API/ops docs do not fully describe this |

## Runtime Configuration Audit

| Setting | Documented | Actual | Finding |
| ------- | ---------- | ------ | ------- |
| `DATABASE_URL` | PostgreSQL URL | `sqlite:///./medical_db.db` | Major deployment drift |
| `SECRET_KEY` | Change in production | Hardcoded local secret in `.env` | High security risk if deployed/shared |
| LLM backend | Ollama/OpenAI | Ollama with `medgemma1.5:latest`, qwen intent/NER models | Plausible but Ollama not runtime-tested |
| Service URLs | localhost 8001-8003 | localhost 8001-8003 | Config matches docs, but processes were down |
| Frontend mode | mock/live toggle | `.env.example` defaults `mock` | Demo can mask backend failure |
| Startup | Backend + services | `start_all_services.ps1` starts backend/microservices only | React frontend omitted |

## Database Audit

Live SQLite tables:

| Table | Rows | Documented |
| ----- | ---- | ---------- |
| `users` | 3 | Partially; docs still say `doctors` |
| `patients` | 2415 | Yes |
| `visits` | 30 | Yes |
| `diagnoses` | 99932 | Yes |
| `medications` | 165604 | Yes |
| `lab_results` | 1446327 | Yes |
| `allergies` | 2112 | Yes |
| `chat_logs` | 8 | Yes |
| `alerts` | 65 | Architecture docs, not primary API |
| `vital_signs` | 0 | Architecture/data docs |
| `patient_assignments` | 4836 | Not in primary data model |

Key drift:

- `doctors` table documented; `users` table deployed.
- Visit-based assignment documented; `patient_assignments` deployed.
- `vital_signs` exists but is empty and lacks an ingestion route.
- No migration system found; `Base.metadata.create_all()` is used at startup.

## API Audit

| Endpoint | Docs | Backend | Frontend Uses It | Works |
| -------- | ---- | ------- | ---------------- | ----- |
| `GET /` | Yes | Yes | No | Yes, TestClient 200 |
| `GET /api/health` | No | Yes | No | Static yes |
| `POST /api/auth/login` | Yes | Yes | Yes | Yes, TestClient 200 |
| `GET /api/patients` | Yes | Yes | Yes | Yes, TestClient 200 |
| `POST /api/patients` | Yes | Yes | Yes | Static yes |
| `GET /api/patients/{id}` | Yes | Yes | Yes | Static yes |
| `GET /api/patients/{id}/medications` | Yes | Yes | No direct React use | Static yes |
| `GET /api/patients/{id}/labs` | Yes | Yes | No direct React use | Static yes |
| `GET /api/patients/{id}/diagnoses` | Yes | Yes | No direct React use | Static yes |
| `GET /api/patients/{id}/alerts` | No | Yes | Yes | Static yes |
| `POST /api/chat` | Yes | Yes | No primary React use | Static; LLM not E2E tested |
| `WS /api/ws/chat` | Yes | No | Legacy static frontend | Broken |
| `WS /api/chat/stream` | No | Yes | React uses | Static yes |
| `GET /api/chat/history/{patient_id}` | No | Yes | React uses | Static yes |
| `POST /api/chat/analyze-image` | Architecture docs only | Yes | React uses | Static yes |
| `GET /api/dashboard/summary` | No API docs | Yes | React uses | Yes, TestClient 200 |
| `PATCH /api/dashboard/alerts/{id}/acknowledge` | No | Yes | React uses | Static yes |
| `POST /api/arrhythmia/analyze` | No primary API docs | Yes | React uses | Backend reachable; service down |
| `GET /api/arrhythmia/history/{patient_id}` | No | Yes | No direct React use found | Static yes |
| `POST /api/monitoring/fall/start` | No primary API docs | Yes | Sandbox uses | Backend reachable; service down |
| `DELETE /api/monitoring/fall/{room_id}/stop` | No | Yes | Sandbox uses | Backend reachable; service down |
| `POST /api/monitoring/fall/{room_id}/reset-latch` | No | Yes | Sandbox uses | Backend reachable; service down |
| `POST /api/monitoring/seizure/start` | No primary API docs | Yes | Sandbox uses | Backend reachable; service down/path defect likely |
| `DELETE /api/monitoring/seizure/{session_id}/stop` | No | Yes | Sandbox uses | Backend reachable; service down |
| `POST /api/monitoring/seizure/{session_id}/reset-latch` | No | Yes | Sandbox uses | Backend reachable; service down |
| `POST /api/monitoring/seizure/trigger-alert` | No | Yes | Sandbox uses | Static yes |
| `POST /api/monitoring/seizure/upload-test-video` | No | Yes | Sandbox uses | Static; security risk |
| `GET /api/monitoring/status` | No | Yes | Indirect/dashboard | Yes, reports services unreachable |
| `WS /api/ws/alerts` | Frontend docs | Yes | React uses | Static yes |
| `WS /api/ws/camera/{room_id}` | No primary API docs | Yes | Sandbox uses for fall | Backend yes; service down |
| `GET /api/admin/users` | No primary API docs | Yes | React uses | Yes for admin; 403 for doctor/nurse |
| `POST /api/admin/users` | No | Yes | React uses | Static yes |
| `PATCH /api/admin/users/{id}/deactivate` | No | Yes | React uses | Static yes |
| `PATCH /api/admin/users/{id}/activate` | No | Yes | React uses | Static yes |
| `POST /api/admin/assign-patients` | No | Yes | React uses | Static; destructive |

## Frontend Audit

Implemented routes:

- `/login`
- `/doctor/dashboard`
- `/doctor/patients`
- `/doctor/patients/:id`
- `/doctor/monitoring`
- `/doctor/chat`
- `/doctor/sandbox`
- `/nurse/dashboard`
- `/nurse/patients`
- `/nurse/patients/:id`
- `/admin/dashboard`
- `/admin/users`

Findings:

- React build succeeds.
- Role guard exists and routes are role-gated.
- Doctor patient detail has chat, ECG, and monitoring tabs.
- Nurse cannot see patient chat tab.
- Admin user management exists but is underdocumented.
- ECG tab uses generated random ECG samples, not persisted patient ECG data.
- Live monitoring page only displays active sessions; starting fall/seizure monitoring happens in sandbox, not from patient detail despite empty-state copy saying "Start monitoring from a patient's detail page."
- Mock mode can exercise the UI even when backend/microservices are unavailable.
- Legacy `frontend/index.html` is stale and uses `/api/ws/chat`.

## Security Findings

| Severity | Finding | Evidence | Recommendation |
| -------- | ------- | -------- | -------------- |
| Critical | `.env` contains a real JWT `SECRET_KEY` in the workspace | `.env` | Rotate before any shared deployment; never commit/share |
| High | CORS allows all origins with credentials | `backend/main.py` uses `allow_origins=["*"]`, `allow_credentials=True` | Restrict origins per environment |
| High | Test-video upload returns absolute server path and uses user filename in path | `upload_seizure_test_video` | Sanitize filenames, restrict extensions/size, do not expose absolute paths |
| High | Manual critical seizure alert endpoint exists | `/api/monitoring/seizure/trigger-alert` | Add audit metadata, strict role checks, rate limits, documentation |
| Medium | Admin random assignment clears all assignments | `assign_patients` deletes table | Add confirmation, audit log, dry-run, docs |
| Medium | Mock frontend tokens are fake JWT-shaped values | `api/client.js` mock mode | Ensure mock mode cannot be enabled in production |
| Medium | SQLite deployed for large clinical dataset | `.env`, DB size | Use PostgreSQL or document SQLite as demo-only |
| Medium | No migration system found | `Base.metadata.create_all()` | Add Alembic or equivalent |
| Low | Uploaded static files directory mounted globally | `/uploads` mount | Confirm only intended public files are stored |

## Production Readiness Assessment

Overall classification: Pilot Prototype / Advanced Demo  
Overall score: 5/10

| Component | Score / 10 | Reason |
| --------- | ---------- | ------ |
| Main FastAPI backend | 7 | Imports, routes, auth, RBAC, DB access work; docs drift and service dependencies remain |
| React frontend | 7 | Builds and routes are feature-rich; mock mode and placeholder ECG weaken runtime truth |
| Medical chat/RAG | 6 | Pipeline implemented; LLM/Ollama runtime not verified; endpoint docs stale |
| Database layer | 5 | Large SQLite dataset works, but docs claim PostgreSQL and migrations are absent |
| Auth/RBAC | 6 | Role gates work; docs stale and CORS/secret handling need hardening |
| Arrhythmia service | 5 | Service imports and health works; not running on deployed port; ECG input placeholder |
| Fall detection service | 5 | Service imports and health works; not running on deployed port; live camera path depends on manual startup |
| Seizure detection service | 4 | Rich pipeline assets exist; startup path mismatch likely breaks real sessions |
| Monitoring/alerts | 6 | Tables, alert manager, WS, dashboards exist; service unavailability means no live inference |
| Testing/QA | 4 | Tests documented but pytest missing in configured env; no passing suite run |
| Deployment scripts | 4 | Start scripts exist but do not validate readiness, omit React, and seizure path mismatch remains |
| Security posture | 4 | Basic JWT/bcrypt present; secrets, CORS, uploads, and manual alert endpoints need hardening |

## Final Assessment

The implementation exceeds the original medical-history-chatbot docs in breadth, but not in documentation parity. The deployed repository is best described as a unified medical monitoring demo with a working main API, working React build, populated SQLite database, and importable AI microservices. It is not yet a verified production deployment because runtime services are not active, the seizure service has a concrete executable-path defect, pytest is missing from the configured Python environment, several UI flows rely on mock/placeholder data, and the docs do not reflect the actual API/database/security surface.

Priority fixes:

1. Update docs to match current API, RBAC, SQLite/PostgreSQL choice, monitoring endpoints, and service startup.
2. Fix seizure executable path or build layout expected by `service.py`.
3. Add a real deployment smoke script that starts all four backend services, waits for `/health`, verifies model readiness, and starts/serves the React frontend.
4. Replace placeholder ECG generation with real uploaded/persisted ECG input or label the feature demo-only.
5. Harden `.env`, CORS, uploads, manual alert endpoints, and admin assignment operations.
6. Install test dependencies in the documented environment and make `docs/tests/run_all_tests.sh` pass against the current RBAC/API.
