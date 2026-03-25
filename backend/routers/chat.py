from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db, SessionLocal
from ..auth import get_current_doctor
from ..services.intent import classify_intent
from ..services.ner import extract_entities
from ..services.retriever import retrieve
from ..services.llm import generate_answer
from .. import models, schemas
import json

router = APIRouter(prefix='/api', tags=['chat'])

@router.post('/chat', response_model=schemas.ChatResponse)
def chat_rest(request: schemas.ChatRequest,
              db: Session = Depends(get_db),
              doctor=Depends(get_current_doctor)):
    patient = db.query(models.Patient).filter(models.Patient.id == request.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail='Patient not found')
    intent_result = classify_intent(request.query)
    intent = intent_result['intent']
    entities = extract_entities(request.query)
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

@router.websocket('/ws/chat')
async def chat_websocket(websocket: WebSocket):
    await websocket.accept()
    db = SessionLocal()
    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            query      = data.get('query', '')
            patient_id = data.get('patient_id')
            token      = data.get('token', '')
            if not query or not patient_id:
                await websocket.send_json({'error': 'query and patient_id required'})
                continue
            patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
            if not patient:
                await websocket.send_json({'error': 'Patient not found'})
                continue
            intent_result = classify_intent(query)
            intent        = intent_result['intent']
            entities      = extract_entities(query)
            records, sources = retrieve(patient_id, intent, entities, db)
            full_response = ''
            for chunk in generate_answer(query, intent, records, patient):
                full_response += chunk
                await websocket.send_json({'chunk': chunk, 'done': False})
            await websocket.send_json({
                'chunk': '',
                'done': True,
                'intent': intent,
                'sources': sources
            })
            db.add(models.ChatLog(
                patient_id=patient_id,
                query=query,
                response=full_response,
                intent_detected=intent
            ))
            db.commit()
    except WebSocketDisconnect:
        print('Doctor disconnected from WebSocket')
    except Exception as e:
        print(f'WebSocket error: {e}')
        await websocket.send_json({'error': str(e)})
    finally:
        db.close()
