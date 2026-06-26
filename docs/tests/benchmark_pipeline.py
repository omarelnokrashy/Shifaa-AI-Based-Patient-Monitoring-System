"""
Full Pipeline Benchmark Script
================================
Measures end-to-end pipeline latency, intent accuracy, and NER accuracy.
Generates a JSON report with all results.

Requirements:
    pip install httpx scikit-learn (optional)

Usage:
    python docs/tests/benchmark_pipeline.py
    python docs/tests/benchmark_pipeline.py --output results.json
    python docs/tests/benchmark_pipeline.py --skip-llm   # skip LLM calls (offline mode)
"""

import sys
import os
import json
import time
import argparse
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
DOCTOR_EMAIL = os.getenv("DOCTOR_EMAIL", "doctor@hospital.com")
DOCTOR_PASSWORD = os.getenv("DOCTOR_PASSWORD", "doctor123")


# ─── Benchmark Queries ────────────────────────────────────────────────────────

BENCHMARK_QUERIES = [
    # (query, expected_intent, patient_id_placeholder)
    ("What medications is this patient taking?", "medication_check"),
    ("Show me the last HbA1c result", "lab_results"),
    ("Any drug allergies?", "allergy_check"),
    ("Last 3 visits summary", "visit_summary"),
    ("What conditions does this patient have?", "diagnosis_check"),
    ("Give me a brief medical history", "history_lookup"),
    ("Are there any concerning findings?", "risk_flag"),
    ("What is the normal range for HbA1c?", "general_question"),
    ("Is the patient on metformin?", "medication_check"),
    ("Lab results from last 6 months", "lab_results"),
]


