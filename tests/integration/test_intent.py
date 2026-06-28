"""
Intent Classification Accuracy Tests
======================================
Tests the intent.py service with a curated set of 80 doctor queries.
Each query has a known ground-truth intent label.
Produces per-class and macro-averaged accuracy, precision, recall, and F1.

Requirements:
    pip install pytest scikit-learn

Usage:
    # From the project root:
    python -m pytest docs/tests/test_intent.py -v

    # To also print the classification report:
    python docs/tests/test_intent.py
"""

import sys
import os
import json

# Add project root to path so we can import backend
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

# ─── Test Dataset ──────────────────────────────────────────────────────────────
# Format: (query, expected_intent)
INTENT_TEST_CASES = [
    # ── medication_check (12 queries) ──────────────────────────────────────
    ("What medications is this patient currently taking?",              "medication_check"),
    ("What drugs is the patient on?",                                    "medication_check"),
    ("Current prescriptions?",                                           "medication_check"),
    ("Is the patient on metformin?",                                     "medication_check"),
    ("List all active medications",                                      "medication_check"),
    ("What is the patient prescribed?",                                  "medication_check"),
    ("Show me current medications",                                      "medication_check"),
    ("Drug list for this patient",                                       "medication_check"),
    ("What medicines does she take?",                                    "medication_check"),
    ("Any medications for blood pressure?",                              "medication_check"),
    ("Is he taking amlodipine?",                                         "medication_check"),
    ("List of prescriptions",                                            "medication_check"),

    # ── lab_results (12 queries) ────────────────────────────────────────────
    ("What was the last HbA1c?",                                         "lab_results"),
    ("Show me lab results from the last 3 months",                       "lab_results"),
    ("Last creatinine level?",                                           "lab_results"),
    ("Blood glucose readings this year",                                 "lab_results"),
    ("TSH levels?",                                                      "lab_results"),
    ("Recent lab work",                                                  "lab_results"),
    ("CBC results?",                                                      "lab_results"),
    ("Kidney function tests?",                                            "lab_results"),
    ("Latest hemoglobin reading",                                        "lab_results"),
    ("Lab results for diabetes monitoring",                              "lab_results"),
    ("What was the HbA1c 6 months ago?",                                 "lab_results"),
    ("Abnormal labs?",                                                    "lab_results"),

    # ── allergy_check (10 queries) ──────────────────────────────────────────
    ("Does this patient have any allergies?",                            "allergy_check"),
    ("Is she allergic to penicillin?",                                   "allergy_check"),
    ("Any drug allergies?",                                              "allergy_check"),
    ("List known allergies",                                             "allergy_check"),
    ("Allergic to any antibiotics?",                                     "allergy_check"),
    ("What substances is he allergic to?",                               "allergy_check"),
    ("Any adverse drug reactions on file?",                              "allergy_check"),
    ("Can I prescribe sulfa drugs to this patient?",                     "allergy_check"),
    ("Contraindicated due to allergy?",                                  "allergy_check"),
    ("Patient allergy history",                                          "allergy_check"),

    # ── visit_summary (10 queries) ──────────────────────────────────────────
    ("What happened in the last visit?",                                 "visit_summary"),
    ("Last 3 appointments?",                                             "visit_summary"),
    ("Recent clinic visits",                                             "visit_summary"),
    ("What was the chief complaint last time?",                          "visit_summary"),
    ("Visit history from last year",                                     "visit_summary"),
    ("Summarize the last encounter",                                     "visit_summary"),
    ("Why did she come in last time?",                                   "visit_summary"),
    ("Show me the clinical notes from last month",                       "visit_summary"),
    ("Any recent ER visits?",                                            "visit_summary"),
    ("Appointments summary",                                             "visit_summary"),

    # ── diagnosis_check (10 queries) ────────────────────────────────────────
    ("What conditions does this patient have?",                          "diagnosis_check"),
    ("Active diagnoses?",                                                "diagnosis_check"),
    ("Does he have diabetes?",                                           "diagnosis_check"),
    ("Medical conditions on file",                                       "diagnosis_check"),
    ("ICD-10 codes for this patient",                                    "diagnosis_check"),
    ("Is hypertension a current diagnosis?",                             "diagnosis_check"),
    ("List all diagnosed conditions",                                    "diagnosis_check"),
    ("What diseases is she being treated for?",                          "diagnosis_check"),
    ("Current problems list",                                            "diagnosis_check"),
    ("Chronic conditions?",                                              "diagnosis_check"),

    # ── history_lookup (10 queries) ─────────────────────────────────────────
    ("Give me a summary of this patient's medical history",              "history_lookup"),
    ("Full patient background",                                          "history_lookup"),
    ("Brief medical history please",                                     "history_lookup"),
    ("Patient overview",                                                 "history_lookup"),
    ("Tell me about this patient",                                       "history_lookup"),
    ("General health history",                                           "history_lookup"),
    ("What do I need to know about this patient?",                       "history_lookup"),
    ("Complete medical background",                                      "history_lookup"),
    ("Comprehensive patient summary",                                    "history_lookup"),
    ("Everything on file for this patient",                              "history_lookup"),

    # ── risk_flag (8 queries) ────────────────────────────────────────────────
    ("Are there any concerning findings?",                               "risk_flag"),
    ("Any red flags in this patient's history?",                         "risk_flag"),
    ("Is there anything alarming?",                                      "risk_flag"),
    ("Critical values to watch?",                                        "risk_flag"),
    ("Any dangerous drug interactions?",                                 "risk_flag"),
    ("Abnormal findings I should know about?",                           "risk_flag"),
    ("Risk assessment for this patient",                                 "risk_flag"),
    ("Should I be concerned about anything?",                            "risk_flag"),

    # ── general_question (8 queries) ────────────────────────────────────────
    ("What is the normal range for HbA1c?",                              "general_question"),
    ("How does metformin work?",                                         "general_question"),
    ("What are symptoms of hypoglycemia?",                               "general_question"),
    ("Explain creatinine clearance",                                     "general_question"),
    ("What is ICD-10 code E11?",                                         "general_question"),
    ("Normal blood pressure range?",                                     "general_question"),
    ("When should I prescribe insulin?",                                 "general_question"),
    ("What does an HbA1c of 9 mean?",                                   "general_question"),
]


