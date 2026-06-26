# Medical Monitoring System

This repository implements a multi-service medical monitoring platform with a FastAPI backend, React frontend, and three AI inference services for arrhythmia, fall, and seizure alerts [source: `backend/main.py`, `frontend-react/src/App.jsx`, `Repos/Arrythmia-Detection-master/service.py`, `Repos/Patient-fall-detection-system-main/service.py`, `Repos/seizure_detection/service.py`]. Clinical outputs are normalized into active alerts, alert history records, room status updates, and WebSocket events [source: `backend/models.py`, `backend/services/alert_manager.py`, `backend/routers/rooms.py`, `backend/routers/monitoring.py`].

The seizure subsystem combines a native C++ ONNX Runtime executable with a Python ViViT token producer over Win32 Named Pipes [source: `Repos/seizure_detection/runtime/src/full_runtime.cpp`, `Repos/seizure_detection/runtime/vivit_ipc_server.py`, `Repos/seizure_detection/service.py`]. The fall subsystem uses YOLO tracking, MobileNet role classification, MediaPipe pose extraction, and CTR-GCN motion recognition [source: `Repos/Patient-fall-detection-system-main/service.py`]. The arrhythmia subsystem uses a two-stage ECG cascade: Normal/Abnormal followed by abnormal subtype classification [source: `Repos/Arrythmia-Detection-master/service.py`].

## 1. Title & Description

**Project name:** Medical Monitoring System [source: `backend/main.py`].

**Primary function:** authenticated hospital staff can manage rooms and patients, start monitoring sessions, submit ECG signals, receive real-time clinical alerts, and acknowledge/cancel alert records [source: `backend/routers/rooms.py`, `backend/routers/monitoring.py`, `backend/routers/arrhythmia.py`, `backend/routers/dashboard.py`].

**Key model architectures:** arrhythmia uses a two-stage ECG PyTorch cascade; fall uses YOLO plus MediaPipe plus CTR-GCN; seizure uses OpenPose ONNX, VSViG ONNX, Python ViViT joint tokens, a Cross-Joint ONNX head, and a C++ series gate [source: `Repos/Arrythmia-Detection-master/service.py`, `Repos/Patient-fall-detection-system-main/service.py`, `Repos/seizure_detection/runtime/src/full_runtime.cpp`, `Repos/seizure_detection/runtime/vivit_ipc_server.py`].

**Final outputs:** persisted `alerts`, persisted `alert_history`, live `/api/ws/alerts` WebSocket messages, room status updates, seizure CSV rows, and service log files [source: `backend/models.py`, `backend/services/alert_manager.py`, `Repos/seizure_detection/service.py`, `start_all_services.ps1`].

## 2. Project Overview

**Project Goal:** Provide a role-aware medical monitoring application that centralizes patient records, room monitoring services, AI-generated alerts, and real-time dashboard updates [source: `backend/main.py`, `backend/models.py`, `frontend-react/src/App.jsx`].

**Objective:** The repository defines model thresholds, latches, and runtime profiling hooks, but it does not define a single global target FPS or accuracy target in source code. Therefore: **Unable to verify from repository.** The C++ seizure runtime prints processing FPS and per-component mean timings after a run [source: `Repos/seizure_detection/runtime/src/full_runtime.cpp`].

**Deployment Architecture:** The intended Windows launcher starts four Python/Uvicorn processes: main backend on port `8000`, arrhythmia on `8001`, fall detection on `8002`, and seizure detection on `8003` [source: `start_all_services.ps1`]. The seizure service starts an additional C++ subprocess and Python token-producer thread per session [source: `Repos/seizure_detection/service.py`].

**Evaluation Architecture:** Seizure evaluation scripts exist for segment metrics and runtime clinical summaries; fall evaluation scripts exist for YOLO, role classification, sliding-window fall motion, and runtime visualizations; arrhythmia training/evaluation results are stored under model result folders, but generated result files are not treated as source-of-truth in this README [source: `Repos/seizure_detection/evaluation/evaluate_segments.py`, `Repos/seizure_detection/evaluation/evaluate_runtime.py`, `Repos/Patient-fall-detection-system-main/evaluation/scripts/evaluate_fall_motion_sliding_windows_72f.py`, `Repos/Patient-fall-detection-system-main/evaluation/scripts/evaluate_role_classification_mobilenetv3.py`, `Repos/Patient-fall-detection-system-main/evaluation/scripts/evaluate_patient_detection_yolo.py`, `Repos/Arrythmia-Detection-master/src/evaluate.py`].

## 3. Pipeline Architecture Diagrams

### Overall Architecture

```mermaid
flowchart LR
  UI["React frontend\nfrontend-react/src"] -->|"Axios + JWT"| API["Main FastAPI backend\nbackend/main.py"]
  UI -->|"WS /api/ws/alerts?token=JWT"| AM["AlertManager\nbackend/services/alert_manager.py"]
  API --> DB["SQLAlchemy DB\nbackend/database.py + backend/models.py"]
  API -->|"HTTP /predict"| ARR["Arrhythmia service\nRepos/Arrythmia-Detection-master/service.py"]
  API -->|"HTTP /sessions + WS /ws/{room_id}"| FALL["Fall service\nRepos/Patient-fall-detection-system-main/service.py"]
  API -->|"HTTP /sessions + WS /ws/{session_id}"| SEIZ["Seizure service\nRepos/seizure_detection/service.py"]
  SEIZ --> CPP["C++ runtime\nruntime/src/full_runtime.cpp"]
  SEIZ --> PY["Python token producer\nservice.py thread / vivit_ipc_server.py"]
  PY -->|"Win32 named pipe VIVT packet"| CPP
  CPP -->|"CSV alert rows"| SEIZ
  ARR -->|"classification JSON"| API
  FALL -->|"fall event JSON"| API
  SEIZ -->|"seizure event JSON"| API
  API -->|"publish()"| AM
  AM --> UI
```

