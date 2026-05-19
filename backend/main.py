from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import engine, Base
from . import models
from .routers import auth, patients, chat, uploads

# Create all DB tables if they don't exist yet
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title='Medical History Chatbot API',
    description='AI-powered patient history retrieval for doctors',
    version='2.0.0'
)

# CORS: allow the frontend to call the backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# Register all routers
app.include_router(auth.router)
app.include_router(patients.router)
app.include_router(chat.router)
app.include_router(uploads.router)

@app.get('/')
def root():
    return {'message': 'Medical Chatbot API is running', 'docs': '/docs'}
