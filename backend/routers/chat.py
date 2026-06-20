"""
Chat router
-----------
Exposes two chat interfaces for authenticated doctors:

* REST endpoint   POST /api/chat          — single-shot query/response (non-streaming).
* WebSocket       WS   /api/chat/stream   — token-by-token streaming with optional
  chain-of-thought ('<think>' / MedGemma style) display.

Both modes support a ``'patient'`` mode (full RAG pipeline with patient records)
and a ``'general'`` mode (open-ended medical Q&A without patient context).
Access is restricted to the ``doctor`` role via the require_role dependency.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db, SessionLocal
from ..auth import get_current_doctor, require_role
from ..services.intent import classify_intent
from ..services.ner import extract_entities
from ..services.retriever import retrieve
from ..services.llm import generate_answer, generate_general
from .. import models, schemas
import json
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor

router = APIRouter(prefix='/api', tags=['chat'])

# Thread pool for running synchronous Ollama generators without blocking the event loop
_executor = ThreadPoolExecutor(max_workers=4)


async def _iter_generator_async(generator):
    """
    Wraps a synchronous generator in an async generator by running it in a
    background thread. This prevents the Ollama streaming loop from blocking
    FastAPI's event loop and allows WebSocket sends to be dispatched in real-time.
    """
    loop = asyncio.get_event_loop()
    queue = asyncio.Queue()
    _SENTINEL = object()

    def _run():
        try:
            for token in generator:
                loop.call_soon_threadsafe(queue.put_nowait, token)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

    loop.run_in_executor(_executor, _run)

    while True:
        item = await queue.get()
        if item is _SENTINEL:
            break
        yield item


# ── Helper: stream parser for <think> tags ────────────────────────────────────
async def stream_with_thinking(websocket: WebSocket, generator):
    """
    Reads tokens from a generator and splits them into think/answer channels.
    Handles standard <think> tags, MedGemma's native 'thought ...' prefix,
    and MedGemma 1.5's <unused94> thought start and <unused95> thought end tokens.
    """
    in_think       = False
    format_decided = False   # have we committed to think-mode or answer-mode?
    think_buf      = ""
    answer_buf     = ""
    raw_buffer     = ""
    think_start    = None

    async for token in _iter_generator_async(generator):
        raw_buffer += token

        # ── Phase 1: hold initial buffer until format is decided ──────────────
        if not format_decided and not in_think:
            stripped = raw_buffer.lstrip()

            # If it starts with <unused94>, enter think-mode immediately
            if stripped.lower().startswith("<unused94>"):
                in_think = True
                format_decided = True
                think_start = time.time()
                await websocket.send_json({"type": "think_start"})
                remainder = stripped[len("<unused94>"):]
                if remainder.lower().startswith("thought"):
                    remainder = remainder[len("thought"):]
                remainder = remainder.lstrip(": \n\r")
                if remainder:
                    think_buf += remainder
                    await websocket.send_json({"type": "think", "chunk": remainder})
                raw_buffer = ""
                continue

            # If it looks like it's starting to say "<unused94>", hold it
            if stripped.lower().startswith("<unused94>"[:len(stripped)]):
                if len(stripped) < len("<unused94>"):
                    continue

            # If it looks like it's starting to say "thought", hold it
            if stripped.lower().startswith("thought"[:len(stripped)]):
                if len(stripped) < 7:
                    continue  # Keep buffering to make sure we get the full word "thought"
            
            # Decision point
            format_decided = True

            # Robust case-insensitive check for "thought"
            if stripped.lower().startswith("thought"):
                # Strip the "thought" prefix and any trailing punctuation (like :), spaces, or newlines
                remainder = stripped[7:]
                # Remove optional colons, spaces, newlines immediately after "thought"
                remainder = remainder.lstrip(": \n\r")
                
                in_think    = True
                think_start = time.time()
                await websocket.send_json({"type": "think_start"})
                if remainder:
                    think_buf += remainder
                    await websocket.send_json({"type": "think", "chunk": remainder})
                raw_buffer = ""
                continue
            # else: regular response — fall through to normal processing below

        # ── Open <think> tag ──────────────────────────────────────────────────
        if not in_think and "<think>" in raw_buffer:
            before, raw_buffer = raw_buffer.split("<think>", 1)
            if before:
                answer_buf += before
                await websocket.send_json({"type": "chunk", "chunk": before, "done": False})
            in_think    = True
            think_start = time.time()
            format_decided = True
            await websocket.send_json({"type": "think_start"})
            continue

        # ── Close tag (</think> or MedGemma's <unused95> separator) ──────────
        close_tag = None
        if in_think and "</think>" in raw_buffer:
            close_tag = "</think>"
        elif in_think and "<unused95>" in raw_buffer:
            close_tag = "<unused95>"

        if close_tag:
            think_chunk, raw_buffer = raw_buffer.split(close_tag, 1)
            if think_chunk:
                think_buf += think_chunk
                await websocket.send_json({"type": "think", "chunk": think_chunk})
            duration = round(time.time() - think_start, 1) if think_start else 0
            await websocket.send_json({"type": "think_done", "duration": duration})
            in_think = False
            if raw_buffer:
                answer_buf += raw_buffer
                await websocket.send_json({"type": "chunk", "chunk": raw_buffer, "done": False})
                raw_buffer = ""
            continue

        # ── Partial tag buffering ─────────────────────────────────────────────
        if "<" in raw_buffer:
            is_close_tag_prefix = False
            for tag in ["</think>", "<unused95>"]:
                if tag.startswith(raw_buffer):
                    is_close_tag_prefix = True
                    break
            if is_close_tag_prefix:
                continue

        # ── Normal streaming ──────────────────────────────────────────────────
        if in_think:
            think_buf  += raw_buffer
            await websocket.send_json({"type": "think", "chunk": raw_buffer})
        else:
            answer_buf += raw_buffer
            await websocket.send_json({"type": "chunk", "chunk": raw_buffer, "done": False})
        raw_buffer = ""


    # Flush any remaining buffer
    if raw_buffer:
        if in_think:
            think_buf += raw_buffer
            await websocket.send_json({"type": "think", "chunk": raw_buffer})
        else:
            answer_buf += raw_buffer
            await websocket.send_json({"type": "chunk", "chunk": raw_buffer, "done": False})

    # Catch cases where model hit max_tokens before closing </think>
    if in_think:
        duration = round(time.time() - think_start, 1) if think_start else 0
        await websocket.send_json({"type": "think_done", "duration": duration})

    return answer_buf, think_buf



# ── REST endpoint (non-streaming, for compatibility) ──────────────────────────
@router.post('/chat', response_model=schemas.ChatResponse)
def chat_rest(request: schemas.ChatRequest,
              db: Session = Depends(get_db),
              doctor=Depends(require_role("doctor"))):
    """
    Non-streaming (REST) chat endpoint for doctor–patient queries.

    Runs the full pipeline synchronously:
      1. Classify intent via the NER / intent service.
      2. Extract medical entities from the query.
      3. Retrieve relevant patient records from the database.
      4. Generate a response using the LLM with the retrieved context.

    The conversation turn is persisted to ``ChatLog`` after generation.
    Returns the complete answer, detected intent, and source references.
    """
    patient = db.query(models.Patient).filter(models.Patient.id == request.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail='Patient not found')
    
    # Verify assignment
    assigned = db.query(models.PatientAssignment).filter(
        models.PatientAssignment.patient_id == request.patient_id,
        models.PatientAssignment.user_id == doctor.id
    ).first()
    if not assigned:
        raise HTTPException(status_code=403, detail='Access Denied: Patient is not assigned to you')

    intent_result = classify_intent(request.query)
    intent        = intent_result['intent']
    entities      = extract_entities(request.query)
    records, sources = retrieve(request.patient_id, intent, entities, db)
    full_answer = ''.join(generate_answer(request.query, intent, records, patient))
    db.add(models.ChatLog(
        doctor_id=doctor.id,
        patient_id=request.patient_id,
        query=request.query,
        response=full_answer,
        intent_detected=intent
    ))
    db.commit()
    return {'answer': full_answer, 'intent': intent, 'sources': sources}


# ── WebSocket (streaming) ─────────────────────────────────────────────────────
@router.websocket('/chat/stream')
async def chat_websocket(websocket: WebSocket):
    """
    Streaming WebSocket chat endpoint for authenticated doctors.

    Authentication is performed via a ``?token=<jwt>`` query parameter
    because WebSocket clients cannot send custom HTTP headers easily.

    Message protocol (client → server):
      - ``{"type": "stop"}``                   — abort the current generation.
      - ``{"query": str, "patient_id": int}``  — patient-context query (full RAG).
      - ``{"query": str, "mode": "general"}``  — general medical Q&A (no patient).

    Message protocol (server → client):
      - ``{"type": "status", "step": str, "status": "active"|"done"}``
      - ``{"type": "think_start"}`` / ``{"type": "think", "chunk": str}`` / ``{"type": "think_done", "duration": float}``
      - ``{"type": "chunk", "chunk": str, "done": false}``
      - ``{"type": "done", ...}``
      - ``{"error": str}`` on validation or auth failure.
    """
    # Get token from query parameters
    token = websocket.query_params.get("token")
    if not token:
        await websocket.accept()
        await websocket.send_json({'error': 'Missing token query parameter'})
        await websocket.close(code=4001)
        return

    db = SessionLocal()
    try:
        from ..auth import get_current_user_from_token
        user = get_current_user_from_token(token, db)
    except Exception:
        await websocket.accept()
        await websocket.send_json({'error': 'Invalid or expired token'})
        await websocket.close(code=4001)
        db.close()
        return

    if user.role.value != "doctor":
        await websocket.accept()
        await websocket.send_json({'error': 'Access Denied: Chat is only available for doctors'})
        await websocket.close(code=4003)
        db.close()
        return

    await websocket.accept()
    stop_flag = {"stop": False}

    try:
        while True:
            raw  = await websocket.receive_text()
            data = json.loads(raw)

            # Stop signal from frontend
            if data.get("type") == "stop":
                stop_flag["stop"] = True
                continue

            stop_flag["stop"] = False
            query      = data.get('query', '')
            patient_id = data.get('patient_id')
            mode       = data.get('mode', 'patient')   # 'patient' | 'general'

            if not query:
                await websocket.send_json({'error': 'query is required'})
                continue

            # ── General mode — no patient context ─────────────────────────────
            if mode == 'general':
                await websocket.send_json({"type": "status", "step": "intent", "status": "active"})
                await asyncio.sleep(0.1)
                await websocket.send_json({"type": "status", "step": "intent", "status": "done"})

                await websocket.send_json({"type": "status", "step": "llm", "status": "active"})
                answer_buf, _ = await stream_with_thinking(
                    websocket, generate_general(query)
                )
                await websocket.send_json({
                    'type': 'done',
                    'chunk': '',
                    'done': True,
                    'intent': 'general_medical_qa',
                    'sources': []
                })
                db.add(models.ChatLog(
                    doctor_id=user.id,
                    query=query,
                    response=answer_buf,
                    intent_detected='general_medical_qa'
                ))
                db.commit()
                continue

            # ── Patient mode — full pipeline ──────────────────────────────────
            if not patient_id:
                await websocket.send_json({'error': 'patient_id required in patient mode'})
                continue

            patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
            if not patient:
                await websocket.send_json({'error': 'Patient not found'})
                continue

            # Verify assignment
            assigned = db.query(models.PatientAssignment).filter(
                models.PatientAssignment.patient_id == patient_id,
                models.PatientAssignment.user_id == user.id
            ).first()
            if not assigned:
                await websocket.send_json({'error': 'Access Denied: Patient is not assigned to you'})
                continue

            await websocket.send_json({"type": "status", "step": "intent", "status": "active"})
            intent_result    = classify_intent(query)
            intent           = intent_result['intent']
            await websocket.send_json({"type": "status", "step": "intent", "status": "done"})

            await websocket.send_json({"type": "status", "step": "ner", "status": "active"})
            entities         = extract_entities(query)
            await websocket.send_json({"type": "status", "step": "ner", "status": "done"})

            await websocket.send_json({"type": "status", "step": "retrieval", "status": "active"})
            records, sources = retrieve(patient_id, intent, entities, db)
            await websocket.send_json({"type": "status", "step": "retrieval", "status": "done"})

            await websocket.send_json({"type": "status", "step": "llm", "status": "active"})
            answer_buf, _ = await stream_with_thinking(
                websocket, generate_answer(query, intent, records, patient)
            )

            await websocket.send_json({
                'type': 'done',
                'chunk': '',
                'done': True,
                'intent': intent,
                'sources': sources
            })

            db.add(models.ChatLog(
                doctor_id=user.id,
                patient_id=patient_id,
                query=query,
                response=answer_buf,
                intent_detected=intent
            ))
            db.commit()

    except WebSocketDisconnect:
        print('Doctor disconnected from WebSocket')
    except Exception as e:
        print(f'WebSocket error: {e}')
        try:
            await websocket.send_json({'error': str(e)})
        except Exception:
            pass
    finally:
        db.close()