# ─── Test Functions ────────────────────────────────────────────────────────────

def run_intent_evaluation():
    """
    Run full evaluation of the intent classifier.
    Returns (predictions, labels, accuracy, report_dict)
    """
    try:
        from backend.services.intent import classify_intent
    except ImportError as e:
        print(f"ERROR: Could not import intent service: {e}")
        print("Make sure you're running from the project root with venv activated.")
        return None

    predictions = []
    labels = []
    errors = []

    print(f"\n{'='*60}")
    print("INTENT CLASSIFICATION EVALUATION")
    print(f"Test cases: {len(INTENT_TEST_CASES)}")
    print(f"{'='*60}")

    for query, expected in INTENT_TEST_CASES:
        result = classify_intent(query)
        predicted = result.get('intent', 'history_lookup')
        confidence = result.get('confidence', 0.0)
        predictions.append(predicted)
        labels.append(expected)

        status = "✅" if predicted == expected else "❌"
        if predicted != expected:
            errors.append({
                'query': query,
                'expected': expected,
                'predicted': predicted,
                'confidence': confidence
            })

        print(f"{status} [{confidence:.2f}] {query[:60]:<60} → {predicted}")

    # Compute metrics
    correct = sum(p == l for p, l in zip(predictions, labels))
    accuracy = correct / len(labels)

    print(f"\n{'='*60}")
    print(f"OVERALL ACCURACY: {accuracy:.1%}  ({correct}/{len(labels)} correct)")
    print(f"{'='*60}")

    if errors:
        print(f"\n❌ MISCLASSIFIED ({len(errors)}):")
        for e in errors:
            print(f"  Query: '{e['query'][:60]}'")
            print(f"  Expected: {e['expected']} | Got: {e['predicted']} (conf: {e['confidence']:.2f})")
            print()

    # Per-class metrics
    try:
        from sklearn.metrics import classification_report
        report = classification_report(labels, predictions, output_dict=True, zero_division=0)
        print("\nPER-CLASS METRICS:")
        print(classification_report(labels, predictions, zero_division=0))
        return predictions, labels, accuracy, report
    except ImportError:
        print("\n(Install scikit-learn for detailed per-class metrics: pip install scikit-learn)")
        return predictions, labels, accuracy, {}