### Runtime Execution

```mermaid
sequenceDiagram
  participant User
  participant API as backend/routers/monitoring.py
  participant SeizSvc as Repos/seizure_detection/service.py
  participant CPP as seizure_runtime_cpp.exe
  participant Py as Python token thread
  participant Pipe as Named Pipe
  participant Gate as SeizureGate
  participant Alert as AlertManager
  participant UI as React WebSocket client

  User->>API: POST /api/monitoring/seizure/start
  API->>SeizSvc: POST /sessions
  SeizSvc->>CPP: subprocess run --source --output-csv --pipe-name
  SeizSvc->>Py: thread _run_token_producer(pipe_name)
  CPP->>CPP: OpenCV capture loop
  CPP->>CPP: OpenPose ONNX and VSViG ONNX
  Py->>Pipe: write VIVT packet
  CPP->>Pipe: ReadFile payload
  CPP->>CPP: CJ ONNX inference
  CPP->>Gate: decide_from_signals()
  CPP->>SeizSvc: append CSV row
  SeizSvc->>API: WS event subscription callback
  API->>Alert: publish() on transition to SEIZURE
  Alert->>UI: alert + room_update
```

### IPC Communication

```mermaid
sequenceDiagram
  participant CppThread as C++ IPC thread
  participant Pipe as "\\.\pipe\seizure_vivit_tokens[_session]"
  participant PyProducer as Python token producer
  participant CJ as CJ ONNX session

  CppThread->>Pipe: CreateNamedPipeA(..., PIPE_ACCESS_INBOUND, PIPE_TYPE_MESSAGE)
  PyProducer->>Pipe: open(pipe_name, "wb")
  CppThread->>Pipe: ConnectNamedPipe()
  PyProducer->>Pipe: struct.pack("4s d d d", b"VIVT", time_sec, token_build_ms, vivit_ms)
  PyProducer->>Pipe: append tokens float32[14*768]
  PyProducer->>Pipe: append positions float32[14*30*3]
  CppThread->>Pipe: ReadFile(sizeof(payload))
  CppThread->>CppThread: validate magic == "VIVT"
  CppThread->>CJ: tensors (1,14,768), (1,14,30,3)
  CJ-->>CppThread: probability
```

### Directory Dependency Graph

```mermaid
flowchart TB
  Root["Repository root"] --> Backend["backend/"]
  Root --> Frontend["frontend-react/"]
  Root --> Repos["Repos/"]
  Root --> Scripts["start_all_services.ps1 / .sh"]
  Backend --> Routers["backend/routers/"]
  Backend --> Services["backend/services/"]
  Backend --> Models["backend/models.py"]
  Services --> ArrClient["arrhythmia_client.py"]
  Services --> FallClient["fall_detection_client.py"]
  Services --> SeizClient["seizure_detection_client.py"]
  Repos --> ArrRepo["Arrythmia-Detection-master/"]
  Repos --> FallRepo["Patient-fall-detection-system-main/"]
  Repos --> SeizRepo["seizure_detection/"]
  SeizRepo --> CppRuntime["runtime/src + runtime/include"]
  SeizRepo --> SeizModels["model_weights/"]
  FallRepo --> FallRuntime["runtime/"]
  FallRepo --> FallModels["model_weights/"]
  ArrRepo --> ArrSrc["src/"]
  ArrRepo --> ArrModels["models/"]
```

## 4. Component Execution & Fallback Heuristics

1. Authentication starts at `/api/auth/login`; JWT payloads contain `sub`, `role`, and `name`; role gates are implemented by `require_role` [source: `backend/routers/auth.py`, `backend/auth.py`].
2. Room state is computed by querying active alerts for the room patient and deriving `Monitoring`, `Warning`, `Critical Alert`, `Idle`, `Offline`, or `Disconnected` [source: `backend/routers/rooms.py`].
3. Arrhythmia analysis accepts `patient_id`, `signal`, and optional `qrs7`, verifies patient access, calls the arrhythmia service, and persists an alert only when stage 1 is `Abnormal` [source: `backend/routers/arrhythmia.py`].
4. Fall monitoring creates a room session, then `/api/ws/camera/{room_id}` bridges binary JPEG frames to the fall service WebSocket and publishes an alert on a rising edge of `fall_detected` [source: `backend/routers/monitoring.py`].
5. The fall service decodes each JPEG, tracks people with YOLO, classifies role periodically, filters non-patient tracks, extracts MediaPipe pose, fills a 72-frame sequence, and runs CTR-GCN every `INFER_EVERY` frames [source: `Repos/Patient-fall-detection-system-main/service.py`].
6. Seizure monitoring starts a seizure service session, sets room state to `Initializing`, subscribes to the seizure service WebSocket, and publishes an alert on transition into `SEIZURE` [source: `backend/routers/monitoring.py`].
7. The seizure service creates a C++ subprocess, starts an in-process Python token-producer thread, tails a CSV alert log, and broadcasts typed WebSocket events [source: `Repos/seizure_detection/service.py`].
8. The C++ seizure runtime captures frames through OpenCV, extracts OpenPose keypoints, builds VSViG patches, reads ViViT/CJ data from a named pipe, applies the series gate, writes CSV rows, and prints profiling information at completion [source: `Repos/seizure_detection/runtime/src/full_runtime.cpp`].

