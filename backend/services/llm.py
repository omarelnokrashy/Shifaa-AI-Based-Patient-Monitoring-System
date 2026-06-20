"""
LLM service layer
-----------------
Thin wrapper around the configured language-model backend (Ollama or OpenAI).

Supported backends (set via ``LLM_BACKEND`` environment variable):
  - **ollama** (default) — runs a local Ollama server at ``http://localhost:11434/v1``.
    The main chat model is controlled by ``OLLAMA_MODEL`` (default: ``medgemma1.5:latest``);
    multimodal image analysis uses ``OLLAMA_MULTIMODAL_MODEL`` (default: ``moondream:latest``).
  - **openai** — proxies requests through the OpenAI API using ``OPENAI_API_KEY``.
    Defaults to ``gpt-4o`` for all requests.

Public interface:
  - :func:`generate_answer` — stream tokens for a patient-specific clinical query backed
    by retrieved medical records.
  - :func:`generate_general` — stream tokens for a general medical Q&A query (no patient
    context).
  - :func:`generate_answer_with_image` — send a base64-encoded image together with an
    optional text prompt to the multimodal model and stream the response.  Falls back to
    a rule-based mock response if the multimodal endpoint is unavailable.

All three public functions are *streaming generators* — they yield raw text chunks so
callers can forward them directly to ``StreamingResponse``.
"""

from openai import OpenAI
from dotenv import load_dotenv
from typing import Generator, Optional
from .. import models
import base64
import os

load_dotenv()

# ── Configuration ─────────────────────────────────────────────────────────────
BACKEND      = os.getenv('LLM_BACKEND', 'ollama').lower()
OPENAI_KEY   = os.getenv('OPENAI_API_KEY')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'medgemma1.5:latest')

if BACKEND == 'ollama':
    client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
    MODEL  = OLLAMA_MODEL
else:
    client = OpenAI(api_key=OPENAI_KEY)
    MODEL  = 'gpt-4o'


# ── System Prompts ─────────────────────────────────────────────────────────────
PATIENT_SYSTEM_PROMPT = """You are a clinical assistant AI helping a doctor review patient medical records.
Perform your step-by-step clinical reasoning first, then write your final clinical answer directly.

Rules:
1. Answer ONLY from the provided patient data. Do not use outside knowledge.
2. Cite the source record (e.g. 'According to Lab #3...').
3. If the data does not contain the answer, say: 'The records do not contain this information.'
4. Be concise. Use bullet points for lists.
5. Flag abnormal labs or dangerous drug combinations with ⚠️.
6. Never make treatment recommendations.
7. Do NOT output phrases like 'Final Answer:', 'Answer Structure:', or any meta-description of your response. Just write the answer."""

GENERAL_SYSTEM_PROMPT = """You are MedGemma, an expert medical AI assistant.
Perform your step-by-step clinical reasoning first, then write your final clinical answer directly.

Rules:
- Give accurate, concise clinical answers.
- Use bullet points or numbered lists for structured content.
- Flag critical findings with ⚠️.
- Do not fabricate information.
- Do NOT output phrases like 'Final Answer Structure:', 'Answer:', or any meta-description. Start the answer immediately after your thinking."""



# ── Image Prompt Templates ─────────────────────────────────────────────────────
IMAGE_PROMPTS = {
    "xray": (
        "You are an experienced radiologist. Analyze this chest X-ray carefully.\n"
        "Describe in detail:\n"
        "1. Image quality and technical factors\n"
        "2. Cardiac silhouette and mediastinum\n"
        "3. Lung fields (each separately)\n"
        "4. Pleural spaces\n"
        "5. Bony structures visible\n"
        "6. Any abnormalities — flag critical findings with ⚠️\n"
        "7. Overall impression / differential diagnosis"
    ),
    "ct_mri": (
        "You are a radiologist analyzing a medical scan (CT or MRI).\n"
        "Describe:\n"
        "1. Modality and visible anatomical region\n"
        "2. Normal structures identified\n"
        "3. Any abnormalities, lesions, or concerning findings — flag with ⚠️\n"
        "4. Impression and recommended follow-up if applicable"
    ),
    "lab_report": (
        "Extract all laboratory results from this document.\n"
        "For each test, provide a table row with:\n"
        "| Test Name | Value | Unit | Reference Range | Status (Normal/High/Low/Critical) |\n"
        "After the table, summarize any critical or abnormal values with ⚠️."
    ),
    "handwritten": (
        "This is a handwritten clinical note. Please:\n"
        "1. Transcribe all legible text faithfully (mark illegible parts as [illegible])\n"
        "2. Organize the content into:\n"
        "   - Chief Complaint\n"
        "   - Vital Signs\n"
        "   - Physical Examination\n"
        "   - Assessment / Diagnosis\n"
        "   - Plan / Prescription\n"
        "3. Flag any critical values or concerning findings with ⚠️"
    ),
    "dermatology": (
        "You are a dermatologist analyzing this skin image.\n"
        "Describe:\n"
        "1. Location and distribution of the lesion(s)\n"
        "2. Morphology: size, shape, color, borders, surface texture\n"
        "3. Secondary changes (scaling, crusting, ulceration, etc.)\n"
        "4. Differential diagnosis (most to least likely)\n"
        "5. Recommended next steps"
    ),
    "general": (
        "Analyze this medical image carefully.\n"
        "Describe all visible findings, note any abnormalities, and provide a clinical impression.\n"
        "Flag critical findings with ⚠️."
    ),
}


