# 05 — AI Pipeline

## 5.1 Overview

The AI pipeline processes every chat message through four sequential stages. Each stage uses structured LLM output (JSON mode) or rule-based SQL query building to ensure determinism and accuracy.

```
Doctor Query
     │
     ▼
┌────────────┐
│   STAGE 1  │  Intent Classification
│ intent.py  │  → Determines WHAT the doctor is asking
└─────┬──────┘  → 8 possible intents
      │
      ▼
┌────────────┐
│   STAGE 2  │  Named Entity Recognition (NER)
│   ner.py   │  → Extracts structured information FROM the query
└─────┬──────┘  → 5 entity types
      │
      ▼
┌────────────┐
│   STAGE 3  │  Database Retrieval
│retriever.py│  → Queries PostgreSQL based on intent + entities
└─────┬──────┘  → Returns relevant records + source citations
      │
      ▼
┌────────────┐
│   STAGE 4  │  LLM Answer Generation (MedGemma 1.5)
│   llm.py   │  → Formats records + generates grounded response
└─────┬──────┘  → Wraps reasoning in <think> tags
      │
      ▼
  Answer to Doctor (via WebSocket streaming with think-parser)
```

**Alternative Flows:**
- **General Medical Mode:** Bypasses Stages 1-3. Doctor query goes straight to Stage 4 using a general medical system prompt.
- **Image Upload:** Bypasses WebSocket. Uses a standard HTTP POST with SSE (Server-Sent Events) streaming to process base64 multi-modal images alongside a text query.

---

## 5.2 Stage 1 — Intent Classification

**File:** `backend/services/intent.py`

### Supported Intents

| Intent | Description | Example Query |
|--------|-------------|---------------|
| `history_lookup` | General medical history | "What is the patient's medical background?" |
| `medication_check` | Current prescriptions | "What drugs is this patient on?" |
| `lab_results` | Laboratory test values | "Show me the last HbA1c result" |
| `allergy_check` | Known allergies | "Is this patient allergic to penicillin?" |
| `visit_summary` | Past clinical encounters | "What happened in the last 3 visits?" |
| `diagnosis_check` | Active/past diagnoses | "Does this patient have diabetes?" |
| `risk_flag` | Abnormal findings/risk | "Are there any concerning findings?" |
| `general_question` | General clinical knowledge | "What's the normal range for HbA1c?" |

### Implementation

```python
# System prompt enforces JSON output with only valid intent values
SYSTEM_PROMPT = """
You are a medical intent classifier. Given a doctor's query, return a JSON object with:
- intent: one of: history_lookup, medication_check, lab_results,
  allergy_check, visit_summary, diagnosis_check, risk_flag, general_question
- confidence: a float between 0 and 1
Return ONLY valid JSON.
"""

# Response format: { "intent": "lab_results", "confidence": 0.97 }
```

**Model configuration:**
- Ollama backend (default): `medgemma1.5:latest`
- OpenAI backend (legacy): `gpt-4o-mini`
- Temperature: `0.0` (deterministic)
- Response format: `json_object`

**Fallback behavior:** If the LLM returns an invalid intent string, the system defaults to `history_lookup`.

---

## 5.3 Stage 2 — Named Entity Recognition (NER)

**File:** `backend/services/ner.py`

### Extracted Entity Types

| Entity | Description | Example |
|--------|-------------|---------|
| `date_range` | Temporal scope | "last 3 months", "2024", "this year" |
| `condition` | Medical condition | "diabetes", "hypertension" |
| `drug` | Medication name | "metformin", "aspirin" |
| `lab_test` | Laboratory test name | "HbA1c", "creatinine" |
| `limit` | Numeric limit | 3 (from "last 3 visits") |

### Implementation

```python
NER_SYSTEM = """
You are a medical named entity extractor. Extract entities from the doctor query.
Return ONLY a JSON object with these fields (use null if not mentioned):
{
  "date_range": null or string like 'last 3 months' or '2024',
  "condition": null or string e.g. 'diabetes',
  "drug": null or string e.g. 'metformin',
  "lab_test": null or string e.g. 'HbA1c',
  "limit": null or integer e.g. 3 (when doctor says 'last 3 visits')
}
Return ONLY valid JSON.
"""
```

**Example:**
- Input: `"Show me HbA1c results from the last 3 months"`
- Output: `{"date_range": "last 3 months", "condition": null, "drug": null, "lab_test": "HbA1c", "limit": null}`

---

## 5.4 Stage 3 — Database Retrieval

**File:** `backend/services/retriever.py`

The retriever maps each intent to one or more database queries, applying entity-based filters dynamically.

### Retrieval Strategy by Intent

| Intent | Table(s) Queried | Filters Applied |
|--------|-----------------|-----------------|
| `medication_check` | `medications` | drug name (ilike), is_active=True |
| `lab_results` | `lab_results` | test_name (ilike), test_date >= cutoff, LIMIT |
| `allergy_check` | `allergies` | patient_id only |
| `visit_summary` | `visits` | visit_date >= cutoff, LIMIT |
| `diagnosis_check` | `diagnoses` | description (ilike condition) |
| `history_lookup` | diagnoses + medications + lab_results + allergies | Combined |
| `risk_flag` | diagnoses + medications + lab_results + allergies | Combined |
| `general_question` | *(no DB query)* | Returns empty list |

### Date Range Parsing

The `_parse_date_range()` function converts natural language temporal expressions to a cutoff `date`:

```
"last 3 months"  → today - 90 days
"last 2 years"   → today - 730 days
"last week"      → today - 7 days
"2024"           → (no cutoff applied - year handling TBD)
```

### Output Format