**Degraded/Fallback Mode**

- Arrhythmia client fallback: network, timeout, or HTTP errors are converted into a degraded dict where all prediction fields are `None`, `all_probabilities` is `{}`, and `error` contains the failure message [source: `backend/services/arrhythmia_client.py`].
- Fall client fallback: health, create, delete, list, and reset failures return error dictionaries or empty session lists instead of throwing directly to callers [source: `backend/services/fall_detection_client.py`].
- Seizure client fallback: health failures return `{"status": "unreachable", "error": ...}`, session list failures return `[]`, and start/stop/reset failures return `{"error": ...}` [source: `backend/services/seizure_detection_client.py`].
- Seizure gate warm-up fallback: before any Cross-Joint sample has been seen, `SeizureGate` returns `INITIALISING`, score `0.0`, source `INITIALISING`, and an unlatched alert [source: `Repos/seizure_detection/runtime/include/seizure_gate.hpp`].
- Seizure gate stale-side-channel throttle: file replay waits when `time_sec - current_cj_time > max_cj_age_sec`, whose default is `5.5` seconds [source: `Repos/seizure_detection/runtime/src/full_runtime.cpp`, `Repos/seizure_detection/runtime/include/seizure_gate.hpp`].
- Fall latch fallback: if a track is latched, the latch automatically clears after `30.0` seconds; reset endpoints also clear fall latch fields [source: `Repos/Patient-fall-detection-system-main/service.py`].
- Alert expiration fallback: active alerts older than 24 hours are deleted by a background loop that checks once every 60 seconds and broadcasts an `expire` event [source: `backend/services/alert_manager.py`, `backend/main.py`].

## 5. Repository Structure

```text
.
|-- backend/ <- FastAPI backend, SQLAlchemy models, RBAC, routers, service clients
|   |-- main.py <- app registration, CORS, static uploads, startup alert cleanup
|   |-- models.py <- users, patients, alerts, rooms, services, assignments
|   |-- auth.py <- bcrypt helpers, JWT creation/validation, role gates
|   |-- database.py <- DATABASE_URL handling and SQLAlchemy session factory
|   |-- routers/ <- auth, patients, chat, uploads, users, arrhythmia, monitoring, dashboard, rooms
|   `-- services/ <- alert manager, LLM helpers, arrhythmia/fall/seizure clients
|-- frontend-react/ <- Vite React UI
|   |-- package.json <- frontend dependencies and scripts
|   `-- src/ <- routes, pages, stores, hooks, API client
|-- Repos/
|   |-- Arrythmia-Detection-master/ <- ECG arrhythmia microservice and model code
|   |-- Patient-fall-detection-system-main/ <- fall detection service, runtime, training/evaluation code
|   `-- seizure_detection/ <- seizure service, C++ runtime, configs, model weights, evaluation code
|-- start_all_services.ps1 <- Windows launcher for four Uvicorn services
|-- start_all_services.sh <- Linux launcher, contains a path conflict documented below
|-- requirements.txt <- main backend dependency list
|-- .env.example <- documented environment variable template
`-- README.md <- this file
```

## 6. Hardware Requirements

**Minimum Hardware:** Unable to verify from repository. No source or configuration file specifies minimum CPU cores, RAM, VRAM, or SSD capacity.

**Recommended Hardware:** Unable to verify from repository. No source or configuration file specifies target CPU or GPU models.

**Expected Runtime Speed:** The C++ seizure runtime prints `Steady-state Processing FPS`, OpenPose mean time, VSViG patch mean time, VSViG runtime mean time, CJ head mean time, and gate mean time after a run [source: `Repos/seizure_detection/runtime/src/full_runtime.cpp`]. Fixed expected numeric FPS is not hard-coded in source; **Unable to verify from repository.**

**Known Bottlenecks:** The Python ViViT token producer measures token-building time and ViViT time, while the C++ side measures CJ ONNX time; these timing fields are serialized in the IPC packet and written to telemetry CSV when enabled [source: `Repos/seizure_detection/runtime/vivit_ipc_server.py`, `Repos/seizure_detection/runtime/src/full_runtime.cpp`]. The seizure service also performs global PyTorch model loading and background warm-up [source: `Repos/seizure_detection/service.py`].

## 7. Software Prerequisites

**Operating Systems:** Windows is explicitly required by the active seizure C++ named-pipe implementation because `full_runtime.cpp` includes `windows.h` and uses `CreateNamedPipeA`, `ConnectNamedPipe`, `ReadFile`, and `DisconnectNamedPipe` [source: `Repos/seizure_detection/runtime/src/full_runtime.cpp`]. Linux/macOS support for the full seizure IPC runtime is **Not implemented** in the active C++ IPC code, although `start_all_services.sh` exists [source: `start_all_services.sh`, `Repos/seizure_detection/runtime/src/full_runtime.cpp`].

**Python packages:** main backend dependencies are pinned in `requirements.txt`: FastAPI `0.111.0`, Uvicorn `0.30.1`, SQLAlchemy `2.0.30`, Pydantic `2.7.1`, Python-Jose `3.3.0`, Passlib bcrypt `1.7.4`, HTTPX `0.27.0`, WebSockets `12.0`, Pandas `2.2.2`, plus AI packages including OpenCV, Ultralytics, Transformers, timm, WFDB, PyYAML, tqdm, matplotlib, TensorBoardX, and Pillow [source: `requirements.txt`].

