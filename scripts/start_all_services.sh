#!/usr/bin/env bash
# =============================================================================
# start_all_services.sh — Unified Medical Monitoring System launcher for Linux
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/runtime/logs"

mkdir -p "$LOG_DIR/arrhythmia" "$LOG_DIR/fall" "$LOG_DIR/seizure" "$LOG_DIR/backend"

# ── Load environment variables ────────────────────────────────────────────────
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC2046
    source <(grep -v '^\s*#' "$PROJECT_ROOT/.env" | grep -v '^\s*$')
    set +a
    echo "[✓] Loaded .env"
else
    echo "[!] WARNING: .env not found. Using defaults from environment."
fi

# ── Helper to pick the right Python interpreter ───────────────────────────────
CONDA_PYTHON="/home/omar/anaconda3/envs/gp/bin/python3"
if [[ ! -x "$CONDA_PYTHON" ]]; then
    CONDA_PYTHON="$(command -v python3 || echo python3)"
fi

python_for() {
    local repo_dir="$1"
    local venv_py="$repo_dir/.venv/bin/python"
    if [[ -x "$venv_py" ]]; then
        echo "$venv_py"
    else
        echo "$CONDA_PYTHON"
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
ARR_DIR="$PROJECT_ROOT/services/arrhythmia"
ARR_PY="$(python_for "$ARR_DIR")"
echo "[1/4] Starting arrhythmia service on port $ARR_PORT ..."
PORT=$ARR_PORT "$ARR_PY" -m uvicorn service:app \
    --app-dir "$ARR_DIR" \
    --host 0.0.0.0 \
    --port "$ARR_PORT" \
    --no-access-log \
    > "$LOG_DIR/arrhythmia/arrhythmia.log" 2>&1 &
ARR_PID=$!
echo "      PID=$ARR_PID  log=$LOG_DIR/arrhythmia/arrhythmia.log"

# ── 2. Fall detection service ─────────────────────────────────────────────────
FALL_DIR="$PROJECT_ROOT/services/fall_detection"
FALL_PY="$(python_for "$FALL_DIR")"
echo "[2/4] Starting fall detection service on port $FALL_PORT ..."
PORT=$FALL_PORT "$FALL_PY" -m uvicorn service:app \
    --app-dir "$FALL_DIR" \
    --host 0.0.0.0 \
    --port "$FALL_PORT" \
    --no-access-log \
    > "$LOG_DIR/fall/fall.log" 2>&1 &
FALL_PID=$!
echo "      PID=$FALL_PID  log=$LOG_DIR/fall/fall.log"

# ── 3. Seizure detection service ──────────────────────────────────────────────
SEIZ_DIR="$PROJECT_ROOT/services/seizure_detection"
SEIZ_PY="$(python_for "$SEIZ_DIR")"
echo "[3/4] Starting seizure detection service on port $SEIZ_PORT ..."
PORT=$SEIZ_PORT "$SEIZ_PY" -m uvicorn service:app \
    --app-dir "$SEIZ_DIR" \
    --host 0.0.0.0 \
    --port "$SEIZ_PORT" \
    --no-access-log \
    > "$LOG_DIR/seizure/seizure.log" 2>&1 &
SEIZ_PID=$!
echo "      PID=$SEIZ_PID  log=$LOG_DIR/seizure/seizure.log"

# ── 4. Main FastAPI backend ───────────────────────────────────────────────────
echo "[4/4] Starting main backend on port $MAIN_PORT ..."
cd "$PROJECT_ROOT"
"$CONDA_PYTHON" -m uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port "$MAIN_PORT" \
    --reload \
    > "$LOG_DIR/backend/backend.log" 2>&1 &
MAIN_PID=$!
echo "      PID=$MAIN_PID  log=$LOG_DIR/backend/backend.log"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  All services started.  Press Ctrl+C to stop all.        ║"
echo "║                                                          ║"
echo "║  Main backend      →  http://localhost:$MAIN_PORT          ║"
echo "║  Arrhythmia svc    →  http://localhost:$ARR_PORT          ║"
echo "║  Fall detection    →  http://localhost:$FALL_PORT          ║"
echo "║  Seizure detection →  http://localhost:$SEIZ_PORT          ║"
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

wait
