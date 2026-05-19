# 🏥 Medical History Chatbot

An AI-powered patient history retrieval system and multi-modal clinical assistant designed for doctors. Powered by **MedGemma 1.5**, this application features a clinical reasoning pipeline, multi-modal medical image analysis (OCR, X-rays, MRI/CT), and an intuitive UI to manage patient records and streamline diagnoses.

---

## 🚀 Quick Start Instructions

### 1. Prerequisites

- **Python 3.10+**
- **PostgreSQL** (running)
- **Ollama** (optional, for local LLM)

### 2. Environment Setup

```bash
# Clone the repository and enter the directory
cd "/media/omar/Graduation Project/GP/Project"

# Create and activate the Conda environment
conda create -n medical_chatbot python=3.10 -y
conda activate medical_chatbot

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
# Ensure your .env file has the correct DATABASE_URL and OLLAMA_MODEL (e.g., medgemma1.5:latest)
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

- `backend/`: FastAPI application, database models, and AI services (including LLM integration).
- `frontend/`: Multi-modal HTML/JS/CSS clinical chat interface featuring a Patient Hub, Image Uploads, and a Claude-style Thinking UI.
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