**Frontend packages:** React `^18.3.1`, React DOM `^18.3.1`, React Router DOM `^6.24.0`, Zustand `^4.5.2`, Recharts `^2.12.7`, Axios `^1.7.2`, Vite `^5.3.1`, Tailwind CSS `^3.4.4`, and related tooling are declared in `frontend-react/package.json` [source: `frontend-react/package.json`].

**C++ build tools:** CMake minimum version is `3.16`, C++17 is required, MSVC builds use `/W4 /WX /utf-8`, and non-MSVC builds use `-Wall -Wextra -O2` [source: `Repos/seizure_detection/runtime/CMakeLists.txt`].

**CUDA/cuDNN:** The code prepends CUDA `v12.2` bin directories when present, but it does not specify a cuDNN version [source: `Repos/seizure_detection/service.py`, `Repos/seizure_detection/runtime/vivit_ipc_server.py`]. cuDNN version: **Unable to verify from repository.**

## 8. Environment Setup Guide

Clone command: **Unable to verify from repository.** The repository does not include its remote URL in source/config files.

Create `.env` from the template:

```powershell
Copy-Item .env.example .env
```

The command above is valid because `.env.example` exists at the repository root [source: `.env.example`].

Install backend dependencies:

```powershell
python -m pip install -r requirements.txt
```

This command is valid because `requirements.txt` exists at repository root [source: `requirements.txt`].

Install frontend dependencies:

```powershell
cd frontend-react
npm install
npm run dev
```

These commands are valid because `frontend-react/package.json` defines `dev`, `build`, `preview`, and `lint` scripts [source: `frontend-react/package.json`].

**Dependency Paths:** The seizure C++ build expects ONNX Runtime at `Repos/seizure_detection/third_party/onnxruntime` and OpenCV/vcpkg libraries at `Repos/seizure_detection/third_party/vcpkg_installed/x64-windows` [source: `Repos/seizure_detection/runtime/CMakeLists.txt`].

**Database default:** code defaults to SQLite at `sqlite:///./medical_db.db` if `DATABASE_URL` is unset [source: `backend/database.py`]. `.env.example` instead recommends PostgreSQL at `postgresql://medical_user:medical_pass_2025@localhost:5432/medical_db` [source: `.env.example`]. Actual implementation is the code default when `.env` is absent [source: `backend/database.py`].

## 9. Model Checkpoints & Assets

| Model File | Source | Input | Output | Purpose |
|---|---|---|---|---|
| `Repos/seizure_detection/model_weights/pose.onnx` | `Args.pose_onnx_path` | normalized OpenPose frame tensor | heatmap/output tensors | C++ OpenPose keypoint extraction [source: `Repos/seizure_detection/runtime/src/full_runtime.cpp`, `Repos/seizure_detection/configs/default.yaml`] |
| `Repos/seizure_detection/model_weights/vsvig_protogcn.onnx` | `Args.vsvig_onnx_path` | `(1,30,15,3,32,32)` patches and `(1,30,15,3)` keypoints | VSViG logit/probability output | C++ seizure visual risk branch [source: `Repos/seizure_detection/runtime/src/full_runtime.cpp`, `Repos/seizure_detection/configs/default.yaml`] |
| `Repos/seizure_detection/model_weights/cj_final.onnx` | `Args.cj_head_onnx_path` | `(1,14,768)` tokens and `(1,14,30,3)` positions | Cross-Joint probability | C++ CJ head inference [source: `Repos/seizure_detection/runtime/src/full_runtime.cpp`, `Repos/seizure_detection/configs/default.yaml`] |
| `Repos/seizure_detection/model_weights/pose.pth` | `--pose-weights` | video frame via Python pose utilities | OpenPose keypoints | Python ViViT sidecar pose extraction [source: `Repos/seizure_detection/runtime/vivit_ipc_server.py`] |
| `google/vivit-b-16x2-kinetics400` | `--vivit-name` / `VivitModel.from_pretrained` | ViViT tubelets | joint token embeddings | Python ViViT token generation [source: `Repos/seizure_detection/runtime/vivit_ipc_server.py`, `Repos/seizure_detection/service.py`] |
| `Repos/Patient-fall-detection-system-main/model_weights/patient_detection_yolov8n.pt` | `YOLO_WEIGHTS` | BGR image frame | tracked person boxes | patient/person detection [source: `Repos/Patient-fall-detection-system-main/service.py`] |
| `Repos/Patient-fall-detection-system-main/model_weights/role_classification_mobilenetv3_best.pt` | `ROLE_WEIGHTS` | cropped person image | role label/confidence | patient/staff/other filtering [source: `Repos/Patient-fall-detection-system-main/service.py`] |
| `Repos/Patient-fall-detection-system-main/model_weights/fall_motion_ctrgcn_72f_impact.pt` | `FALL_WEIGHTS` | `(1,3,72,25,2)` skeleton tensor | fall/non-fall logits | CTR-GCN fall motion classification [source: `Repos/Patient-fall-detection-system-main/service.py`] |
| `Repos/Arrythmia-Detection-master/models/binary_normal_abnormal/checkpoints/best.pt` | `BINARY_CKPT` | `(1,5000,12)` ECG plus `(1,7)` QRS | Normal/Abnormal logits | binary ECG screening [source: `Repos/Arrythmia-Detection-master/service.py`] |
| `Repos/Arrythmia-Detection-master/models/abnormal_subtype/checkpoints/best.pt` | `SUBTYPE_CKPT` | `(1,5000,12)` ECG plus `(1,7)` QRS | AF/IAVB/SB/STach logits | abnormal ECG subtype classification [source: `Repos/Arrythmia-Detection-master/service.py`] |
| `medical_db.db` | `DATABASE_URL` fallback | SQLAlchemy ORM records | SQLite tables | default local database [source: `backend/database.py`] |

