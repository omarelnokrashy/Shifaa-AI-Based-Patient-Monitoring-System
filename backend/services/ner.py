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
            temperature=0.0
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f'NER error: {e}')
        return {'date_range': None, 'condition': None, 'drug': None, 'lab_test': None, 'limit': None}
