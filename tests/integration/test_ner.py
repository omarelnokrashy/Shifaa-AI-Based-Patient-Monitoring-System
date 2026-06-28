"""
Named Entity Recognition (NER) Accuracy Tests
===============================================
Tests the ner.py service with 50 annotated medical queries.
Measures precision, recall, and F1 per entity type.

Requirements:
    pip install pytest

Usage:
    python -m pytest docs/tests/test_ner.py -v
    python docs/tests/test_ner.py   # standalone with report
"""

import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

# ─── NER Test Dataset ─────────────────────────────────────────────────────────
# Format: (query, expected_entities_dict)
# Use None when entity should NOT be extracted.
# Use a function (lambda) for flexible matching (case-insensitive substring).

NER_TEST_CASES = [
    # ── date_range extraction ─────────────────────────────────────────────
    ("HbA1c from last 3 months",
     {"date_range": "3 months", "lab_test": "hba1c", "drug": None, "condition": None}),

    ("Blood glucose last 6 months",
     {"date_range": "6 months", "lab_test": "blood glucose", "drug": None}),

    ("Visits from last year",
     {"date_range": "year", "limit": None}),

    ("Lab results from last week",
     {"date_range": "week"}),

    ("Results from 2024",
     {"date_range": "2024"}),

    ("Recent labs",
     {"date_range": None}),

    # ── drug extraction ───────────────────────────────────────────────────
    ("Is the patient on metformin?",
     {"drug": "metformin", "condition": None}),

    ("Is she taking amlodipine?",
     {"drug": "amlodipine"}),

    ("Was aspirin prescribed?",
     {"drug": "aspirin"}),

    ("Current lisinopril dose?",
     {"drug": "lisinopril"}),

    ("Any problems with levothyroxine?",
     {"drug": "levothyroxine"}),

    ("Atorvastatin history",
     {"drug": "atorvastatin"}),

    # ── lab_test extraction ───────────────────────────────────────────────
    ("What was the last HbA1c?",
     {"lab_test": "hba1c", "drug": None}),

    ("Creatinine levels this year",
     {"lab_test": "creatinine"}),

    ("TSH result last month",
     {"lab_test": "tsh", "date_range": "month"}),

    ("Hemoglobin reading?",
     {"lab_test": "hemoglobin"}),

    ("Fasting blood glucose?",
     {"lab_test": "glucose"}),

    ("Latest CBC",
     {"lab_test": "cbc"}),

    # ── condition extraction ──────────────────────────────────────────────
    ("Does she have diabetes?",
     {"condition": "diabetes", "drug": None}),

    ("Hypertension diagnosis?",
     {"condition": "hypertension"}),

    ("History of asthma",
     {"condition": "asthma"}),

    ("Kidney disease status",
     {"condition": "kidney"}),

    ("Any hypothyroidism?",
     {"condition": "hypothyroid"}),

    ("Cardiac conditions?",
     {"condition": "cardiac"}),

    # ── limit extraction ──────────────────────────────────────────────────
    ("Last 3 visits",
     {"limit": 3, "date_range": None}),

    ("Show last 5 lab results",
     {"limit": 5}),

    ("Last 10 medications",
     {"limit": 10}),

    ("Last 2 hospital admissions",
     {"limit": 2}),

    ("First visit",
     {"limit": 1}),

    # ── combined entity extraction ────────────────────────────────────────
    ("HbA1c results in last 3 months",
     {"lab_test": "hba1c", "date_range": "3 months"}),

    ("Metformin since last year",
     {"drug": "metformin", "date_range": "year"}),

    ("Diabetes labs from last 6 months",
     {"condition": "diabetes", "date_range": "6 months"}),

    ("Last 5 HbA1c readings",
     {"limit": 5, "lab_test": "hba1c"}),

    ("Last 3 visits for diabetes",
     {"limit": 3, "condition": "diabetes"}),

    # ── null cases (entity not present) ──────────────────────────────────
    ("What is the patient's blood type?",
     {"drug": None, "lab_test": None, "condition": None, "limit": None}),

    ("Give me a summary",
     {"drug": None, "lab_test": None, "condition": None, "date_range": None}),

    ("Any allergies?",
     {"drug": None, "lab_test": None, "condition": None}),

    ("Medical history overview",
     {"drug": None, "lab_test": None}),

    # ── edge cases ────────────────────────────────────────────────────────
    ("Is she on metformin or amlodipine?",
     {"drug": "metformin"}),  # at minimum first drug captured

    ("HbA1c and creatinine from last month",
     {"date_range": "month"}),  # at minimum date captured

    ("Last 3 HbA1c from past year",
     {"limit": 3, "lab_test": "hba1c", "date_range": "year"}),

    ("TSH levels — is it normal?",
     {"lab_test": "tsh"}),

    ("Metformin 500mg dose history",
     {"drug": "metformin"}),

    ("Chronic kidney disease grade?",
     {"condition": "kidney"}),

    ("Any penicillin allergy?",
     {"drug": "penicillin"}),

    ("BP readings last 2 weeks",
     {"date_range": "2 weeks"}),

    ("COPD exacerbations",
     {"condition": "copd"}),

    ("Lipid panel results",
     {"lab_test": "lipid"}),

    ("Is she taking steroids?",
     {"drug": "steroid"}),
]