Offline Hugging Face behavior is enabled for seizure ViViT by setting `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, and `HF_HUB_DISABLE_TELEMETRY=1` [source: `Repos/seizure_detection/runtime/vivit_ipc_server.py`, `Repos/seizure_detection/service.py`].

## 10. Build Instructions

Build the seizure C++ runtime on Windows:

```powershell
cd Repos\seizure_detection\runtime
.\build_and_test_windows.cmd
```

This command is valid because `build_and_test_windows.cmd` exists and calls Visual Studio `VsDevCmd.bat`, CMake with Ninja, builds Release, runs `seizure_gate_replay.exe test`, runs CTest, and runs `seizure_gate_replay.exe bench` [source: `Repos/seizure_detection/runtime/build_and_test_windows.cmd`].

Manual CMake build:

```powershell
cd Repos\seizure_detection\runtime
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
```

These commands match the CMake source tree and build directory used by the build script [source: `Repos/seizure_detection/runtime/build_and_test_windows.cmd`, `Repos/seizure_detection/runtime/CMakeLists.txt`].

The build creates `seizure_gate_replay` from `src/main.cpp` and `seizure_runtime_cpp` from `src/full_runtime.cpp`; it links ONNX Runtime and OpenCV libraries and copies ONNX Runtime provider DLLs after build [source: `Repos/seizure_detection/runtime/CMakeLists.txt`].

## 11. Consolidated Runtime Parameters

| Name | Default Value | Source File | Why & Effect |
|---|---:|---|---|
| `DATABASE_URL` | `sqlite:///./medical_db.db` | `backend/database.py` | Selects SQLite or non-SQLite SQLAlchemy engine; SQLite uses `check_same_thread=False`. |
| `SECRET_KEY` | no code default | `backend/auth.py` | JWT signing secret; if missing, token creation/validation cannot be considered production-safe. |
| `ALGORITHM` | `HS256` | `backend/auth.py` | JWT signing algorithm. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | `backend/auth.py` | Controls JWT expiration window. |
| `ARRHYTHMIA_SERVICE_URL` | `http://localhost:8001` | `backend/services/arrhythmia_client.py` | Backend URL for ECG inference; failures degrade to error dict. |
| `FALL_DETECTION_SERVICE_URL` | `http://localhost:8002` | `backend/services/fall_detection_client.py` | Backend URL for fall REST/WS service; failures return error dicts or empty sessions. |
| `SEIZURE_DETECTION_SERVICE_URL` | `http://localhost:8003` | `backend/services/seizure_detection_client.py` | Backend URL for seizure REST/WS service. |
| `MAIN_PORT` | `8000` | `start_all_services.ps1`, `start_all_services.sh` | Main backend launcher port. |
| `ARRHYTHMIA_PORT` | `8001` | `start_all_services.ps1`, `start_all_services.sh` | Arrhythmia service launcher port. |
| `FALL_DETECTION_PORT` | `8002` | `start_all_services.ps1`, `start_all_services.sh` | Fall service launcher port. |
| `SEIZURE_DETECTION_PORT` | `8003` | `start_all_services.ps1`, `start_all_services.sh` | Seizure service launcher port. |
| `FALL_THRESHOLD` | `0.90` | `Repos/Patient-fall-detection-system-main/service.py` | Higher values reduce fall alerts; lower values increase sensitivity and false-positive risk. |
| `ROLE_THRESHOLD` | `0.50` | `Repos/Patient-fall-detection-system-main/service.py` | Minimum role confidence to treat a tracked person as a patient. |
| `INFER_EVERY` | `6` | `Repos/Patient-fall-detection-system-main/service.py` | CTR-GCN stride after the 72-frame buffer is full; smaller values increase compute and responsiveness. |
| `ROLE_EVERY` | `10` | `Repos/Patient-fall-detection-system-main/service.py` | MobileNet role-refresh interval per track. |
| `WINDOW_SIZE` | `72` | `Repos/Patient-fall-detection-system-main/service.py` | Number of pose frames required for fall motion inference. |
| `GATE_UPPER_BOUND` | `0.50` | `Repos/seizure_detection/runtime/include/seizure_gate.hpp` | Above this CJ probability, CJ score is trusted directly. |
| `GATE_LOWER_BOUND` | `0.20` | `Repos/seizure_detection/runtime/include/seizure_gate.hpp` | Between lower and upper bounds, CJ and VSViG are blended. |
| `GATE_ALPHA` | `0.30` | `Repos/seizure_detection/runtime/include/seizure_gate.hpp` | CJ blend weight; VSViG weight is `0.70`. |
| `ALERT_HOLD_SEC` | `30.0` | `Repos/seizure_detection/runtime/include/seizure_gate.hpp` | Keeps seizure status latched after a raw alarm. |
| `CJ_MAX_AGE_SEC` | `5.5` | `Repos/seizure_detection/runtime/include/seizure_gate.hpp` | Maximum CJ lag used by replay throttle and freshness logic. |
| `THRESHOLD_SAFETY` | `0.88` | `Repos/seizure_detection/runtime/include/seizure_gate.hpp` | High seizure gate threshold for safety mode. |
| `THRESHOLD_MONITOR` | `0.49` | `Repos/seizure_detection/runtime/include/seizure_gate.hpp` | Default monitor threshold selected by `threshold_for`. |
| `THRESHOLD_HELD_OUT` | `0.3081087228480716` | `Repos/seizure_detection/runtime/include/seizure_gate.hpp` | Constant exists but is not selected by `threshold_for`; effect in deployed gate is not active unless custom threshold is passed. |
| `vsvig_sample_fps` | `6.0` | `Repos/seizure_detection/configs/default.yaml`, `full_runtime.cpp` | Controls VSViG/OpenPose sampling cadence. |
| `inference_stride` | `15` | `Repos/seizure_detection/configs/default.yaml`, `full_runtime.cpp` | Controls VSViG decision cadence in frames. |
| `warmup_runs` | `3` | `Repos/seizure_detection/configs/default.yaml`, `full_runtime.cpp` | ONNX warm-up iterations excluded from profiling when applicable. |
| `--pipe-name` | `\\.\pipe\seizure_vivit_tokens` | `Repos/seizure_detection/runtime/vivit_ipc_server.py`, `full_runtime.cpp` | Named-pipe endpoint for ViViT token packets. |
| `--slide-sec` | `5.0` | `Repos/seizure_detection/runtime/vivit_ipc_server.py` | ViViT/CJ segment slide interval; larger values reduce CJ frequency and compute. |
| `VITE_DATA_MODE` | mock unless exactly `live` | `frontend-react/src/api/client.js`, `frontend-react/src/hooks/useAlertsWS.js` | Selects mock data or live HTTP/WebSocket calls. |
| `VITE_API_URL` | `http://localhost:8000` | `frontend-react/src/api/client.js` | Frontend API base URL. |
| `VITE_WS_URL` | `ws://localhost:8000` | `frontend-react/src/hooks/useAlertsWS.js` | Frontend WebSocket base URL. |

