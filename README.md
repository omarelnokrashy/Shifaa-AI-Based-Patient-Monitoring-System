# Medical Monitoring System

This repository implements a multi-service medical monitoring platform with a FastAPI backend, React frontend, and three independent AI services for arrhythmia, fall, and seizure alerts. Clinical outputs are normalized into active alerts, alert history records, room status updates, and WebSocket events.

---

## 1. Repository Directory Structure

The project has been organized into a professional production-grade directory layout:

```text
.
├── backend/            # FastAPI backend application
│   ├── routers/        # API routers (auth, monitoring, rooms, chat, dashboard, uploads, users)
│   ├── services/       # Core business logic (AlertManager, LLM client, AI clients)
│   └── tests/          # Local backend unit & database tests
├── frontend/           # Vite React UI web application
├── services/           # Independent AI monitoring microservices
│   ├── arrhythmia/     # ECG classifier service (binary normal/abnormal & subtypes)
│   ├── fall_detection/ # YOLO + MediaPipe + CTR-GCN fall detection service
│   └── seizure_detection/ # C++ ONNX + Python ViViT seizure detection service
├── models/             # Centralized models directory (arrhythmia/, fall/, seizure/)
├── datasets/           # Static patient Synthea CSV datasets for bulk seeding
├── configs/            # Centralized env templates and configuration files
├── deployment/         # Docker, systemd, and orchestration assets
├── scripts/            # Shell and powershell start/stop launchers
├── tools/              # Developer database seed & data loading tools
├── tests/              # Unified integration and end-to-end tests
├── runtime/            # Generated log directories and transient temp files
├── uploads/            # Local clinical uploads & test media (preserved at root)
├── requirements.txt    # Main backend python dependency manifest
├── REPOSITORY_REFACTOR.md # Structural refactoring details and migration guide
└── README.md           # This file
```

---

## 2. Launching the Platform

### Windows Launcher
Run the startup script from the project root:
```powershell
./start_all_services.ps1
```
*(This launches the Main Backend on port `8000`, Arrhythmia Service on `8001`, Fall Detection on `8002`, and Seizure Detection on `8003`)*

### Linux/macOS Launcher
```bash
./start_all_services.sh
```

---

## 3. Database Ingestion & Seeding

All developer scripts are located inside the `/tools/` directory. Initialize the database schema and load seed data:

```bash
# 1. Seed database accounts and synthetic patients
python tools/seed.py

# 2. Seed ward rooms and ICU bed assignments
python tools/migrate_db_rooms.py

# 3. Load Synthea CSV patient datasets
python tools/load_synthea_csv.py
```

For more details on the refactored directory structure, import paths, and upgrade instructions, see [REPOSITORY_REFACTOR.md](file:///f:/GP/Deployment/Medical-History-Chatbot/REPOSITORY_REFACTOR.md).
