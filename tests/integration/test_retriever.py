"""
Data Retriever Unit Tests
==========================
Tests the retriever.py service against a real (test) database.
Uses SQLite in-memory for fast, isolated testing without needing PostgreSQL.

Requirements:
    pip install pytest sqlalchemy

Usage:
    python -m pytest docs/tests/test_retriever.py -v
"""

import sys
import os
import pytest
from datetime import date, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)


# ─── Test Database Setup ──────────────────────────────────────────────────────

@pytest.fixture(scope='module')
def db_session():
    """
    Create an in-memory SQLite database with test data.
    Yields a SQLAlchemy session for each test module.
    """
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from backend.database import Base
        from backend import models
    except ImportError as e:
        pytest.skip(f"Backend not importable: {e}")

    # Use SQLite in-memory for test isolation
    engine = create_engine('sqlite:///:memory:', connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # ── Seed test data ────────────────────────────────────────────────────

    # Create a patient
    patient = models.Patient(
        id=1,
        name="Test Patient",
        dob=date(1980, 1, 1),
        gender="Male",
        blood_type="O+"
    )
    session.add(patient)

    # 3 diagnoses
    session.add(models.Diagnosis(patient_id=1, description="Type 2 Diabetes Mellitus",
                                  icd10_code="E11", diagnosed_on=date(2020, 1, 1),
                                  is_active=True, severity="moderate"))
    session.add(models.Diagnosis(patient_id=1, description="Hypertension",
                                  icd10_code="I10", diagnosed_on=date(2019, 6, 15),
                                  is_active=True, severity="mild"))
    session.add(models.Diagnosis(patient_id=1, description="Resolved Infection",
                                  icd10_code="J00", diagnosed_on=date(2018, 3, 1),
                                  is_active=False, severity="mild"))

    # 3 medications (2 active, 1 inactive)
    session.add(models.Medication(patient_id=1, drug_name="Metformin", dose="500mg twice daily",
                                   start_date=date(2020, 2, 1), is_active=True))
    session.add(models.Medication(patient_id=1, drug_name="Amlodipine", dose="5mg once daily",
                                   start_date=date(2021, 3, 1), is_active=True))
    session.add(models.Medication(patient_id=1, drug_name="OldDrug", dose="10mg",
                                   start_date=date(2015, 1, 1), end_date=date(2016, 1, 1),
                                   is_active=False))

    # 4 lab results (2 recent, 2 old)
    today = date.today()
    session.add(models.LabResult(patient_id=1, test_name="HbA1c", value=8.1, unit="%",
                                  reference="4.0-5.6", test_date=today - timedelta(days=30),
                                  is_abnormal=True))
    session.add(models.LabResult(patient_id=1, test_name="HbA1c", value=7.5, unit="%",
                                  reference="4.0-5.6", test_date=today - timedelta(days=200),
                                  is_abnormal=True))
    session.add(models.LabResult(patient_id=1, test_name="Creatinine", value=1.1, unit="mg/dL",
                                  reference="0.6-1.2", test_date=today - timedelta(days=60),
                                  is_abnormal=False))
    session.add(models.LabResult(patient_id=1, test_name="TSH", value=3.2, unit="mIU/L",
                                  reference="0.4-4.0", test_date=today - timedelta(days=90),
                                  is_abnormal=False))

    # 2 allergies
    session.add(models.Allergy(patient_id=1, allergen="Penicillin", reaction="Anaphylaxis",
                                severity="severe"))
    session.add(models.Allergy(patient_id=1, allergen="Aspirin", reaction="Rash",
                                severity="mild"))

    # 4 visits (3 recent, 1 old)
    session.add(models.Visit(patient_id=1, visit_date=today - timedelta(days=10),
                              chief_complaint="Follow-up for diabetes", notes="Stable"))
    session.add(models.Visit(patient_id=1, visit_date=today - timedelta(days=60),
                              chief_complaint="Blood pressure check", notes="BP controlled"))
    session.add(models.Visit(patient_id=1, visit_date=today - timedelta(days=120),
                              chief_complaint="Routine check-up", notes="All good"))
    session.add(models.Visit(patient_id=1, visit_date=date(2018, 1, 1),
                              chief_complaint="Old visit", notes="Historical"))

    session.commit()
    yield session
    session.close()


# ─── Retriever Tests ──────────────────────────────────────────────────────────

class TestMedicationRetrieval:
    def test_returns_only_active_medications(self, db_session):
        """medication_check should return only active medications by default."""
        from backend.services.retriever import retrieve
        records, sources = retrieve(1, 'medication_check', {}, db_session)
        assert len(records) == 2, f"Expected 2 active medications, got {len(records)}"
        assert all(r.is_active for r in records)

    def test_drug_name_filter(self, db_session):
        """medication_check with drug entity should filter by drug name."""
        from backend.services.retriever import retrieve
        records, sources = retrieve(1, 'medication_check', {'drug': 'metformin'}, db_session)
        assert len(records) >= 1
        assert any('metformin' in r.drug_name.lower() for r in records)

    def test_drug_filter_case_insensitive(self, db_session):
        """Drug name filter should be case-insensitive."""
        from backend.services.retriever import retrieve
        records1, _ = retrieve(1, 'medication_check', {'drug': 'Metformin'}, db_session)
        records2, _ = retrieve(1, 'medication_check', {'drug': 'METFORMIN'}, db_session)
        assert len(records1) == len(records2)

    def test_sources_include_drug_name(self, db_session):
        """Sources should include the drug name for citations."""
        from backend.services.retriever import retrieve
        _, sources = retrieve(1, 'medication_check', {}, db_session)
        assert len(sources) > 0
        source_text = ' '.join(sources).lower()
        assert 'metformin' in source_text or 'amlodipine' in source_text


class TestLabResultsRetrieval:
    def test_returns_lab_results_ordered_by_date(self, db_session):
        """lab_results should return results ordered by most recent first."""
        from backend.services.retriever import retrieve
        records, _ = retrieve(1, 'lab_results', {}, db_session)
        assert len(records) > 0
        dates = [r.test_date for r in records]
        assert dates == sorted(dates, reverse=True), "Results not ordered by date desc"

    def test_lab_test_name_filter(self, db_session):
        """lab_results with lab_test entity should filter by test name."""
        from backend.services.retriever import retrieve
        records, sources = retrieve(1, 'lab_results', {'lab_test': 'HbA1c'}, db_session)
        assert len(records) >= 1
        assert all('hba1c' in r.test_name.lower() for r in records)

    def test_date_range_filter(self, db_session):
        """lab_results with date_range should only return results within window."""
        from backend.services.retriever import retrieve
        # "last 3 months" = ~90 days
        records, _ = retrieve(1, 'lab_results', {'date_range': 'last 3 months'}, db_session)
        today = date.today()
        cutoff = today - timedelta(days=90)
        assert all(r.test_date >= cutoff for r in records), \
            "Some lab results are outside the 3-month window"

    def test_limit_applied(self, db_session):
        """limit entity should cap the number of results returned."""
        from backend.services.retriever import retrieve
        records, _ = retrieve(1, 'lab_results', {'limit': 2}, db_session)
        assert len(records) <= 2


class TestAllergyRetrieval:
    def test_returns_all_allergies(self, db_session):
        """allergy_check should return all allergies for the patient."""
        from backend.services.retriever import retrieve
        records, sources = retrieve(1, 'allergy_check', {}, db_session)
        assert len(records) == 2
        allergens = {r.allergen for r in records}
        assert "Penicillin" in allergens
        assert "Aspirin" in allergens

    def test_sources_include_allergen(self, db_session):
        """Sources should include allergen names."""
        from backend.services.retriever import retrieve
        _, sources = retrieve(1, 'allergy_check', {}, db_session)
        source_text = ' '.join(sources)
        assert 'Penicillin' in source_text


class TestVisitRetrieval:
    def test_returns_visits_ordered_by_date(self, db_session):
        """visit_summary should return visits ordered by most recent first."""
        from backend.services.retriever import retrieve
        records, _ = retrieve(1, 'visit_summary', {}, db_session)
        assert len(records) > 0
        dates = [r.visit_date for r in records]
        assert dates == sorted(dates, reverse=True)

    def test_visit_limit_applied(self, db_session):
        """last N visits should be limited correctly."""
        from backend.services.retriever import retrieve
        records, _ = retrieve(1, 'visit_summary', {'limit': 2}, db_session)
        assert len(records) == 2

    def test_visit_date_filter(self, db_session):
        """visit_summary with date_range should filter visits."""
        from backend.services.retriever import retrieve
        records, _ = retrieve(1, 'visit_summary', {'date_range': 'last 6 months'}, db_session)
        today = date.today()
        cutoff = today - timedelta(days=180)
        assert all(r.visit_date >= cutoff for r in records)


class TestDiagnosisRetrieval:
    def test_returns_all_diagnoses(self, db_session):
        """diagnosis_check should return all diagnoses (active and inactive)."""
        from backend.services.retriever import retrieve
        records, _ = retrieve(1, 'diagnosis_check', {}, db_session)
        assert len(records) == 3  # 2 active + 1 inactive

    def test_condition_filter(self, db_session):
        """diagnosis_check with condition entity should filter by description."""
        from backend.services.retriever import retrieve
        records, _ = retrieve(1, 'diagnosis_check', {'condition': 'diabetes'}, db_session)
        assert len(records) >= 1
        assert all('diabetes' in r.description.lower() for r in records)


class TestHistoryLookupRetrieval:
    def test_returns_combined_dict(self, db_session):
        """history_lookup should return a dict with all 4 record types."""
        from backend.services.retriever import retrieve
        records, sources = retrieve(1, 'history_lookup', {}, db_session)
        assert isinstance(records, dict), "history_lookup should return a dict"
        assert 'diagnoses' in records
        assert 'medications' in records
        assert 'labs' in records
        assert 'allergies' in records

    def test_history_has_data(self, db_session):
        """history_lookup should return at least one record per category."""
        from backend.services.retriever import retrieve
        records, _ = retrieve(1, 'history_lookup', {}, db_session)
        assert len(records['diagnoses']) > 0
        assert len(records['medications']) > 0
        assert len(records['labs']) > 0
        assert len(records['allergies']) > 0


class TestRiskFlagRetrieval:
    def test_risk_flag_behaves_like_history(self, db_session):
        """risk_flag should return the same combined dict as history_lookup."""
        from backend.services.retriever import retrieve
        records, _ = retrieve(1, 'risk_flag', {}, db_session)
        assert isinstance(records, dict)
        assert 'diagnoses' in records


class TestEdgeCases:
    def test_patient_with_no_records(self, db_session):
        """Retrieval for non-existent patient should return empty results."""
        from backend.services.retriever import retrieve
        records, sources = retrieve(9999, 'medication_check', {}, db_session)
        assert records == [] or (isinstance(records, list) and len(records) == 0)
        assert sources == []

    def test_unknown_intent_returns_empty(self, db_session):
        """Unknown intents not handled explicitly should return empty records."""
        from backend.services.retriever import retrieve
        records, sources = retrieve(1, 'general_question', {}, db_session)
        # general_question has no retrieval logic → empty
        assert records == [] or records == {}
