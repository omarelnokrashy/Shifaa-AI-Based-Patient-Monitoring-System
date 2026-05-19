from sqlalchemy.orm import Session
from .. import models
from datetime import date, timedelta

def _parse_date_range(date_range_str: str | None):
    """Convert natural language date range to a cutoff date."""
    if not date_range_str:
        return None
    s = date_range_str.lower()
    today = date.today()
    if 'month' in s:
        try: 
            digits = ''.join(filter(str.isdigit, s))
            months = int(digits) if digits else 1
        except: months = 1
        return today - timedelta(days=months * 30)
    if 'year' in s:
        try: 
            digits = ''.join(filter(str.isdigit, s))
            years = int(digits) if digits else 1
        except: years = 1
        return today - timedelta(days=years * 365)
    if 'week' in s:
        try: 
            digits = ''.join(filter(str.isdigit, s))
            weeks = int(digits) if digits else 1
        except: weeks = 1
        return today - timedelta(weeks=weeks)
    return None

def retrieve(patient_id: int, intent: str, entities: dict, db: Session) -> tuple[list, list]:
    """
    Returns (records_list, sources_list) based on intent and entities.
    records_list: list of model objects
    sources_list: list of human-readable source strings for citations
    """
    records = []
    sources = []
    limit   = entities.get('limit') or 10
    cutoff  = _parse_date_range(entities.get('date_range'))

    if intent == 'medication_check':
        drug_filter = entities.get('drug')
        q = db.query(models.Medication).filter(models.Medication.patient_id == patient_id)
        if drug_filter:
            q = q.filter(models.Medication.drug_name.ilike(f'%{drug_filter}%'))
        records = q.filter(models.Medication.is_active == True).all()
        sources = [f'Medication record #{r.id}: {r.drug_name} {r.dose}' for r in records]

    elif intent == 'lab_results':
        test_filter = entities.get('lab_test')
        q = db.query(models.LabResult).filter(models.LabResult.patient_id == patient_id)
        if test_filter:
            q = q.filter(models.LabResult.test_name.ilike(f'%{test_filter}%'))
        if cutoff:
            q = q.filter(models.LabResult.test_date >= cutoff)
        records = q.order_by(models.LabResult.test_date.desc()).limit(limit).all()
        sources = [f'Lab #{r.id}: {r.test_name} = {r.value} {r.unit} on {r.test_date}' for r in records]

    elif intent == 'allergy_check':
        records = db.query(models.Allergy).filter(models.Allergy.patient_id == patient_id).all()
        sources = [f'Allergy #{r.id}: {r.allergen} — {r.reaction}' for r in records]

    elif intent == 'visit_summary':
        q = db.query(models.Visit).filter(models.Visit.patient_id == patient_id)
        if cutoff:
            q = q.filter(models.Visit.visit_date >= cutoff)
        records = q.order_by(models.Visit.visit_date.desc()).limit(limit).all()
        sources = [f'Visit #{r.id} on {r.visit_date}: {r.chief_complaint}' for r in records]

    elif intent == 'diagnosis_check':
        cond_filter = entities.get('condition')
        q = db.query(models.Diagnosis).filter(models.Diagnosis.patient_id == patient_id)
        if cond_filter:
            q = q.filter(models.Diagnosis.description.ilike(f'%{cond_filter}%'))
        records = q.all()
        sources = [f'Diagnosis #{r.id}: {r.description} ({r.icd10_code}) since {r.diagnosed_on}' for r in records]

    elif intent in ('history_lookup', 'risk_flag'):
        # For general history, fetch everything
        diags = db.query(models.Diagnosis).filter(models.Diagnosis.patient_id == patient_id).all()
        meds  = db.query(models.Medication).filter(models.Medication.patient_id == patient_id, models.Medication.is_active == True).all()
        labs  = db.query(models.LabResult).filter(models.LabResult.patient_id == patient_id).order_by(models.LabResult.test_date.desc()).limit(5).all()
        allgs = db.query(models.Allergy).filter(models.Allergy.patient_id == patient_id).all()
        records = {'diagnoses': diags, 'medications': meds, 'labs': labs, 'allergies': allgs}
        sources = ([f'Diagnosis: {r.description}' for r in diags] +
                   [f'Medication: {r.drug_name}' for r in meds] +
                   [f'Lab: {r.test_name}={r.value}{r.unit}' for r in labs])

    return records, sources
