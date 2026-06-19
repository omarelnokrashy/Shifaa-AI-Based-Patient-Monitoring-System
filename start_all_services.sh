#!/usr/bin/env bash
# =============================================================================
# start_all_services.sh — Unified Medical Monitoring System launcher
# =============================================================================
#
# Starts all four processes in the background with separate log files, then
# waits so Ctrl+C kills them all cleanly.
#
# Usage:
#   chmod +x start_all_services.sh
#   ./start_all_services.sh
#
# Prerequisites:
#   - .env file configured (copy from .env.example)
#   - Main conda env: conda activate medical_chatbot
#   - Each repo has its own venv at Repos/<name>/.venv/
#     If not created yet, run:
#       python -m venv Repos/Arrythmia-Detection-master/.venv
#       Repos/Arrythmia-Detection-master/.venv/bin/pip install -r Repos/Arrythmia-Detection-master/requirements.txt fastapi uvicorn httpx
#
#       python -m venv Repos/Patient-fall-detection-system-main/.venv
#       Repos/Patient-fall-detection-system-main/.venv/bin/pip install -r Repos/Patient-fall-detection-system-main/requirements.txt fastapi uvicorn websockets
#
#       python -m venv Repos/Seizure-Detection-main/.venv
#       Repos/Seizure-Detection-main/.venv/bin/pip install -r Repos/Seizure-Detection-main/requirements.txt fastapi uvicorn websockets
#
# =============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"

# ── Load environment variables ────────────────────────────────────────────────
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    # Export only key=value lines, skip comments
    set -a
    # shellcheck disable=SC2046
    source <(grep -v '^\s*#' "$PROJECT_ROOT/.env" | grep -v '^\s*$')
    set +a
    echo "[✓] Loaded .env"
else
    echo "[!] WARNING: .env not found. Using defaults from environment."
fi

# ── Helper to pick the right Python interpreter ───────────────────────────────
python_for() {
    local repo_dir="$1"
    local venv_py="$repo_dir/.venv/bin/python"
    if [[ -x "$venv_py" ]]; then
        echo "$venv_py"
    else
        echo "python3"
        echo "[!] WARNING: No venv found at $repo_dir/.venv — using system python3" >&2
    fi
}

# ── Ports (can be overridden in .env) ────────────────────────────────────────
MAIN_PORT="${MAIN_PORT:-8000}"
ARR_PORT="${ARRHYTHMIA_PORT:-8001}"
FALL_PORT="${FALL_DETECTION_PORT:-8002}"
SEIZ_PORT="${SEIZURE_DETECTION_PORT:-8003}"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║       Medical Monitoring System — Starting services       ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── 1. Arrhythmia service ─────────────────────────────────────────────────────
ARR_DIR="$PROJECT_ROOT/Repos/Arrythmia-Detection-master"
ARR_PY="$(python_for "$ARR_DIR")"
echo "[1/4] Starting arrhythmia service on port $ARR_PORT ..."
PORT=$ARR_PORT "$ARR_PY" -m uvicorn service:app \
    --app-dir "$ARR_DIR" \
    --host 0.0.0.0 \
    --port "$ARR_PORT" \
    --no-access-log \
    > "$LOG_DIR/arrhythmia.log" 2>&1 &
ARR_PID=$!
echo "      PID=$ARR_PID  log=$LOG_DIR/arrhythmia.log"

# ── 2. Fall detection service ─────────────────────────────────────────────────
FALL_DIR="$PROJECT_ROOT/Repos/Patient-fall-detection-system-main"
FALL_PY="$(python_for "$FALL_DIR")"
echo "[2/4] Starting fall detection service on port $FALL_PORT ..."
PORT=$FALL_PORT "$FALL_PY" -m uvicorn service:app \
    --app-dir "$FALL_DIR" \
    --host 0.0.0.0 \
    --port "$FALL_PORT" \
    --no-access-log \
    > "$LOG_DIR/fall_detection.log" 2>&1 &
FALL_PID=$!
echo "      PID=$FALL_PID  log=$LOG_DIR/fall_detection.log"

# ── 3. Seizure detection service ──────────────────────────────────────────────
SEIZ_DIR="$PROJECT_ROOT/Repos/Seizure-Detection-main"
SEIZ_PY="$(python_for "$SEIZ_DIR")"
echo "[3/4] Starting seizure detection service on port $SEIZ_PORT ..."
PORT=$SEIZ_PORT "$SEIZ_PY" -m uvicorn service:app \
    --app-dir "$SEIZ_DIR" \
    --host 0.0.0.0 \
    --port "$SEIZ_PORT" \
    --no-access-log \
    > "$LOG_DIR/seizure_detection.log" 2>&1 &
SEIZ_PID=$!
echo "      PID=$SEIZ_PID  log=$LOG_DIR/seizure_detection.log"

# ── 4. Main FastAPI backend ───────────────────────────────────────────────────
echo "[4/4] Starting main backend on port $MAIN_PORT ..."
cd "$PROJECT_ROOT"
python3 -m uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port "$MAIN_PORT" \
    --reload \
    > "$LOG_DIR/main_backend.log" 2>&1 &
MAIN_PID=$!
echo "      PID=$MAIN_PID  log=$LOG_DIR/main_backend.log"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  All services started.  Press Ctrl+C to stop all.        ║"
echo "║                                                          ║"
printf  "║  Main backend      →  http://localhost:%-5s           ║\n" "$MAIN_PORT"
printf  "║  Arrhythmia svc    →  http://localhost:%-5s           ║\n" "$ARR_PORT"
printf  "║  Fall detection    →  http://localhost:%-5s           ║\n" "$FALL_PORT"
printf  "║  Seizure detection →  http://localhost:%-5s           ║\n" "$SEIZ_PORT"
echo "║                                                          ║"
echo "║  Swagger UI  →  http://localhost:$MAIN_PORT/docs         ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Cleanup on Ctrl+C ────────────────────────────────────────────────────────
cleanup() {
    echo ""
    echo "Stopping all services..."
    kill "$ARR_PID"  2>/dev/null || true
    kill "$FALL_PID" 2>/dev/null || true
    kill "$SEIZ_PID" 2>/dev/null || true
    kill "$MAIN_PID" 2>/dev/null || true
    wait
    echo "All services stopped."
}
trap cleanup SIGINT SIGTERM

# Wait forever (or until a child dies unexpectedly)
wait
