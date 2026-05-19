from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor

from ..database import get_db
from ..auth import get_current_doctor_from_token
from ..services.llm import generate_answer_with_image
from .. import models

router = APIRouter(prefix='/api/chat', tags=['image-analysis'])

_executor = ThreadPoolExecutor(max_workers=4)


async def _iter_sync_gen(generator):
    """Run a synchronous generator in a thread pool and yield tokens asynchronously."""
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


@router.post('/analyze-image')
async def analyze_image(
    image:      UploadFile = File(...),
    question:   str        = Form(default=""),
    image_type: str        = Form(default="general"),
    patient_id: Optional[int] = Form(default=None),
    token:      str        = Form(...),
    db: Session = Depends(get_db),
):
    """
    Accepts a medical image + question, streams MedGemma's analysis via SSE.
    Supported image_type values: xray, ct_mri, lab_report, handwritten, dermatology, general
    """
    # Validate token
    try:
        doctor = get_current_doctor_from_token(token, db)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Read image bytes
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty image file")

    # Load patient if provided
    patient = None
    if patient_id:
        patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()

    # Stream via SSE — uses async iteration to avoid blocking the event loop
    async def event_stream():
        try:
            in_think       = False
            format_decided = False
            answer_buf     = ""
            raw_buffer     = ""
            think_start    = None

            yield f"data: {json.dumps({'type': 'status', 'step': 'image', 'status': 'active'})}\n\n"

            async for token_text in _iter_sync_gen(
                generate_answer_with_image(question, image_bytes, image_type, patient)
            ):
                raw_buffer += token_text

                # ── Phase 1: hold initial buffer until format is decided ──────────────
                if not format_decided and not in_think:
                    stripped = raw_buffer.lstrip()

                    # If it starts with <unused94>, enter think-mode immediately
                    if stripped.lower().startswith("<unused94>"):
                        in_think = True
                        format_decided = True
                        think_start = time.time()
                        yield f"data: {json.dumps({'type': 'status', 'step': 'image', 'status': 'done'})}\n\n"
                        yield f"data: {json.dumps({'type': 'status', 'step': 'llm', 'status': 'active'})}\n\n"
                        yield f"data: {json.dumps({'type': 'think_start'})}\n\n"
                        remainder = stripped[len("<unused94>"):]
                        if remainder.lower().startswith("thought"):
                            remainder = remainder[len("thought"):]
                        remainder = remainder.lstrip(": \n\r")
                        if remainder:
                            yield f"data: {json.dumps({'type': 'think', 'chunk': remainder})}\n\n"
                        raw_buffer = ""
                        continue

                    # If it looks like it's starting to say "<unused94>", hold it
                    if stripped.lower().startswith("<unused94>"[:len(stripped)]):
                        if len(stripped) < len("<unused94>"):
                            continue

                    # If it looks like it's starting to say "thought", hold it
                    if stripped.lower().startswith("thought"[:len(stripped)]):
                        if len(stripped) < 7:
                            continue

                    format_decided = True
                    yield f"data: {json.dumps({'type': 'status', 'step': 'image', 'status': 'done'})}\n\n"
                    yield f"data: {json.dumps({'type': 'status', 'step': 'llm', 'status': 'active'})}\n\n"

                    # Robust case-insensitive check for "thought"
                    if stripped.lower().startswith("thought"):
                        remainder = stripped[7:]
                        remainder = remainder.lstrip(": \n\r")
                        in_think   = True
                        think_start = time.time()
                        yield f"data: {json.dumps({'type': 'think_start'})}\n\n"
                        if remainder:
                            yield f"data: {json.dumps({'type': 'think', 'chunk': remainder})}\n\n"
                        raw_buffer = ""
                        continue

                # ── Open <think> tag ──────────────────────────────────────────────────
                if not in_think and "<think>" in raw_buffer:
                    before, raw_buffer = raw_buffer.split("<think>", 1)
                    if before:
                        answer_buf += before
                        yield f"data: {json.dumps({'type': 'chunk', 'chunk': before, 'done': False})}\n\n"
                    in_think = True
                    format_decided = True
                    think_start = time.time()
                    yield f"data: {json.dumps({'type': 'status', 'step': 'image', 'status': 'done'})}\n\n"
                    yield f"data: {json.dumps({'type': 'status', 'step': 'llm', 'status': 'active'})}\n\n"
                    yield f"data: {json.dumps({'type': 'think_start'})}\n\n"
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
                        yield f"data: {json.dumps({'type': 'think', 'chunk': think_chunk})}\n\n"
                    duration = round(time.time() - think_start, 1) if think_start else 0
                    yield f"data: {json.dumps({'type': 'think_done', 'duration': duration})}\n\n"
                    in_think = False
                    if raw_buffer:
                        yield f"data: {json.dumps({'type': 'chunk', 'chunk': raw_buffer, 'done': False})}\n\n"
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
                    yield f"data: {json.dumps({'type': 'think', 'chunk': raw_buffer})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'chunk', 'chunk': raw_buffer, 'done': False})}\n\n"
                raw_buffer = ""

            # Flush remainder
            if raw_buffer:
                if in_think:
                    yield f"data: {json.dumps({'type': 'think', 'chunk': raw_buffer})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'chunk', 'chunk': raw_buffer, 'done': False})}\n\n"

            if in_think:
                duration = round(time.time() - think_start, 1) if think_start else 0
                yield f"data: {json.dumps({'type': 'think_done', 'duration': duration})}\n\n"

            yield f"data: {json.dumps({'type': 'done', 'chunk': '', 'done': True})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering if proxied
        }
    )
