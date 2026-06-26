# 07 — Setup & Deployment Guide

## 7.1 Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.10+ | 3.11 recommended |
| PostgreSQL | 14+ | Must be running before starting backend |
| pip | latest | `pip install --upgrade pip` |
| Ollama (optional) | latest | Only if using local LLM backend |
| Internet access | — | Required for OpenAI backend |

---

## 7.2 Installation Steps

### Step 1 — Clone / locate the project

```bash
cd "/media/omar/Graduation Project/GP/Project"
```

### Step 2 — Create and activate a Python virtual environment

```bash
```bash
conda create -n medical_chatbot python=3.10 -y
conda activate medical_chatbot
```

### Step 3 — Install Python dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Configure environment variables

```bash
cp .env .env.backup   # keep a backup
nano .env             # or use any editor
```

Edit `.env`:
```ini
# Database connection string
DATABASE_URL=postgresql://medical_user:medical_pass_2025@localhost:5432/medical_db

# OpenAI API key (only needed if LLM_BACKEND=openai)
OPENAI_API_KEY=sk-your-key-here

# JWT secret (change this in production!)
SECRET_KEY=change-this-to-a-long-random-string-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

# LLM backend: 'ollama' (local) or 'openai' (cloud)
LLM_BACKEND=ollama
OLLAMA_MODEL=medgemma1.5:latest
```

---

## 7.3 Database Setup

### Create the PostgreSQL database and user

```bash
sudo -u postgres psql
```

```sql
CREATE USER medical_user WITH PASSWORD 'medical_pass_2025';
CREATE DATABASE medical_db OWNER medical_user;
GRANT ALL PRIVILEGES ON DATABASE medical_db TO medical_user;
\q
```

### Auto-create tables (first run)

Tables are created automatically when the backend starts via:
```python
Base.metadata.create_all(bind=engine)
```

You can also create them manually by running:
```bash
python -c "from backend.database import engine, Base; from backend import models; Base.metadata.create_all(engine)"
```

---

## 7.4 Seed Data (Development)

Create one doctor account + 10 sample patients with full medical data:

```bash
cd "/media/omar/Graduation Project/GP/Project"
python -m backend.seed
```

**Test credentials:**
- Email: `doctor@hospital.com`
- Password: `doctor123`

---

## 7.5 Import Synthea Data (Production/Demo)

> ⚠️ The Synthea CSV files are large (claims.csv is ~128MB). Make sure you have enough disk space and RAM (8GB+ recommended).

```bash
cd "/media/omar/Graduation Project/GP/Project"
python backend/load_synthea_csv.py
```

This imports:
- `patients_localized.csv` → `patients` table
- `conditions.csv` → `diagnoses` table
- `medications.csv` → `medications` table
- `observations.csv` → `lab_results` table (numeric observations only)
- `allergies.csv` → `allergies` table

**Fix blood types (run after import):**
```bash
python -m backend.fix_blood_types
```

---

## 7.6 Running the Backend

```bash
```bash
cd "/media/omar/Graduation Project/GP/Project"
conda activate medical_chatbot
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

- `--reload` enables hot-reload during development (remove in production)
- `--host 0.0.0.0` allows access from other machines on the network

**Verify it's running:**
```bash
curl http://localhost:8000/
# Expected: {"message":"Medical Chatbot API is running","docs":"/docs"}
```

---

## 7.7 Running the Frontend (React + Vite)

The frontend is built as a React single page application, requiring **Node.js (v18+)** and **npm**.

### Step 1 — Install Node.js inside the Conda Environment
To keep your system clean, install Node.js and npm directly into your active Conda environment:
```bash
conda activate medical_chatbot
conda install -c conda-forge nodejs -y
```

### Step 2 — Configure the Frontend Environment variables
Create a `.env` file inside the `frontend-react` folder:
```bash
cd "/media/omar/Graduation Project/GP/Project/frontend-react"
cp .env.example .env
```
Ensure the configuration parameters are set correctly:
*   `VITE_API_URL`: Backend REST endpoint (`http://localhost:8000`)
*   `VITE_WS_URL`: Backend WebSocket URL (`ws://localhost:8000`)
*   `VITE_DATA_MODE`: Set to `mock` for standalone testing (uses simulated pipelines), or `live` to connect to the actual FastAPI backend.

### Step 3 — Install Dependencies & Start Dev Server
```bash
# Install NPM modules
npm install

# Start Vite Development Server (usually binds to http://localhost:5173)
npm run dev
```

### Step 4 — Build & Preview Production Bundle (Optional)
To check the production optimization compile or serve optimized static assets:
```bash
# Compile and build the React bundles inside /dist
npm run build

# Preview the built production site locally
npm run preview
```

---

## 7.8 Setting Up Ollama (Local LLM)

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull the model (requires ~3.5GB)
ollama pull medgemma1.5:latest

# Start the Ollama service (runs on :11434)
ollama serve
```

Verify it's running:
```bash
curl http://localhost:11434/api/tags
```

---

## 7.9 Production Deployment (Nginx)

### Nginx configuration example:

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    # Frontend static files
    location / {
        root /path/to/project/frontend;
        try_files $uri $uri/ /index.html;
    }

    # Backend API proxy
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

### Run backend with Gunicorn for production:

```bash
pip install gunicorn
gunicorn backend.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

---

## 7.10 Environment Quick Reference

| Variable | Required | Default | Example |
|----------|----------|---------|---------|
| `DATABASE_URL` | ✅ | — | `postgresql://user:pass@localhost/db` |
| `SECRET_KEY` | ✅ | — | Random 64-char string |
| `ALGORITHM` | ❌ | `HS256` | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | ❌ | `60` | `120` |
| `LLM_BACKEND` | ❌ | `openai` | `ollama` or `openai` |
| `OLLAMA_MODEL` | ❌ | `llama3.2` | `llama3.2`, `mistral` |
| `OPENAI_API_KEY` | If openai | — | `sk-...` |

---

## 7.11 Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| `psycopg2.OperationalError` | PostgreSQL not running | `sudo service postgresql start` |
| `500 Internal Server Error` on Login | `passlib` bcrypt limit bug | Run `pip install bcrypt==4.0.1` |
| `401 Unauthorized` on all requests | JWT expired or missing | Re-login in the browser |
| WebSocket refuses connection | Backend not running | Check `uvicorn` process |
| LLM timeout | Ollama model not loaded | Run `ollama pull medgemma1.5:latest` |
| `ImportError` | Conda env not activated | `conda activate medical_chatbot` |
| Blank patient list | DB empty | Run `python -m backend.seed` |

---

*Next: [Benchmarks & Evaluation →](08_benchmarks_and_evaluation.md)*