## 12. Named Pipe / IPC Protocol Specifications

The active seizure IPC channel is a Win32 named pipe. The C++ runtime opens it with `CreateNamedPipeA(args.pipe_name.c_str(), PIPE_ACCESS_INBOUND, PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT, 1, 65536, 65536, 0, NULL)` [source: `Repos/seizure_detection/runtime/src/full_runtime.cpp`]. The standalone Python IPC script defaults to `\\.\pipe\seizure_vivit_tokens`; the service per-session runtime uses `\\.\pipe\seizure_vivit_tokens_{session_id}` [source: `Repos/seizure_detection/runtime/vivit_ipc_server.py`, `Repos/seizure_detection/service.py`].

**Ownership:** C++ owns pipe creation and reads packets; Python opens the pipe in binary write mode and writes ViViT/CJ payloads [source: `Repos/seizure_detection/runtime/src/full_runtime.cpp`, `Repos/seizure_detection/runtime/vivit_ipc_server.py`, `Repos/seizure_detection/service.py`].

**Packet structure:** The packet has `4` bytes of magic (`VIVT`), `3` doubles (`24` bytes), `14*768` float32 token values (`43,008` bytes), and `14*30*3` float32 position values (`5,040` bytes). Total payload size is `52,076` bytes [source: `Repos/seizure_detection/runtime/src/full_runtime.cpp`, `Repos/seizure_detection/runtime/vivit_ipc_server.py`].

**Serialization:** Python uses `struct.pack("4s d d d", b"VIVT", time_sec, token_build_ms, vivit_ms)`, then appends `tokens_np.tobytes()` and `pos_np.tobytes()` [source: `Repos/seizure_detection/runtime/vivit_ipc_server.py`, `Repos/seizure_detection/service.py`].

**Synchronization:** C++ blocks in `ConnectNamedPipe` and then calls `ReadFile` for exactly `sizeof(payload)` bytes; it drops the connection if read size is incorrect or magic is not `VIVT` [source: `Repos/seizure_detection/runtime/src/full_runtime.cpp`].

**Connection recovery:** The standalone Python IPC script retries pipe connection once per second for up to 600 seconds; the service token-producer thread retries every 0.2 seconds for 300 iterations, which is 60 seconds [source: `Repos/seizure_detection/runtime/vivit_ipc_server.py`, `Repos/seizure_detection/service.py`].

## 13. Running Implementation

Run all Windows services:

```powershell
.\start_all_services.ps1
```

This command is valid because `start_all_services.ps1` exists and starts arrhythmia, fall, seizure, and backend Uvicorn processes [source: `start_all_services.ps1`].

Run all Linux/macOS-style services:

```bash
chmod +x start_all_services.sh
./start_all_services.sh
```

The script exists, but it references `Repos/Seizure-Detection-main` for the seizure service while the active repository path used elsewhere is `Repos/seizure_detection`; this is a verified conflict [source: `start_all_services.sh`, `start_all_services.ps1`, `backend/services/seizure_detection_client.py`]. Use the Windows launcher or fix the shell script path before relying on it.

Run individual services:

```powershell
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
python -m uvicorn service:app --host 0.0.0.0 --port 8001 --no-access-log
python -m uvicorn service:app --host 0.0.0.0 --port 8002 --no-access-log
python -m uvicorn service:app --host 0.0.0.0 --port 8003 --no-access-log
```

The service commands are valid only when run from their corresponding directories: repository root for `backend.main:app`, `Repos/Arrythmia-Detection-master` for port `8001`, `Repos/Patient-fall-detection-system-main` for port `8002`, and `Repos/seizure_detection` for port `8003` [source: `start_all_services.ps1`, `Repos/Arrythmia-Detection-master/service.py`, `Repos/Patient-fall-detection-system-main/service.py`, `Repos/seizure_detection/service.py`].