# ─── Evaluation Logic ─────────────────────────────────────────────────────────

def _entity_matches(extracted, expected):
    """Case-insensitive substring match for entity values."""
    if expected is None:
        return extracted is None or extracted == ''
    if extracted is None or extracted == '':
        return False
    return expected.lower() in str(extracted).lower()


def run_ner_evaluation():
    """Run full NER evaluation and print detailed report."""
    try:
        from backend.services.ner import extract_entities
    except ImportError as e:
        print(f"ERROR: Could not import NER service: {e}")
        return None

    entity_types = ['date_range', 'condition', 'drug', 'lab_test', 'limit']

    # Track TP, FP, FN per entity type
    stats = {et: {'tp': 0, 'fp': 0, 'fn': 0} for et in entity_types}
    total = 0
    errors = []

    print(f"\n{'='*60}")
    print("NER EVALUATION")
    print(f"Test cases: {len(NER_TEST_CASES)}")
    print(f"{'='*60}")

    for query, expected_dict in NER_TEST_CASES:
        result = extract_entities(query)
        total += 1
        row_correct = True

        for entity_type, expected_val in expected_dict.items():
            if entity_type not in entity_types:
                continue
            extracted_val = result.get(entity_type)

            if _entity_matches(extracted_val, expected_val):
                if expected_val is not None:
                    stats[entity_type]['tp'] += 1
            else:
                row_correct = False
                if expected_val is not None:
                    stats[entity_type]['fn'] += 1  # should have found it
                    errors.append({
                        'query': query,
                        'entity': entity_type,
                        'expected': expected_val,
                        'got': extracted_val
                    })
                else:
                    stats[entity_type]['fp'] += 1  # extracted something that shouldn't be there

        status = "✅" if row_correct else "❌"
        print(f"{status} {query[:60]:<60}")
        if not row_correct:
            for k, v in result.items():
                if v:
                    print(f"     extracted: {k}={v}")

    print(f"\n{'='*60}")
    print("PER-ENTITY METRICS")
    print(f"{'Entity':<15} {'Precision':>12} {'Recall':>10} {'F1':>8}")
    print("-" * 50)

    f1_scores = []
    for et in entity_types:
        tp = stats[et]['tp']
        fp = stats[et]['fp']
        fn = stats[et]['fn']
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        f1_scores.append(f1)
        print(f"{et:<15} {precision:>12.1%} {recall:>10.1%} {f1:>8.3f}")

    macro_f1 = sum(f1_scores) / len(f1_scores)
    print(f"\nMACRO AVERAGE F1: {macro_f1:.3f}")

    if errors:
        print(f"\n❌ MISSED ENTITIES ({len(errors)}):")
        for e in errors[:10]:  # show first 10
            print(f"  [{e['entity']}] '{e['query'][:55]}'")
            print(f"     Expected: {e['expected']} | Got: {e['got']}")

    return stats, macro_f1


# ─── Pytest Tests ─────────────────────────────────────────────────────────────

