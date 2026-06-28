"""
LLM service layer
-----------------
Thin wrapper around the configured language-model backend (Ollama or OpenAI).

Supported backends (set via ``LLM_BACKEND`` environment variable):
  - **ollama** (default) — runs a local Ollama server at ``http://localhost:11434/v1``.
    The main chat model is controlled by ``OLLAMA_MODEL`` (default: ``medgemma1.5:latest``);
    multimodal image analysis uses ``OLLAMA_MULTIMODAL_MODEL`` (default: ``OLLAMA_MODEL``).
  - **openai** — proxies requests through the OpenAI API using ``OPENAI_API_KEY``.
    Defaults to ``gpt-4o`` for all requests.

Public interface:
  - :func:`generate_answer` — stream tokens for a patient-specific clinical query backed
    by retrieved medical records.
  - :func:`generate_general` — stream tokens for a general medical Q&A query (no patient
    context).
  - :func:`generate_answer_with_image` — send a base64-encoded image together with an
    optional text prompt to the multimodal model and stream the response. If the
    multimodal endpoint is unavailable, it returns an explicit failure message instead
    of a fake clinical interpretation.

All three public functions are *streaming generators* — they yield raw text chunks so
callers can forward them directly to ``StreamingResponse``.
"""

import base64
import os
from pathlib import Path
from typing import Generator, Optional

import httpx
from dotenv import load_dotenv
from openai import OpenAI

from .. import models

load_dotenv()

# ── Configuration ─────────────────────────────────────────────────────────────
BACKEND      = os.getenv('LLM_BACKEND', 'ollama').lower()
OPENAI_KEY   = os.getenv('OPENAI_API_KEY')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'medgemma1.5:latest')

OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')

if BACKEND == 'ollama':
    client = OpenAI(base_url=f"{OLLAMA_BASE_URL.rstrip('/')}/v1", api_key="ollama")
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
4. Structure the response for fast clinical review. Organize information under meaningful clinical headings, use chronological timelines for events, tables for laboratory trends or medication summaries when appropriate, and bullet points only where they improve readability. Highlight abnormal or clinically significant findings within their relevant section while remaining faithful to the records.
5. Flag abnormal labs or dangerous drug combinations with ⚠️.
6. Never make treatment recommendations.
7. Do NOT output phrases like 'Final Answer:', 'Answer Structure:', or any meta-description of your response. Just write the answer."""


GENERAL_SYSTEM_PROMPT = """You are MedGemma, an expert clinical AI assistant assisting healthcare professionals.

Perform your complete clinical reasoning internally, then provide only the final clinical response.

Rules:

1. Base every statement only on the provided context and patient records.
2. Never fabricate, infer, or assume information that is not explicitly supported by the records.
3. If the requested information is unavailable, clearly state:
   "The available records do not contain this information."
4. Do not provide diagnoses, treatment recommendations, or medical advice beyond what is documented.
5. Flag clinically important abnormalities with ⚠️.
6. Write for clinicians, prioritizing rapid review and decision support.

Response Structure

Whenever applicable, organize the response using the following sections (omit sections that have no relevant information):

# Clinical Summary
- Provide a concise 2–5 sentence overview of the patient's current clinical status.

# Active Medical Problems
- Group conditions by organ system (e.g., Cardiovascular, Respiratory, Neurological, Endocrine, Musculoskeletal).
- Prioritize active and clinically significant conditions before historical or resolved conditions.
- Clearly distinguish Active vs Historical conditions.

# Current Medications
Present medications in a table:

| Medication | Status | Indication (if documented) |
|------------|--------|----------------------------|

Do not infer indications.

# Laboratory Findings
- Present laboratory results in tables whenever possible.
- Group related tests together.
- Highlight abnormal values with ⚠️.
- Preserve reported units and reference ranges when available.
- For repeated measurements, summarize trends chronologically instead of listing every value.

# Imaging and Diagnostic Studies
- Summarize only clinically relevant findings.
- Organize chronologically when multiple studies exist.

# Procedures / Hospitalizations
- Present significant procedures and encounters in chronological order.

# Allergies
- List documented allergies.
- If none are documented, explicitly state that no allergy information is available.

