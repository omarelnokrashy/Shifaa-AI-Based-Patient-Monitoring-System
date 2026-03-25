from openai import OpenAI
from dotenv import load_dotenv
from typing import Generator
from .. import models
import os

load_dotenv()

# Configuration
BACKEND = os.getenv('LLM_BACKEND', 'openai').lower()
OPENAI_KEY = os.getenv('OPENAI_API_KEY')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama3.2')

if BACKEND == 'ollama':
    client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
    MODEL = OLLAMA_MODEL
else:
    client = OpenAI(api_key=OPENAI_KEY)
    MODEL = 'gpt-4o'


SYSTEM_PROMPT = """
You are a clinical assistant AI helping a doctor review patient medical history.

STRICT RULES:
1. Answer ONLY from the patient data provided below. Do not use outside knowledge.
2. Always cite which record your answer comes from (e.g. 'According to Lab #3...')
3. If the data does not contain the answer, say exactly: 'The records do not contain this information.'
4. Be concise and clinically precise. Use bullet points for lists.
5. Never make medical recommendations. You are presenting records only.
6. If you see abnormal lab values or dangerous drug combinations, flag them clearly.
"""

def _format_records(intent: str, records, patient: models.Patient) -> str:
    """Convert retrieved DB records into a formatted string for the prompt."""
    patient_info = (
        f'Patient: {patient.name}, DOB: {patient.dob}, Gender: {patient.gender}, '
        f'Blood Type: {patient.blood_type}'
    )

    if isinstance(records, dict):
        parts = [patient_info, '\n--- DIAGNOSES ---']
        for d in records.get('diagnoses', []):
            parts.append(f'  [{d.id}] {d.description} ({d.icd10_code}) | Severity: {d.severity} | Active: {d.is_active}')
        parts.append('\n--- ACTIVE MEDICATIONS ---')
        for m in records.get('medications', []):
            parts.append(f'  [{m.id}] {m.drug_name} {m.dose} | Since: {m.start_date}')
        parts.append('\n--- RECENT LABS ---')
        for l in records.get('labs', []):
            flag = ' ⚠ ABNORMAL' if l.is_abnormal else ''
            parts.append(f'  [{l.id}] {l.test_name}: {l.value} {l.unit} (ref: {l.reference}) on {l.test_date}{flag}')
        parts.append('\n--- ALLERGIES ---')
        for a in records.get('allergies', []):
            parts.append(f'  [{a.id}] {a.allergen} → {a.reaction} ({a.severity})')
        return '\n'.join(parts)

    lines = [patient_info, f'\n--- RETRIEVED RECORDS ({intent}) ---']
    for r in records:
        if hasattr(r, 'drug_name'):
            lines.append(f'  [{r.id}] {r.drug_name} {r.dose} | Active: {r.is_active} | Since: {r.start_date}')
        elif hasattr(r, 'test_name'):
            flag = ' ⚠ ABNORMAL' if r.is_abnormal else ''
            lines.append(f'  [{r.id}] {r.test_name}: {r.value} {r.unit} (ref: {r.reference}) on {r.test_date}{flag}')
        elif hasattr(r, 'description') and hasattr(r, 'icd10_code'):
            lines.append(f'  [{r.id}] {r.description} ({r.icd10_code}) | {r.severity} | Active: {r.is_active}')
        elif hasattr(r, 'allergen'):
            lines.append(f'  [{r.id}] {r.allergen} → {r.reaction} ({r.severity})')
        elif hasattr(r, 'chief_complaint'):
            lines.append(f'  [{r.id}] Visit on {r.visit_date}: {r.chief_complaint}')
            if r.notes: lines.append(f'      Notes: {r.notes[:200]}...')
        else:
            lines.append(f'  [{r.id}] {str(r)}')
    return '\n'.join(lines)

def generate_answer(query: str, intent: str, records, patient: models.Patient) -> Generator:
    """
    Calls OpenAI with retrieved patient data and streams the response.
    Yields text chunks as they arrive.
    """
    context = _format_records(intent, records, patient)

    stream = client.chat.completions.create(
        model=MODEL,
        stream=True,
        temperature=0.2,
        max_tokens=800,

        messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': (
                f'PATIENT DATA:\n{context}\n\n'
                f'DOCTOR QUERY: {query}'
            )}
        ]
    )

    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
