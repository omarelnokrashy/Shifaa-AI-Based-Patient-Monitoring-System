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
python3 -m venv venv
source venv/bin/activate        # Linux/macOS
# venv\Scripts\activate.bat     # Windows
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
OLLAMA_MODEL=llama3.2
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
cd "/media/omar/Graduation Project/GP/Project"
source venv/bin/activate
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

## 7.7 Running the Frontend

The frontend is a static HTML file. Three options:

**Option A — Open directly in browser:**
```bash
xdg-open "/media/omar/Graduation Project/GP/Project/frontend/index.html"
```

**Option B — Serve with Python's HTTP server:**
```bash
cd "/media/omar/Graduation Project/GP/Project/frontend"
python -m http.server 3000
# Open: http://localhost:3000
```

**Option C — Use Nginx or any static file server**

---

## 7.8 Setting Up Ollama (Local LLM)

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull the model (one-time download ~2GB)
ollama pull llama3.2

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
| `401 Unauthorized` on all requests | JWT expired or missing | Re-login in the browser |
| WebSocket refuses connection | Backend not running | Check `uvicorn` process |
| LLM timeout | Ollama model not loaded | Run `ollama pull llama3.2` |
| `ImportError` | Virtual env not activated | `source venv/bin/activate` |
| Blank patient list | DB empty | Run `python -m backend.seed` |

---

*Next: [Benchmarks & Evaluation →](08_benchmarks_and_evaluation.md)*