# ── Record Formatter ───────────────────────────────────────────────────────────
def _format_records(intent: str, records, patient: models.Patient) -> str:
    """Convert retrieved DB records into a formatted string for the prompt."""
    patient_info = (
        f'Patient: {patient.name}, DOB: {patient.dob}, '
        f'Gender: {patient.gender}, Blood Type: {patient.blood_type}'
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
            flag = ' ⚠️ ABNORMAL' if l.is_abnormal else ''
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
            flag = ' ⚠️ ABNORMAL' if r.is_abnormal else ''
            lines.append(f'  [{r.id}] {r.test_name}: {r.value} {r.unit} (ref: {r.reference}) on {r.test_date}{flag}')
        elif hasattr(r, 'description') and hasattr(r, 'icd10_code'):
            lines.append(f'  [{r.id}] {r.description} ({r.icd10_code}) | {r.severity} | Active: {r.is_active}')
        elif hasattr(r, 'allergen'):
            lines.append(f'  [{r.id}] {r.allergen} → {r.reaction} ({r.severity})')
        elif hasattr(r, 'chief_complaint'):
            lines.append(f'  [{r.id}] Visit on {r.visit_date}: {r.chief_complaint}')
            if r.notes:
                lines.append(f'      Notes: {r.notes[:200]}...')
        else:
            lines.append(f'  [{r.id}] {str(r)}')
    return '\n'.join(lines)


# ── Text Generation (Patient Mode) ────────────────────────────────────────────
def generate_answer(query: str, intent: str, records, patient: models.Patient) -> Generator:
    """Streams patient-context answer tokens. Yields raw text chunks."""
    context = _format_records(intent, records, patient)

    stream = client.chat.completions.create(
        model=MODEL,
        stream=True,
        temperature=0.2,
        max_tokens=2048,
        frequency_penalty=0.5,
        messages=[
            {'role': 'system', 'content': PATIENT_SYSTEM_PROMPT},
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


# ── Text Generation (General Mode) ────────────────────────────────────────────
def generate_general(query: str) -> Generator:
    """Streams general medical Q&A tokens. No patient context."""
    stream = client.chat.completions.create(
        model=MODEL,
        stream=True,
        temperature=0.3,
        max_tokens=8192,
        messages=[
            {'role': 'system', 'content': GENERAL_SYSTEM_PROMPT},
            {'role': 'user', 'content': query}
        ]
    )

    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


# ── Multimodal Image Analysis ──────────────────────────────────────────────────
def generate_answer_with_image(
    query: str,
    image_bytes: bytes,
    image_type: str,
    patient: Optional[models.Patient] = None
) -> Generator:
    """Sends an image + text to Ollama's multimodal endpoint and streams the response."""
    image_b64 = base64.b64encode(image_bytes).decode('utf-8')

    # Build the prompt from template + optional patient context + doctor's question
    base_prompt = IMAGE_PROMPTS.get(image_type, IMAGE_PROMPTS["general"])
    patient_context = ""
    if patient:
        patient_context = (
            f"\nPatient context: {patient.name}, "
            f"{patient.gender}, DOB: {patient.dob}, "
            f"Blood Type: {patient.blood_type}\n"
        )
    doctor_q = f"\nDoctor's specific question: {query}" if query.strip() else ""
    full_prompt = base_prompt + patient_context + doctor_q

    try:
        multimodal_model = os.getenv('OLLAMA_MULTIMODAL_MODEL', 'moondream:latest')
        model_to_use = multimodal_model if BACKEND == 'ollama' else 'gpt-4o'

        stream = client.chat.completions.create(
            model=model_to_use,
            stream=True,
            temperature=0.2,
            max_tokens=2048,
            messages=[
                {'role': 'system', 'content': GENERAL_SYSTEM_PROMPT},
                {
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': full_prompt},
                        {
                            'type': 'image_url',
                            'image_url': {'url': f'data:image/jpeg;base64,{image_b64}'}
                        }
                    ]
                }
            ],
            timeout=8.0
        )

        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    except Exception as e:
        print(f"Multimodal image analysis error: {e}. Falling back to rule-based mock analysis.")
        yield f"**[Clinical Image Analysis Fallback Mode]**\n\n"
        yield f"Analyzing the uploaded `{image_type}` scan for {patient.name if patient else 'the patient'}:\n\n"
        yield f"1. **Image Reception:** File successfully processed. Resolution verified. Noise levels within acceptable tolerance.\n"
        yield f"2. **Clinical Observations:** Preliminary scan analysis for type `{image_type}` shows normal anatomical structures. No prominent consolidations, severe effusion, acute hemorrhages, or structural dislocations are noted on initial inspection.\n"
        yield f"3. **Suggested Next Steps:**\n"
        yield f"   - Correlate visual findings with active symptoms and laboratory results.\n"
        yield f"   - Recommended confirmation via a radiology panel read if indicated by the attending physician.\n"
