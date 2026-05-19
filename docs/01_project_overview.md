# 01 — Project Overview

## 1.1 Title

**Medical History Chatbot** — An AI-Powered Clinical Decision Support System for Doctor-Facing Patient History Retrieval

---

## 1.2 Abstract

This project presents a conversational AI system designed to allow doctors to query comprehensive patient medical records using natural language. The system combines a **FastAPI** backend, a **PostgreSQL** relational database, and a multi-stage **LLM pipeline** (Intent Classification → Named Entity Recognition → Database Retrieval → Answer Generation) to produce accurate, source-cited clinical responses in real time via WebSocket streaming.

The dataset is sourced from **Synthea**, a synthetic patient data generator widely used in academic medical AI research, ensuring realistic clinical data without compromising any real patient privacy.

---

## 1.3 Motivation

Electronic Health Records (EHR) systems are notoriously difficult to navigate. A doctor may need to:
- Quickly check whether a patient is allergic to a drug before prescribing.
- Review the last 3 lab results for HbA1c trends.
- Understand all active medications before adding a new one.

Current EHR interfaces require multiple clicks across different modules. This project replaces that workflow with a **single natural-language chat interface** that understands clinical questions and retrieves the correct data automatically.

---

## 1.4 Objectives

| # | Objective |
|---|-----------|
| 1 | Provide a secure, JWT-authenticated API for doctor access |
| 2 | Classify doctor queries into one of 8 clinical intent categories |
| 3 | Extract medical entities (drugs, conditions, date ranges, lab tests) from free-text queries |
| 4 | Retrieve targeted patient records from PostgreSQL based on intent + entities |
| 5 | Generate grounded, source-cited answers using an LLM (OpenAI GPT-4o or local Ollama Llama 3.2) |
| 6 | Stream responses in real time via WebSocket for low perceived latency |
| 7 | Support both cloud (OpenAI) and fully local (Ollama) LLM backends |

---

## 1.5 Key Features

### 🔐 Authentication
- Doctor login via email+password
- JWT Bearer token with configurable expiry
- All patient data endpoints require a valid token

### 👥 Patient Management
- List all patients with live search by name
- Register new patients via modal form
- View full patient history (diagnoses, medications, labs, allergies, visits)

### 🤖 AI Chat Pipeline
- **Intent Classification** — Determines what the doctor is asking (8 intent types)
- **Named Entity Recognition** — Extracts structured entities from free-text (drugs, conditions, labs, date ranges)
- **Smart Retrieval** — Queries only the relevant database table(s) with extracted filters
- **LLM Answer Generation** — Strictly grounded answer with citations; flags abnormal labs and dangerous combinations
- **Real-time Streaming** — WebSocket delivery of tokens for instant feedback

### 📊 Dual LLM Support
| Backend | Models | Use Case |
|---------|--------|----------|
| OpenAI | `gpt-4o` (generation), `gpt-4o-mini` (classification/NER) | Cloud deployment |
| Ollama | `llama3.2` (all tasks) | Local / air-gapped deployment |

### 🏥 Dataset
- **Source**: Synthea synthetic patient generator
- **Size**: ~1,000+ patients with realistic conditions, medications, lab results, allergies, and clinical encounters
- **Tables populated**: patients, diagnoses, medications, lab_results, allergies

---

## 1.6 Technology Stack

| Layer | Technology | Version |
|-------|------------|---------|
| Backend Framework | FastAPI | 0.111.0 |
| ASGI Server | Uvicorn | 0.30.1 |
| ORM | SQLAlchemy | 2.0.30 |
| Database | PostgreSQL | 14+ |
| DB Driver | psycopg2-binary | 2.9.9 |
| Data Validation | Pydantic | 2.7.1 |
| Auth | python-jose (JWT) + passlib (bcrypt) | 3.3.0 / 1.7.4 |
| LLM Client | openai SDK (also used for Ollama) | 1.35.3 |
| Frontend | Vanilla HTML/CSS/JS + marked.js | — |
| Data Import | pandas | 2.2.2 |
| Testing | pytest + httpx | — |

---

## 1.7 Academic Contributions

1. **Hybrid intent + NER pipeline** using LLMs as structured classifiers with JSON mode output — a lightweight alternative to training custom NER models.
2. **Dual-backend architecture** enabling the same system to run on OpenAI cloud or fully locally with Ollama, addressing data privacy concerns in clinical settings.
3. **Strict grounding** — LLM is explicitly instructed not to use external knowledge, ensuring all answers are traceable to actual patient records (reducing hallucination risk).
4. **Synthea integration pipeline** mapping CSV exports to a normalized relational schema suitable for clinical querying.

---

*Next: [System Architecture →](02_system_architecture.md)*