Run frontend development server:

```powershell
cd frontend-react
npm run dev
```

This command is valid because the `dev` script is declared as `vite` [source: `frontend-react/package.json`].

## 14. Output Files & Logs

| Output | Producer | Schema / Contents | Source |
|---|---|---|---|
| `logs/arrhythmia.log`, `logs/arrhythmia.err.log` | Windows launcher | stdout/stderr for arrhythmia service | `start_all_services.ps1` |
| `logs/fall_detection.log`, `logs/fall_detection.err.log` | Windows launcher | stdout/stderr for fall service | `start_all_services.ps1` |
| `logs/seizure_detection.log`, `logs/seizure_detection.err.log` | Windows launcher | stdout/stderr for seizure service | `start_all_services.ps1` |
| `logs/main_backend.log`, `logs/main_backend.err.log` | Windows launcher | stdout/stderr for backend service | `start_all_services.ps1` |
| `Repos/seizure_detection/runtime_outputs/alert_logs/{session_id}_alerts.csv` | Seizure C++ runtime and service | `frame,time_sec,status,seizure_signal,seizure_source,current_risk,cj_prob,cj_age_sec,alert_latched` | `Repos/seizure_detection/runtime/src/full_runtime.cpp`, `Repos/seizure_detection/service.py` |
| `{session_id}_alerts_cj_telemetry.csv` | Seizure C++ runtime | `sample_time,token_build_ms,vivit_ms,onnx_ms,activated_time,age_sec,prob` as written by telemetry loop | `Repos/seizure_detection/runtime/src/full_runtime.cpp` |
| `{session_id}_cpp_stdout.log`, `{session_id}_cpp_stderr.log`, `{session_id}_py_stdout.log`, `{session_id}_py_stderr.log` | Seizure service | per-session subprocess/thread logs | `Repos/seizure_detection/service.py` |
| `/api/ws/alerts` event | Backend AlertManager | JSON event with `type`, `id`, `patient_id`, `alert_type`, `severity`, `details`, `created_at` for alerts | `backend/services/alert_manager.py` |
| `/ws/{session_id}` seizure event | Seizure service | JSON event with `frame`, `time_sec`, `status`, `gate_score`, `seizure_source`, `current_risk`, `cj_prob`, `alert`, `alert_latched`, `ready`, `timestamp` | `Repos/seizure_detection/service.py` |
| `/ws/{room_id}` fall event | Fall service | JSON with `fall_detected`, `fall_probability`, `track_id`, `timestamp`, `latch_active`, `latch_remaining` | `Repos/Patient-fall-detection-system-main/service.py` |

## 15. Reproducibility & Evaluation

Run seizure C++ unit tests and gate benchmark:

```powershell
cd Repos\seizure_detection\runtime
.\build\seizure_gate_replay.exe test
.\build\seizure_gate_replay.exe bench
```

The executable is produced by the CMake build; the subcommands are implemented in `src/main.cpp` [source: `Repos/seizure_detection/runtime/CMakeLists.txt`, `Repos/seizure_detection/runtime/src/main.cpp`].

Run seizure segment evaluation:

```powershell
cd Repos\seizure_detection
python evaluation\evaluate_segments.py
```

This script exists and defaults to `evaluation/results/official_test_scores.csv`, `evaluation/results/segment_metrics.json`, and threshold `DEFAULT_THRESHOLD` [source: `Repos/seizure_detection/evaluation/evaluate_segments.py`]. Exact expected AUROC/AUPRC values are **Unable to verify from repository without using generated result files**, which this README intentionally does not treat as source-of-truth.

Run seizure runtime clinical evaluation:

```powershell
cd Repos\seizure_detection
python evaluation\evaluate_runtime.py
```

This script exists and defaults its output JSON path to `evaluation/results/current_10_demo_clinical_summary_2026-06-19.json` [source: `Repos/seizure_detection/evaluation/evaluate_runtime.py`]. Exact LEO/LCO values are **Unable to verify from repository without using generated result files**.

Run fall sliding-window evaluation:

```powershell
cd Repos\Patient-fall-detection-system-main
python evaluation\scripts\evaluate_fall_motion_sliding_windows_72f.py
```

The script exists and defines defaults for `--weights`, `--out-dir`, `--cache-dir`, `--window-size 72`, `--window-stride 18`, and `--batch-size 64` [source: `Repos/Patient-fall-detection-system-main/evaluation/scripts/evaluate_fall_motion_sliding_windows_72f.py`].

Run arrhythmia cascade inference script:

```powershell
cd Repos\Arrythmia-Detection-master
python scripts\inference_cascade.py --input path\to\ecg.npy
```

The script exists and requires `--input`; optional `--qrs7` and `--device` are defined by argparse [source: `Repos/Arrythmia-Detection-master/scripts/inference_cascade.py`].

## 16. Verification Checklist

