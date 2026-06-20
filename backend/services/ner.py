"""
Named Entity Recognition (NER) service
---------------------------------------
Extracts structured medical entities from a free-text doctor query so the
retriever can apply precise database filters.

Primary path: sends the query to the configured LLM (``gpt-4o-mini`` or a local
Ollama model) with a JSON system prompt that returns a fixed-schema object.

Fallback path (:func:`_extract_entities_local`): if the LLM call fails or times
out (4 s hard limit), a regex / keyword scan is used instead.

Extracted entity fields:
  - ``date_range`` — temporal qualifier (e.g., "last 3 months", "last year")
  - ``condition``  — clinical condition keyword (e.g., "diabetes")
  - ``drug``       — medication name (e.g., "metformin")
  - ``lab_test``   — laboratory test name (e.g., "HbA1c")
  - ``limit``      — integer count qualifier (e.g., 3 from "last 3 visits")
"""

from openai import OpenAI
from dotenv import load_dotenv
import json, os

load_dotenv()

# Configuration
BACKEND = os.getenv('LLM_BACKEND', 'openai').lower()
OPENAI_KEY = os.getenv('OPENAI_API_KEY')
OLLAMA_NER_MODEL = os.getenv('OLLAMA_NER_MODEL', 'llama3.2')

if BACKEND == 'ollama':
    client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
    MODEL = OLLAMA_NER_MODEL
else:
    client = OpenAI(api_key=OPENAI_KEY)
    MODEL = 'gpt-4o-mini'


NER_SYSTEM = """
You are a medical named entity extractor. Extract entities from the doctor query.
Return ONLY a JSON object with these fields (use null if not mentioned):
{
  "date_range": null or string like 'last 3 months' or '2024'
  "condition": null or string e.g. 'diabetes'
  "drug": null or string e.g. 'metformin'
  "lab_test": null or string e.g. 'HbA1c'
  "limit": null or integer e.g. 3 (when doctor says 'last 3 visits')
}
Return ONLY valid JSON.
"""

def _extract_entities_local(query: str) -> dict:
    """
    Rule-based entity extractor used as a fallback when the LLM is unavailable.

    Uses regular expressions and hard-coded keyword lists to populate a subset of
    the entity schema.  Only common values are covered; rare entities default to
    ``None``.

    Parameters
    ----------
    query : str
        The raw doctor query.

    Returns
    -------
    dict
        Keys: ``date_range``, ``condition``, ``drug``, ``lab_test``, ``limit``.
        Unrecognised fields are ``None``.
    """
    q = query.lower()
    entities = {
        "date_range": None,
        "condition": None,
        "drug": None,
        "lab_test": None,
        "limit": None
    }
    # Limit
    import re
    limit_match = re.search(r'(?:last|recent)\s+(\d+)\s+(?:visit|encounter|record|lab)', q)
    if limit_match:
        entities["limit"] = int(limit_match.group(1))
    
    # Date range
    if 'last 3 months' in q:
        entities["date_range"] = 'last 3 months'
    elif 'last 6 months' in q:
        entities["date_range"] = 'last 6 months'
    elif 'last year' in q or 'past year' in q:
        entities["date_range"] = 'last year'
    
    # Common conditions
    conditions = ['diabetes', 'hypertension', 'asthma', 'heart failure', 'copd', 'arrhythmia']
    for c in conditions:
        if c in q:
            entities["condition"] = c
            break
            
    # Common drugs
    drugs = ['metformin', 'amlodipine', 'lisinopril', 'aspirin', 'atorvastatin', 'albuterol', 'insulin']
    for d in drugs:
        if d in q:
            entities["drug"] = d
            break
            
    # Common labs
    labs = ['hba1c', 'glucose', 'creatinine', 'potassium', 'sodium', 'hemoglobin', 'wbc']
    for l in labs:
        if l in q:
            entities["lab_test"] = l
            break
            
    return entities


def extract_entities(query: str) -> dict:
    """
    Extract medical entities from a query string.
    Returns a dict with keys: date_range, condition, drug, lab_test, limit
    """
    try:
        response = client.chat.completions.create(
            model=MODEL,
            response_format={'type': 'json_object'},
            messages=[
                {'role': 'system', 'content': NER_SYSTEM},
                {'role': 'user', 'content': query}
            ],
            temperature=0.0,
            timeout=4.0
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f'NER error: {e}. Falling back to rule-based.')
        return _extract_entities_local(query)
