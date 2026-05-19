# 📚 Medical History Chatbot — Project Documentation

> **Academic Graduation Project**  
> Faculty of Computer Science & Engineering  
> Date: March 2026

---

## 📂 Documentation Index

| Document | Description |
|----------|-------------|
| [01_project_overview.md](01_project_overview.md) | Executive summary, motivation, and objectives |
| [02_system_architecture.md](02_system_architecture.md) | Full system architecture with diagrams |
| [03_api_reference.md](03_api_reference.md) | Complete REST & WebSocket API reference |
| [04_data_model.md](04_data_model.md) | Database schema and entity relationships |
| [05_ai_pipeline.md](05_ai_pipeline.md) | AI/NLP pipeline: Intent → NER → Retriever → LLM |
| [06_frontend_guide.md](06_frontend_guide.md) | Frontend structure and UI components |
| [07_setup_guide.md](07_setup_guide.md) | Installation, configuration & deployment guide |
| [08_benchmarks_and_evaluation.md](08_benchmarks_and_evaluation.md) | Academic benchmarks and evaluation results |
| [09_dataset_description.md](09_dataset_description.md) | Synthea dataset description and import process |

## 🧪 Test Suite

| File | Description |
|------|-------------|
| [tests/test_intent.py](tests/test_intent.py) | Intent classification accuracy tests |
| [tests/test_ner.py](tests/test_ner.py) | Named Entity Recognition accuracy tests |
| [tests/test_retriever.py](tests/test_retriever.py) | Data retrieval logic unit tests |
| [tests/test_api.py](tests/test_api.py) | REST API integration tests |
| [tests/benchmark_pipeline.py](tests/benchmark_pipeline.py) | Full pipeline benchmarking script |
| [tests/run_all_tests.sh](tests/run_all_tests.sh) | Shell script to run all tests and collect results |

---

## 🚀 Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set environment variables
cp .env.example .env   # then edit .env

# 3. Start the backend
cd /path/to/project
uvicorn backend.main:app --reload --port 8000

# 4. Run the test suite
cd docs/tests
python -m pytest . -v --tb=short
```

---

*Generated: 2026-03-11*