- [ ] `.env` exists and defines a production `SECRET_KEY` [source: `.env.example`, `backend/auth.py`].
- [ ] `python -m pip install -r requirements.txt` completes for the main backend [source: `requirements.txt`].
- [ ] `npm install` and `npm run dev` complete under `frontend-react` [source: `frontend-react/package.json`].
- [ ] `Repos/seizure_detection/runtime/build/seizure_runtime_cpp.exe` exists after CMake build [source: `Repos/seizure_detection/runtime/CMakeLists.txt`].
- [ ] ONNX Runtime and OpenCV third-party paths exist under `Repos/seizure_detection/third_party` [source: `Repos/seizure_detection/runtime/CMakeLists.txt`].
- [ ] Seizure model files exist under `Repos/seizure_detection/model_weights` [source: `Repos/seizure_detection/configs/default.yaml`].
- [ ] Fall model files exist under `Repos/Patient-fall-detection-system-main/model_weights` [source: `Repos/Patient-fall-detection-system-main/service.py`].
- [ ] Arrhythmia checkpoint files exist under `Repos/Arrythmia-Detection-master/models` [source: `Repos/Arrythmia-Detection-master/service.py`].
- [ ] `GET /api/health` returns `{"status":"ok"}` from the backend [source: `backend/main.py`].
- [ ] `GET /health` returns service health from arrhythmia, fall, and seizure services [source: `Repos/Arrythmia-Detection-master/service.py`, `Repos/Patient-fall-detection-system-main/service.py`, `Repos/seizure_detection/service.py`].
- [ ] Frontend live mode sets `VITE_DATA_MODE=live`, `VITE_API_URL`, and `VITE_WS_URL` [source: `frontend-react/src/api/client.js`, `frontend-react/src/hooks/useAlertsWS.js`].

## 17. Troubleshooting Guide

**JWT failures:** If login or authenticated routes fail, verify `SECRET_KEY`, `ALGORITHM`, and `ACCESS_TOKEN_EXPIRE_MINUTES`; token validation depends on those values [source: `backend/auth.py`].

**Database mismatch:** If PostgreSQL is expected but SQLite appears, check `DATABASE_URL`; code defaults to SQLite when the variable is missing, even though `.env.example` shows a PostgreSQL URL [source: `backend/database.py`, `.env.example`].

**Seizure service cannot find executable:** Build `Repos/seizure_detection/runtime/build/seizure_runtime_cpp.exe`; the seizure service expects that path in `CPP_RUN_EXE` [source: `Repos/seizure_detection/service.py`].

**Broken named pipe:** C++ must create the pipe before Python can open it; the Python producer retries for 60 seconds in service mode and then gives up [source: `Repos/seizure_detection/service.py`]. The standalone IPC script retries for 600 seconds [source: `Repos/seizure_detection/runtime/vivit_ipc_server.py`].

**CUDA DLL loading problems:** The seizure service and IPC script add CUDA `v12.2` and PyTorch library directories to DLL search paths when those directories exist [source: `Repos/seizure_detection/service.py`, `Repos/seizure_detection/runtime/vivit_ipc_server.py`].

**Fall service reports models not ready:** `/ws/{room_id}` closes with code `1013` when `_models_loaded` is false [source: `Repos/Patient-fall-detection-system-main/service.py`].

**Frontend shows mock behavior:** `VITE_DATA_MODE` defaults to mock behavior unless it is exactly `live` [source: `frontend-react/src/api/client.js`, `frontend-react/src/hooks/useAlertsWS.js`].

**Linux launcher starts wrong seizure directory:** `start_all_services.sh` uses `Repos/Seizure-Detection-main`, while active code and Windows launcher use `Repos/seizure_detection`; update the script or use `start_all_services.ps1` on Windows [source: `start_all_services.sh`, `start_all_services.ps1`].

## 18. References & Citations

The following references correspond to technologies and model families directly visible in source code or dependency manifests:

- OpenPose-style pose estimation is used through `pose.onnx` and `pose.pth` paths [source: `Repos/seizure_detection/runtime/src/full_runtime.cpp`, `Repos/seizure_detection/runtime/vivit_ipc_server.py`].
- ViViT is loaded by model name `google/vivit-b-16x2-kinetics400` [source: `Repos/seizure_detection/runtime/vivit_ipc_server.py`, `Repos/seizure_detection/service.py`].
- CTR-GCN is used by the fall model class and graph configuration [source: `Repos/Patient-fall-detection-system-main/service.py`].
- ONNX Runtime, OpenCV, FastAPI, React, Vite, Zustand, Axios, Recharts, MediaPipe, Ultralytics, PyTorch, and Transformers are visible in source/build/dependency files [source: `Repos/seizure_detection/runtime/CMakeLists.txt`, `requirements.txt`, `frontend-react/package.json`, `Repos/Patient-fall-detection-system-main/service.py`, `Repos/Arrythmia-Detection-master/service.py`].

```bibtex
@inproceedings{cao2017openpose,
  title={Realtime Multi-Person 2D Pose Estimation using Part Affinity Fields},
  author={Cao, Zhe and Simon, Tomas and Wei, Shih-En and Sheikh, Yaser},
  booktitle={CVPR},
  year={2017}
}

@inproceedings{arnab2021vivit,
  title={ViViT: A Video Vision Transformer},
  author={Arnab, Anurag and Dehghani, Mostafa and Heigold, Georg and Sun, Chen and Lucic, Mario and Schmid, Cordelia},
  booktitle={ICCV},
  year={2021}
}

@inproceedings{chen2021ctrgcn,
  title={Channel-wise Topology Refinement Graph Convolution for Skeleton-Based Action Recognition},
  author={Chen, Yuxin and Zhang, Ziqi and Yuan, Chunfeng and Li, Bing and Deng, Ying and Hu, Weiming},
  booktitle={ICCV},
  year={2021}
}

@misc{onnxruntime,
  title={ONNX Runtime},
  author={{Microsoft}},
  howpublished={Software},
  year={2026}
}

@misc{fastapi,
  title={FastAPI},
  author={Ramirez, Sebastian},
  howpublished={Software framework},
  year={2026}
}
```