```python
# Returns tuple: (records, sources)
records = [<SQLAlchemy ORM objects>]
sources = ["Lab #12: HbA1c = 8.1 % on 2025-11-20", ...]
```

---

## 5.5 Stage 4 — LLM Answer Generation

**File:** `backend/services/llm.py`

### System Prompt (Strict Grounding)

### System Prompt (Patient Grounding)

```
You are a clinical assistant AI helping a doctor review patient medical history.
Before answering, write your step-by-step reasoning inside <think>...</think> tags. Then give your final answer.

STRICT RULES:
1. Answer ONLY from the patient data provided below. Do not use outside knowledge.
2. Always cite which record your answer comes from (e.g. 'According to Lab #3...')
3. If the data does not contain the answer, say exactly: 'The records do not contain this information.'
4. Be concise and clinically precise. Use bullet points for lists.
5. Never make medical recommendations. You are presenting records only.
6. If you see abnormal lab values or dangerous drug combinations, flag them clearly.
```

### Record Formatting

Before calling the LLM, patient data is formatted into a structured text block:

```
Patient: Ahmad Hassan, DOB: 1978-04-12, Gender: Male, Blood Type: O+

--- DIAGNOSES ---
  [5] Type 2 Diabetes Mellitus (E11) | Severity: moderate | Active: True

--- ACTIVE MEDICATIONS ---
  [3] Metformin 500mg | Since: 2023-01-10

--- RECENT LABS ---
  [12] HbA1c: 8.1 % (ref: 4.0-5.6) on 2025-11-20 ⚠ ABNORMAL

--- ALLERGIES ---
  [2] Penicillin → Anaphylaxis (severe)
```

### Streaming & Reasoning Parser

The LLM response is streamed token-by-token. To support MedGemma 1.5's native clinical reasoning model output alongside standard instruction-tuned reasoning models (like DeepSeek R1), the backend implements an advanced stateful stream parser (`stream_with_thinking`) in the WebSocket router (`chat.py`) and equivalent logic in the multi-modal endpoint (`uploads.py`). 

This parser dynamically filters the token stream and separates reasoning from the final answer by supporting three distinct token/text styles:

1. **MedGemma 1.5 Special Tokens:**
   - **Start of Thought:** The `<unused94>` token (which MedGemma 1.5 prefixes to its thinking process). When detected, the parser initiates a `think_start` event.
   - **End of Thought:** The `<unused95>` token (which separates the reasoning block from the final clinical answer). When detected, the parser broadcasts a `think_done` event (with exact thinking duration in seconds) and routes subsequent tokens to the standard final answer channel.
2. **Standard XML-style Tags:**
   - Triggers `think_start` when `<think>` is received.
   - Triggers `think_done` when `</think>` is received.
3. **Text-based thought prefixes:**
   - Triggers `think_start` when the response starts with the case-insensitive keyword `thought ` (common in models that formulate their reasoning in paragraphs).

#### Robust Buffering and Prefix Handling
To prevent tag fragmentation (where brackets like `<` or incomplete tags like `<un` are split across multiple tokens and escape detection), the stream parser holds partial characters in a temporary buffer. If the buffer is a prefix of one of the close tags (`</think>`, `<unused95>`, etc.) or starting tokens (`<unused94>`, `thought`), it continues buffering. As soon as a match or mismatch is confirmed, it either fires the control events or flushes the buffer to the active stream channel.

**Model configuration:**
- Ollama backend (default): `medgemma1.5:latest`
- OpenAI backend (legacy): `gpt-4o`
- Temperature: `0.2` (slight variation but mostly deterministic)
- Max tokens: `1024`

---

## 5.6 Multi-Modal Image Analysis

**File:** `backend/routers/uploads.py`

MedGemma 1.5 supports vision. The `/api/chat/analyze-image` endpoint accepts `multipart/form-data` containing an image and a specific prompt category (`xray`, `ct_mri`, `lab_report`, `handwritten`, `dermatology`, `general`).
The image is base64-encoded and sent to Ollama's OpenAI-compatible multi-modal API. The response is streamed back using **Server-Sent Events (SSE)**, which employs the exact same `<think>` parsing logic as the WebSocket connection.

---

## 5.6 LLM Backend Configuration

The same OpenAI client SDK is used for both backends. Ollama exposes an OpenAI-compatible endpoint.

```bash
# .env configuration
LLM_BACKEND=ollama       # or: openai
OLLAMA_MODEL=medgemma1.5:latest    # model name in Ollama
OPENAI_API_KEY=sk-...    # only needed for openai backend
```

**Ollama setup:**
```bash
ollama pull llama3.2
ollama serve   # starts on http://localhost:11434
```

| Property | OpenAI | Ollama |
|----------|--------|--------|
| Cost | Per-token billing | Free (local compute) |
| Privacy | Data sent to cloud | 100% local |
| Speed | ~0.5s first token | Depends on hardware |
| Quality | Higher (GPT-4o) | Good (Llama 3.2) |
| Internet required | Yes | No |

---

## 5.7 Pipeline Limitations and Known Issues

| Issue | Description | Mitigation |
|-------|-------------|------------|
| NER ambiguity | "last labs" → limit or date_range? | LLM resolves via context |
| Intent overlap | "diabetes meds" → medication_check or diagnosis_check? | Retriever fetches both for `history_lookup` |
| Date range "2024" | Year-only references not parsed to cutoff | Returns all records (no filter applied) |
| Ollama latency | First-token latency high on CPU-only machines | GPU acceleration recommended |
| No conversation memory | Each query is stateless (no chat history) | Planned future improvement |

---

*Next: [Frontend Guide →](06_frontend_guide.md)*