def print_section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def benchmark_intent_classification(skip_llm=False):
    """Benchmark intent classification speed and accuracy."""
    print_section("1. INTENT CLASSIFICATION BENCHMARK")

    if skip_llm:
        print("  [SKIPPED] --skip-llm flag set")
        return None

    try:
        from backend.services.intent import classify_intent
    except ImportError as e:
        print(f"  [ERROR] Cannot import intent service: {e}")
        return None

    from test_intent import INTENT_TEST_CASES

    results = {
        'correct': 0,
        'total': len(INTENT_TEST_CASES),
        'latencies_ms': [],
        'errors': []
    }

    print(f"  Testing {len(INTENT_TEST_CASES)} queries...")

    for query, expected in INTENT_TEST_CASES:
        t0 = time.perf_counter()
        result = classify_intent(query)
        latency_ms = (time.perf_counter() - t0) * 1000

        predicted = result.get('intent', 'history_lookup')
        results['latencies_ms'].append(latency_ms)

        if predicted == expected:
            results['correct'] += 1
        else:
            results['errors'].append({
                'query': query,
                'expected': expected,
                'predicted': predicted
            })

    results['accuracy'] = results['correct'] / results['total']
    results['latency_median_ms'] = sorted(results['latencies_ms'])[len(results['latencies_ms'])//2]
    results['latency_p95_ms'] = sorted(results['latencies_ms'])[int(len(results['latencies_ms'])*0.95)]
    results['latency_mean_ms'] = sum(results['latencies_ms']) / len(results['latencies_ms'])

    print(f"  ✅ Accuracy:         {results['accuracy']:.1%} ({results['correct']}/{results['total']})")
    print(f"  ⏱  Median latency:  {results['latency_median_ms']:.0f}ms")
    print(f"  ⏱  P95 latency:     {results['latency_p95_ms']:.0f}ms")
    print(f"  ⏱  Mean latency:    {results['latency_mean_ms']:.0f}ms")

    return results


def benchmark_ner(skip_llm=False):
    """Benchmark NER extraction speed and accuracy."""
    print_section("2. NER EXTRACTION BENCHMARK")

    if skip_llm:
        print("  [SKIPPED] --skip-llm flag set")
        return None

    try:
        from backend.services.ner import extract_entities
    except ImportError as e:
        print(f"  [ERROR] Cannot import NER service: {e}")
        return None

    from test_ner import NER_TEST_CASES, _entity_matches

    latencies_ms = []
    entity_matches = {'correct': 0, 'total': 0}

    print(f"  Testing {len(NER_TEST_CASES)} queries...")

    for query, expected_dict in NER_TEST_CASES:
        t0 = time.perf_counter()
        result = extract_entities(query)
        latency_ms = (time.perf_counter() - t0) * 1000
        latencies_ms.append(latency_ms)

        for entity_type, expected_val in expected_dict.items():
            if entity_type not in ['date_range', 'condition', 'drug', 'lab_test', 'limit']:
                continue
            entity_matches['total'] += 1
            extracted = result.get(entity_type)
            if _entity_matches(extracted, expected_val):
                entity_matches['correct'] += 1

    accuracy = entity_matches['correct'] / entity_matches['total'] if entity_matches['total'] > 0 else 0
    latencies_ms_sorted = sorted(latencies_ms)

    results = {
        'entity_accuracy': accuracy,
        'correct': entity_matches['correct'],
        'total': entity_matches['total'],
        'latency_median_ms': latencies_ms_sorted[len(latencies_ms_sorted)//2],
        'latency_p95_ms': latencies_ms_sorted[int(len(latencies_ms_sorted)*0.95)],
        'latency_mean_ms': sum(latencies_ms) / len(latencies_ms),
    }

    print(f"  ✅ Entity Accuracy:  {accuracy:.1%} ({entity_matches['correct']}/{entity_matches['total']})")
    print(f"  ⏱  Median latency:  {results['latency_median_ms']:.0f}ms")
    print(f"  ⏱  P95 latency:     {results['latency_p95_ms']:.0f}ms")
    print(f"  ⏱  Mean latency:    {results['latency_mean_ms']:.0f}ms")

    return results


def benchmark_retriever():
    """Benchmark retriever performance using in-memory SQLite."""
    print_section("3. RETRIEVER BENCHMARK")

    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from backend.database import Base
        from backend import models
        from backend.services.retriever import retrieve
    except ImportError as e:
        print(f"  [ERROR] Cannot import retriever: {e}")
        return None

    from datetime import date, timedelta

    # Set up in-memory test DB
    engine = create_engine('sqlite:///:memory:', connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    today = date.today()

    # Create test patient
    p = models.Patient(id=1, name="Bench Patient", dob=date(1975, 1, 1), gender="Male")
    session.add(p)
    for i in range(20):
        session.add(models.Medication(patient_id=1, drug_name=f"Drug{i}", dose="10mg",
                                       start_date=today - timedelta(days=i*30), is_active=True))
        session.add(models.LabResult(patient_id=1, test_name="HbA1c", value=7.0+i*0.1,
                                      unit="%", reference="4.0-5.6",
                                      test_date=today - timedelta(days=i*15), is_abnormal=i%3==0))
    session.commit()

    # Benchmark each intent
    intents_to_test = [
        ('medication_check', {}),
        ('lab_results', {}),
        ('lab_results', {'lab_test': 'HbA1c', 'limit': 5}),
        ('history_lookup', {}),
        ('risk_flag', {}),
        ('allergy_check', {}),
        ('visit_summary', {'limit': 5}),
        ('diagnosis_check', {}),
    ]

    results = {}
    for intent, entities in intents_to_test:
        latencies = []
        for _ in range(10):  # 10 repetitions per intent
            t0 = time.perf_counter()
            retrieve(1, intent, entities, session)
            latencies.append((time.perf_counter() - t0) * 1000)

        median = sorted(latencies)[5]
        results[intent] = {'median_ms': median, 'runs': len(latencies)}
        print(f"  {intent:<20} → median: {median:.2f}ms")

    session.close()
    return results


def benchmark_api_endpoints(skip_llm=False):
    """Benchmark REST API latency for key endpoints."""
    print_section("4. REST API LATENCY BENCHMARK")

    try:
        import httpx
    except ImportError:
        print("  [SKIPPED] httpx not installed: pip install httpx")
        return None

    client = httpx.Client(base_url=BASE_URL, timeout=120.0)

    # Try to login
    try:
        resp = client.post("/api/auth/login", json={
            "email": DOCTOR_EMAIL, "password": DOCTOR_PASSWORD
        })
        if resp.status_code != 200:
            print(f"  [SKIPPED] Cannot authenticate — is backend running at {BASE_URL}?")
            return None
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
    except Exception as e:
        print(f"  [SKIPPED] Backend not available: {e}")
        return None

    # Get first patient
    patients = client.get("/api/patients", headers=headers).json()
    if not patients:
        print("  [SKIPPED] No patients in database")
        return None
    patient_id = patients[0]["id"]

    results = {}

    # Benchmark: list patients
    latencies = []
    for _ in range(5):
        t0 = time.perf_counter()
        client.get("/api/patients", headers=headers)
        latencies.append((time.perf_counter() - t0) * 1000)
    results['GET /api/patients'] = {
        'median_ms': sorted(latencies)[2],
        'mean_ms': sum(latencies)/len(latencies)
    }
    print(f"  GET /api/patients              → {results['GET /api/patients']['median_ms']:.1f}ms")

    # Benchmark: get full patient
    latencies = []
    for _ in range(5):
        t0 = time.perf_counter()
        client.get(f"/api/patients/{patient_id}", headers=headers)
        latencies.append((time.perf_counter() - t0) * 1000)
    results[f'GET /api/patients/{"{id}"}'] = {
        'median_ms': sorted(latencies)[2],
        'mean_ms': sum(latencies)/len(latencies)
    }
    print(f"  GET /api/patients/{{id}}          → {results['GET /api/patients/{\"id\"}']\['median_ms']:.1f}ms")

    if not skip_llm:
        # Benchmark: chat (LLM call - measured just once due to cost)
        print("  POST /api/chat (single run, LLM included)...")
        t0 = time.perf_counter()
        resp = client.post("/api/chat", headers=headers, json={
            "query": "What medications is this patient taking?",
            "patient_id": patient_id
        }, timeout=120.0)
        total_ms = (time.perf_counter() - t0) * 1000
        results['POST /api/chat'] = {
            'total_ms': total_ms,
            'status': resp.status_code
        }
        print(f"  POST /api/chat                 → {total_ms:.0f}ms (status: {resp.status_code})")

    client.close()
    return results


def generate_report(intent_results, ner_results, retriever_results, api_results, output_file):
    """Generate a JSON + text summary report."""
    report = {
        'generated_at': datetime.now().isoformat(),
        'system_info': {
            'python_version': sys.version,
            'base_url': BASE_URL,
        },
        'intent_classification': intent_results,
        'ner_extraction': ner_results,
        'retriever_performance': retriever_results,
        'api_latency': api_results,
        'summary': {}
    }

    # Summary
    if intent_results:
        report['summary']['intent_accuracy'] = f"{intent_results['accuracy']:.1%}"
    if ner_results:
        report['summary']['ner_entity_accuracy'] = f"{ner_results['entity_accuracy']:.1%}"
    if retriever_results:
        meds_median = retriever_results.get('medication_check', {}).get('median_ms', 'N/A')
        report['summary']['retriever_medication_check_ms'] = meds_median

    print_section("SUMMARY REPORT")
    print(json.dumps(report['summary'], indent=2))

    if output_file:
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\n  Full report saved to: {output_file}")

    return report


def main():
    parser = argparse.ArgumentParser(description="Medical Chatbot Pipeline Benchmark")
    parser.add_argument('--output', '-o', default='benchmark_results.json',
                        help='Output JSON file for results (default: benchmark_results.json)')
    parser.add_argument('--skip-llm', action='store_true',
                        help='Skip LLM-dependent tests (intent, NER, chat)')
    args = parser.parse_args()

    print(f"\n{'#'*60}")
    print("  MEDICAL CHATBOT — FULL PIPELINE BENCHMARK")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*60}")

    intent_results = benchmark_intent_classification(skip_llm=args.skip_llm)
    ner_results = benchmark_ner(skip_llm=args.skip_llm)
    retriever_results = benchmark_retriever()
    api_results = benchmark_api_endpoints(skip_llm=args.skip_llm)

    report = generate_report(
        intent_results, ner_results, retriever_results, api_results,
        output_file=args.output
    )

    print(f"\n{'#'*60}")
    print("  BENCHMARK COMPLETE")
    print(f"{'#'*60}\n")

    return report


if __name__ == '__main__':
    main()