# Clinical Timeline
Present important clinical events from oldest to newest (or newest to oldest if requested), including diagnoses, admissions, procedures, major laboratory changes, and significant monitoring events.

# Clinically Significant Findings
Highlight the most important findings requiring clinical attention using ⚠️.
Do not exaggerate importance or introduce unsupported conclusions.

# Sources
Reference the supporting records used for each major conclusion (e.g., "Condition Record #4", "Laboratory Report #2", "Medication List", "Encounter #5").

Formatting Guidelines

- Use clear section headings.
- Use tables for structured information whenever appropriate.
- Use bullet points only to improve readability.
- Avoid long paragraphs.
- Avoid repeating the same information across sections.
- Merge duplicate findings into a single concise summary.
- Present information in a logical clinical order rather than the order it appears in the records.

Never output internal reasoning, chain-of-thought, or meta-commentary.
Do not output phrases such as "Final Answer", "Reasoning", "Answer Structure", or similar.
Begin directly with the clinical response.
"""
VISION_SYSTEM_PROMPT = """You are MedGemma, an expert medical AI assistant specializing in clinical image analysis.
Perform your step-by-step clinical reasoning first, then write your final clinical answer directly.

Rules:
- Respond ONLY in standard natural language prose and lists.
- Do NOT output any JSON, coordinates, 2D boxes (box_2d), bounding boxes, or object detection tags (like '<img>').
- Describe all findings in natural language.
- Use bullet points or numbered lists for structured findings.
- Flag critical findings with ⚠️.
- Do not fabricate information."""



# ── Image Prompt Templates ─────────────────────────────────────────────────────
NO_GROUNDING_INSTRUCTION = (
    "\n\nIMPORTANT: Respond ONLY in plain clinical natural language. "
    "Do NOT perform object detection, region of interest detection, or anatomical localization. "
    "Do NOT output any JSON, coordinates, 2D boxes (box_2d), bounding boxes, or tags like '<img>'. "
    "Your description must be written in standard paragraphs and bullet points."
)

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
        + NO_GROUNDING_INSTRUCTION
    ),
    "ct_mri": (
        "You are a radiologist analyzing a medical scan (CT or MRI).\n"
        "Describe:\n"
        "1. Modality and visible anatomical region\n"
        "2. Normal structures identified\n"
        "3. Any abnormalities, lesions, or concerning findings — flag with ⚠️\n"
        "4. Impression and recommended follow-up if applicable"
        + NO_GROUNDING_INSTRUCTION
    ),
    "lab_report": (
        "Extract all laboratory results from this document.\n"
        "For each test, provide a table row with:\n"
        "| Test Name | Value | Unit | Reference Range | Status (Normal/High/Low/Critical) |\n"
        "After the table, summarize any critical or abnormal values with ⚠️."
        + NO_GROUNDING_INSTRUCTION
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
        + NO_GROUNDING_INSTRUCTION
    ),
    "dermatology": (
        "You are a dermatologist analyzing this skin image.\n"
        "Describe:\n"
        "1. Location and distribution of the lesion(s)\n"
        "2. Morphology: size, shape, color, borders, surface texture\n"
        "3. Secondary changes (scaling, crusting, ulceration, etc.)\n"
        "4. Differential diagnosis (most to least likely)\n"
        "5. Recommended next steps"
        + NO_GROUNDING_INSTRUCTION
    ),
    "general": (
        "Analyze this medical image carefully.\n"
        "Describe all visible findings, note any abnormalities, and provide a clinical impression.\n"
        "Flag critical findings with ⚠️."
        + NO_GROUNDING_INSTRUCTION
    ),
}


def _ollama_model_capabilities(model_name: str) -> list[str]:
    """Return capability labels reported by Ollama for a local model."""
    try:
        response = httpx.get(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags", timeout=5.0)
        response.raise_for_status()
        for model in response.json().get("models", []):
            if model.get("name") == model_name or model.get("model") == model_name:
                return model.get("capabilities", [])
    except Exception:
        return []
    return []


def _is_model_installed(model_name: str) -> bool:
    """Return True if a model with the given name is installed in Ollama."""
    try:
        response = httpx.get(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags", timeout=5.0)
        response.raise_for_status()
        for model in response.json().get("models", []):
            if model.get("name") == model_name or model.get("model") == model_name:
                return True
    except Exception:
        pass
    return False


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
    """
    Send an image + text prompt to the configured multimodal model and stream the response.

    MedGemma 1.5 documentation describes image reasoning through the 4B multimodal
    instruction-tuned model (`google/medgemma-1.5-4b-it`) using image+text chat
    messages. For this app's Ollama/OpenAI-compatible path, the configured model
    therefore must be a vision-capable MedGemma model. If that call fails, do not
    fabricate findings; return an explicit service error.
    """
    # Normalize image to standard RGB JPEG and downscale if too large (speeds up CPU inference)
    import io

    from PIL import Image
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        MAX_SIZE = 1024
        if max(img.size) > MAX_SIZE:
            img.thumbnail((MAX_SIZE, MAX_SIZE), Image.Resampling.LANCZOS)
            
        output_buffer = io.BytesIO()
        img.save(output_buffer, format='JPEG', quality=85)
        image_bytes = output_buffer.getvalue()
    except Exception as conv_err:
        print(f"Image normalization warning: {conv_err}. Proceeding with raw bytes.")

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
        multimodal_model = os.getenv('OLLAMA_MULTIMODAL_MODEL', OLLAMA_MODEL)
        model_to_use = multimodal_model if BACKEND == 'ollama' else 'gpt-4o'

        # Per MedGemma 1.5 documentation, images are sent as part of a multimodal
        # chat message with the image FIRST then the text prompt, matching the
        # HuggingFace apply_chat_template format. The image is embedded as a
        # data-URI inside an image_url content block (OpenAI-compatible path).
        # No capability pre-check is done — the model is trusted to handle vision
        # per its documentation; any failure surfaces as a real error below.
        stream = client.chat.completions.create(
            model=model_to_use,
            stream=True,
            temperature=0.3,
            frequency_penalty=1.0,
            max_tokens=2048,
            messages=[
                {'role': 'system', 'content': VISION_SYSTEM_PROMPT},
                {
                    'role': 'user',
                    'content': [
                        # Image FIRST, then text — matches MedGemma 1.5 docs format
                        {
                            'type': 'image_url',
                            'image_url': {'url': f'data:image/jpeg;base64,{image_b64}'}
                        },
                        {'type': 'text', 'text': full_prompt},
                    ]
                }
            ],
            timeout=120.0  # Vision inference takes longer
        )

        import re
        buffer = ""
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                # Strip MedGemma 1.5 image-position boundary tokens that leak
                # into the text output when running via the OpenAI-compatible path.
                filtered = delta
                for tok in ('📁', '<end_of_image>'):
                    filtered = filtered.replace(tok, '')
                if filtered:
                    buffer += filtered
                    # Replace stray } after quote-colon-space-quote
                    buffer = re.sub(r'":\s*"}', '": "', buffer)
                    # Replace invalid trailing comma sequence
                    buffer = re.sub(r'",\s*\},', '"},', buffer)
                    
                    if len(buffer) > 30:
                        yield buffer[:-30]
                        buffer = buffer[-30:]
        
        # Flush remainder
        if buffer:
            buffer = re.sub(r'":\s*"}', '": "', buffer)
            buffer = re.sub(r'",\s*\},', '"},', buffer)
            yield buffer

    except Exception as e:
        import time
        import traceback
        log_dir = Path(__file__).resolve().parent.parent.parent / "runtime" / "logs" / "backend"
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / "multimodal_error.log"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n--- ERROR at {time.time()} ---\n")
            f.write(f"Exception: {e}\n")
            traceback.print_exc(file=f)
        print(f"Multimodal image analysis error: {e}. See {log_path}.")
        yield "**Image analysis unavailable**\n\n"
        yield (
            "The uploaded image was received, but the configured multimodal model did "
            "not return a valid response. No clinical image findings were generated.\n\n"
        )
        yield f"Model attempted: `{model_to_use}`\n\n"
        yield (
            "Check that a MedGemma 1.5 multimodal model is installed/running and that "
            "the serving API accepts image+text chat messages. See `logs/multimodal_error.log` "
            "for the backend exception."
        )
