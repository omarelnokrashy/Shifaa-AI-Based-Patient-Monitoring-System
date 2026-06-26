"""
main.py — FastAPI application entry point
==========================================
Initialises the FastAPI app, applies CORS middleware, and registers all
application routers (auth, patients, chat, uploads, users, arrhythmia,
monitoring, and dashboard).  Database tables are created automatically on
startup via SQLAlchemy's ``create_all``.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
from .database import engine, Base
from . import models
from .routers import auth, patients, chat, uploads, users, arrhythmia, monitoring, dashboard, rooms

# Create all DB tables if they don't exist yet (safe no-op if already present)
Base.metadata.create_all(bind=engine)

# Ensure uploads directory exists
os.makedirs("uploads", exist_ok=True)

app = FastAPI(
    title="Medical Monitoring System API",
    description=(
        "AI-powered patient history chatbot with real-time monitoring: "
        "arrhythmia detection, fall detection, and seizure detection."
    ),
    version="3.0.0",
)

# Serve uploads statically
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# CORS: allow the frontend and inference services to call the backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Existing routers (unchanged) ──────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(patients.router)
app.include_router(chat.router)
app.include_router(uploads.router)

# ── New routers ───────────────────────────────────────────────────────────────
app.include_router(users.router)          # POST/GET/PATCH /api/admin/users
app.include_router(arrhythmia.router)     # POST /api/arrhythmia/analyze
app.include_router(monitoring.router)     # POST/DELETE /api/monitoring/*, WS /api/ws/*
app.include_router(dashboard.router)      # GET /api/dashboard/summary
app.include_router(rooms.router)          # POST/PUT/DELETE/GET /api/rooms/*


@app.get("/")
def root():
    """Return a brief status message confirming the API is running."""
    return {
        "message": "Medical Monitoring System API is running",
        "docs": "/docs",
        "version": "3.0.0",
    }


@app.get("/api/health")
def health():
    """Quick health check for load balancers / uptime monitors."""
    return {"status": "ok"}


@app.on_event("startup")
async def startup_event():
    import asyncio
    from backend.services.alert_manager import alert_manager
    asyncio.create_task(alert_manager.clean_expired_alerts_loop())
