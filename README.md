# 🏥 Medical History Chatbot

An AI-powered patient history retrieval system designed for doctors. This clinical assistant uses a multi-stage LLM pipeline to classify intents, extract medical entities, and retrieve relevant data from patient records to generate grounded, source-cited answers.

---

## 🚀 Quick Start Instructions

### 1. Prerequisites

- **Python 3.10+**
- **PostgreSQL** (running)
- **Ollama** (optional, for local LLM)

### 2. Backend Setup

```bash
# Clone the repository and enter the directory
cd "/media/omar/Graduation Project/GP/Project"

# Activate the virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
# Ensure your .env file has the correct DATABASE_URL and LLM_BACKEND
nano .env
```

### 3. Run the Backend

```bash
# Start the FastAPI server
uvicorn backend.main:app --reload --port 8000
```

The API documentation will be available at [http://localhost:8000/docs](http://localhost:8000/docs).

### 4. Run the Frontend

The frontend is a self-contained SPA. You can open it directly or serve it:

**Option A: Open directly**
Open `frontend/index.html` in any modern web browser.

**Option B: Serve via Python**

```bash
cd frontend
python3 -m http.server 3000
```

Then visit [http://localhost:3000](http://localhost:3000).

---

## 🛠 Project Structure

- `backend/`: FastAPI application, database models, and AI services.
- `frontend/`: Vanilla HTML/JS/CSS clinical chat interface.
- `docs/`: Comprehensive documentation, system architecture, and academic benchmarks.
- `Data/`: Synthea synthetic patient dataset.

---

## 🧪 Documentation & Testing

For detailed system architecture, API reference, and benchmarking results, see the [Documentation Index](docs/README.md).

To run all tests and benchmarks:

```bash
bash docs/tests/run_all_tests.sh
```

---

## 🔑 Test Credentials

If you have seeded the database using `backend/seed.py`, use:

- **Email:** `doctor@hospital.com`
- **Password:** `doctor123`