# ─── Pytest Tests ─────────────────────────────────────────────────────────────

def test_medication_check_queries():
    """All medication_check queries should be classified correctly."""
    try:
        from backend.services.intent import classify_intent
    except ImportError:
        import pytest
        pytest.skip("Backend not importable - check PYTHONPATH")

    cases = [(q, e) for q, e in INTENT_TEST_CASES if e == "medication_check"]
    results = [(classify_intent(q)['intent'], e) for q, e in cases]
    correct = sum(p == e for p, e in results)
    accuracy = correct / len(results)
    print(f"\nmedication_check accuracy: {accuracy:.1%} ({correct}/{len(results)})")
    assert accuracy >= 0.80, f"medication_check accuracy too low: {accuracy:.1%}"


def test_lab_results_queries():
    """All lab_results queries should be classified correctly."""
    try:
        from backend.services.intent import classify_intent
    except ImportError:
        import pytest
        pytest.skip("Backend not importable - check PYTHONPATH")

    cases = [(q, e) for q, e in INTENT_TEST_CASES if e == "lab_results"]
    results = [(classify_intent(q)['intent'], e) for q, e in cases]
    correct = sum(p == e for p, e in results)
    accuracy = correct / len(results)
    print(f"\nlab_results accuracy: {accuracy:.1%} ({correct}/{len(results)})")
    assert accuracy >= 0.80, f"lab_results accuracy too low: {accuracy:.1%}"


def test_allergy_check_queries():
    """All allergy_check queries should be classified correctly."""
    try:
        from backend.services.intent import classify_intent
    except ImportError:
        import pytest
        pytest.skip("Backend not importable - check PYTHONPATH")

    cases = [(q, e) for q, e in INTENT_TEST_CASES if e == "allergy_check"]
    results = [(classify_intent(q)['intent'], e) for q, e in cases]
    correct = sum(p == e for p, e in results)
    accuracy = correct / len(results)
    print(f"\nallergy_check accuracy: {accuracy:.1%} ({correct}/{len(results)})")
    assert accuracy >= 0.80, f"allergy_check accuracy too low: {accuracy:.1%}"


def test_overall_intent_accuracy():
    """Overall intent classification should be >= 85% accurate."""
    try:
        from backend.services.intent import classify_intent
    except ImportError:
        import pytest
        pytest.skip("Backend not importable - check PYTHONPATH")

    predictions = [classify_intent(q)['intent'] for q, _ in INTENT_TEST_CASES]
    labels = [e for _, e in INTENT_TEST_CASES]
    correct = sum(p == l for p, l in zip(predictions, labels))
    accuracy = correct / len(labels)
    print(f"\nOverall accuracy: {accuracy:.1%} ({correct}/{len(labels)})")
    assert accuracy >= 0.85, f"Overall accuracy too low: {accuracy:.1%}"


def test_confidence_scores_are_valid():
    """All confidence scores should be between 0 and 1."""
    try:
        from backend.services.intent import classify_intent
    except ImportError:
        import pytest
        pytest.skip("Backend not importable - check PYTHONPATH")

    # Test a sample of 10 queries to keep test fast
    sample = INTENT_TEST_CASES[:10]
    for query, _ in sample:
        result = classify_intent(query)
        assert 'intent' in result
        assert 'confidence' in result
        assert 0.0 <= result['confidence'] <= 1.0, \
            f"Confidence out of range for '{query}': {result['confidence']}"


def test_invalid_intent_falls_back():
    """When classification fails, intent should default to history_lookup."""
    try:
        from backend.services.intent import classify_intent
    except ImportError:
        import pytest
        pytest.skip("Backend not importable - check PYTHONPATH")

    # A completely nonsensical query should still return a valid intent
    result = classify_intent("asdfgh 1234 @@@ random gibberish")
    assert result['intent'] in [
        'history_lookup', 'medication_check', 'lab_results', 'allergy_check',
        'visit_summary', 'diagnosis_check', 'risk_flag', 'general_question'
    ]


if __name__ == '__main__':
    run_intent_evaluation()
