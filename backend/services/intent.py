from openai import OpenAI
from dotenv import load_dotenv
import json, os

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
            temperature=0.0           # deterministic output for classification
        )
        result = json.loads(response.choices[0].message.content)
        if result.get('intent') not in INTENTS:
            result['intent'] = 'history_lookup'  # safe fallback
        return result
    except Exception as e:
        print(f'Intent classification error: {e}')
        return {'intent': 'history_lookup', 'confidence': 0.5}
