"""
Intent classification service
-------------------------------
Determines the *intent* of a doctor's query so the retriever can select the
correct database tables and filters.

Primary path: sends the query to the configured LLM (``gpt-4o-mini`` or a local
Ollama model) with a tightly-constrained JSON system prompt that returns one of
eight intent labels and a confidence score.

Fallback path (:func:`_classify_intent_local`): if the LLM call fails or times
out (4 s hard limit), a lightweight keyword-matching function is used instead so
the pipeline is never completely blocked.

Recognised intents:
  ``history_lookup``, ``medication_check``, ``lab_results``, ``allergy_check``,
  ``visit_summary``, ``diagnosis_check``, ``risk_flag``, ``general_question``
"""

from openai import OpenAI
from dotenv import load_dotenv
import json, os

load_dotenv()

# Configuration
BACKEND = os.getenv('LLM_BACKEND', 'openai').lower()
OPENAI_KEY = os.getenv('OPENAI_API_KEY')
OLLAMA_INTENT_MODEL = os.getenv('OLLAMA_INTENT_MODEL', 'llama3.2')

if BACKEND == 'ollama':
    client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
    MODEL = OLLAMA_INTENT_MODEL
else:
    client = OpenAI(api_key=OPENAI_KEY)
    MODEL = 'gpt-4o-mini'


# All possible intent types
INTENTS = [
    'history_lookup',    # general medical history
    'medication_check',  # what drugs is patient on
    'lab_results',       # lab test values
    'allergy_check',     # allergies
    'visit_summary',     # past visits
    'diagnosis_check',   # diagnoses / conditions
    'risk_flag',         # any concerning findings
    'general_question',  # medical question not about specific patient
]

SYSTEM_PROMPT = """
You are a medical intent classifier. Given a doctor's query, return a JSON object with:
- intent: one of the following ONLY: history_lookup, medication_check, lab_results,
  allergy_check, visit_summary, diagnosis_check, risk_flag, general_question
- confidence: a float between 0 and 1

Return ONLY valid JSON. No extra text. Example:
{"intent": "medication_check", "confidence": 0.97}
"""

def _classify_intent_local(query: str) -> dict:
    """
    Rule-based intent classifier used as a fallback when the LLM is unavailable.

    Matches lowercase keywords in the query against hard-coded lists for each
    intent category.  Returns the first match found in priority order, or
    ``history_lookup`` with a lower confidence score if nothing matches.

    Parameters
    ----------
    query : str
        The raw doctor query.

    Returns
    -------
    dict
        ``{'intent': str, 'confidence': float}`` — same schema as the LLM path.
    """
    q = query.lower()
    if any(k in q for k in ['medication', 'drug', 'medicine', 'prescription', 'dose', 'dosing', 'pill', 'prescribe']):
        return {'intent': 'medication_check', 'confidence': 0.9}
    if any(k in q for k in ['lab', 'test', 'result', 'hba1c', 'glucose', 'creatinine', 'blood', 'urine', 'panel']):
        return {'intent': 'lab_results', 'confidence': 0.9}
    if any(k in q for k in ['allergy', 'allergies', 'reaction', 'allergic']):
        return {'intent': 'allergy_check', 'confidence': 0.9}
    if any(k in q for k in ['visit', 'encounter', 'checkup', 'admit', 'admission', 'discharge']):
        return {'intent': 'visit_summary', 'confidence': 0.9}
    if any(k in q for k in ['diagnos', 'disease', 'condition', 'illness', 'sick', 'asthma', 'diabetes', 'hypertension']):
        return {'intent': 'diagnosis_check', 'confidence': 0.9}
    if any(k in q for k in ['risk', 'flag', 'danger', 'concern', 'warn', 'critical', 'alert']):
        return {'intent': 'risk_flag', 'confidence': 0.9}
    if any(k in q for k in ['explain', 'what is', 'how to', 'define', 'general']):
        return {'intent': 'general_question', 'confidence': 0.8}
    return {'intent': 'history_lookup', 'confidence': 0.7}


def classify_intent(query: str) -> dict:
    """
    Takes a doctor's message and returns the detected intent.
    Returns a dict: {'intent': str, 'confidence': float}
    """
    try:
        response = client.chat.completions.create(
            model=MODEL,      # cheap and fast for classification
            response_format={'type': 'json_object'},
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': query}
            ],
            temperature=0.0,          # deterministic output for classification
            timeout=15.0
        )
        result = json.loads(response.choices[0].message.content)
        if result.get('intent') not in INTENTS:
            result['intent'] = 'history_lookup'  # safe fallback
        return result
    except Exception as e:
        print(f'Intent classification error: {e}. Falling back to rule-based.')
        return _classify_intent_local(query)