def test_drug_extraction():
    """Drug names should be extracted from queries."""
    try:
        from backend.services.ner import extract_entities
    except ImportError:
        import pytest
        pytest.skip("Backend not importable")

    drug_cases = [
        ("Is the patient on metformin?", "metformin"),
        ("Current lisinopril dose?", "lisinopril"),
        ("Was aspirin prescribed?", "aspirin"),
    ]
    for query, expected_drug in drug_cases:
        result = extract_entities(query)
        extracted = result.get('drug') or ''
        assert expected_drug.lower() in extracted.lower(), \
            f"Failed to extract drug '{expected_drug}' from: '{query}'\nGot: {result}"


def test_lab_test_extraction():
    """Lab test names should be extracted from queries."""
    try:
        from backend.services.ner import extract_entities
    except ImportError:
        import pytest
        pytest.skip("Backend not importable")

    lab_cases = [
        ("What was the last HbA1c?", "hba1c"),
        ("Creatinine levels this year", "creatinine"),
        ("TSH result last month", "tsh"),
    ]
    for query, expected_test in lab_cases:
        result = extract_entities(query)
        extracted = (result.get('lab_test') or '').lower()
        assert expected_test.lower() in extracted, \
            f"Failed to extract lab test '{expected_test}' from: '{query}'\nGot: {result}"


def test_date_range_extraction():
    """Date ranges should be extracted from temporal queries."""
    try:
        from backend.services.ner import extract_entities
    except ImportError:
        import pytest
        pytest.skip("Backend not importable")

    date_cases = [
        ("HbA1c from last 3 months", "month"),
        ("Blood glucose last 6 months", "month"),
        ("Lab results from last week", "week"),
    ]
    for query, expected_keyword in date_cases:
        result = extract_entities(query)
        extracted = (result.get('date_range') or '').lower()
        assert expected_keyword.lower() in extracted, \
            f"Failed to extract date_range from: '{query}'\nGot: {result}"


def test_limit_extraction():
    """Numeric limits should be extracted from queries."""
    try:
        from backend.services.ner import extract_entities
    except ImportError:
        import pytest
        pytest.skip("Backend not importable")

    limit_cases = [
        ("Last 3 visits", 3),
        ("Show last 5 lab results", 5),
        ("Last 10 medications", 10),
    ]
    for query, expected_limit in limit_cases:
        result = extract_entities(query)
        extracted = result.get('limit')
        assert extracted == expected_limit, \
            f"Wrong limit for '{query}': expected {expected_limit}, got {extracted}"


def test_null_entities_not_hallucinated():
    """When no entity is present, extracted value should be None or empty."""
    try:
        from backend.services.ner import extract_entities
    except ImportError:
        import pytest
        pytest.skip("Backend not importable")

    null_cases = [
        "Give me a summary",
        "What is the patient's blood type?",
        "Medical history overview",
    ]
    for query in null_cases:
        result = extract_entities(query)
        # None or empty string acceptable for all entities
        for entity_type in ['drug', 'lab_test', 'condition']:
            val = result.get(entity_type)
            assert val is None or val == '', \
                f"Entity '{entity_type}' hallucinated for '{query}': got '{val}'"


def test_entity_output_has_required_keys():
    """NER output should always contain all 5 required keys."""
    try:
        from backend.services.ner import extract_entities
    except ImportError:
        import pytest
        pytest.skip("Backend not importable")

    result = extract_entities("Test query")
    required_keys = {'date_range', 'condition', 'drug', 'lab_test', 'limit'}
    assert required_keys.issubset(result.keys()), \
        f"Missing keys in NER output: {required_keys - result.keys()}"


def test_condition_extraction():
    """Medical conditions should be extracted correctly."""
    try:
        from backend.services.ner import extract_entities
    except ImportError:
        import pytest
        pytest.skip("Backend not importable")

    condition_cases = [
        ("Does she have diabetes?", "diabetes"),
        ("Hypertension diagnosis?", "hypertension"),
        ("History of asthma", "asthma"),
    ]
    for query, expected_condition in condition_cases:
        result = extract_entities(query)
        extracted = (result.get('condition') or '').lower()
        assert expected_condition.lower() in extracted, \
            f"Failed to extract condition '{expected_condition}' from: '{query}'\nGot: {result}"


if __name__ == '__main__':
    run_ner_evaluation()
