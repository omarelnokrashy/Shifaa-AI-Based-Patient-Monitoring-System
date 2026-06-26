#!/bin/bash
# ============================================================
# Run All Tests for the Medical History Chatbot
# ============================================================
# Usage:
#   chmod +x docs/tests/run_all_tests.sh
#   ./docs/tests/run_all_tests.sh
#
# Options (environment vars):
#   BASE_URL=http://localhost:8000   (default)
#   SKIP_LLM=1                      (skip tests that call LLM APIs)
# ============================================================

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
RESULTS_DIR="$PROJECT_ROOT/docs/tests/results"
REPORT_FILE="$RESULTS_DIR/benchmark_$TIMESTAMP.json"
LOG_FILE="$RESULTS_DIR/test_run_$TIMESTAMP.log"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║     MEDICAL CHATBOT — FULL TEST SUITE                    ║"
echo "║     $(date '+%Y-%m-%d %H:%M:%S')                                  ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Setup ──────────────────────────────────────────────────────────────────────

mkdir -p "$RESULTS_DIR"
cd "$PROJECT_ROOT"

echo "📁 Project root: $PROJECT_ROOT"
echo "📄 Log file:     $LOG_FILE"
echo "📊 Report file:  $REPORT_FILE"
echo ""

# Check conda environment
if [ "${CONDA_DEFAULT_ENV:-}" != "gp" ]; then
    echo "⚠️  Conda environment 'gp' not activated. Trying to activate..."
    if [ -f "/home/omar/anaconda3/etc/profile.d/conda.sh" ]; then
        source "/home/omar/anaconda3/etc/profile.d/conda.sh"
        conda activate gp
        echo "✅ Conda environment 'gp' activated."
    elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
        source "$HOME/anaconda3/etc/profile.d/conda.sh"
        conda activate gp
        echo "✅ Conda environment 'gp' activated."
    elif command -v conda >/dev/null 2>&1; then
        eval "$(conda shell.bash hook)"
        conda activate gp
        echo "✅ Conda environment 'gp' activated."
    else
        echo "❌ ERROR: Conda environment 'gp' is not active and conda could not be found."
        echo "   Please run: conda activate gp"
        exit 1
    fi
fi

# ── Install test dependencies ──────────────────────────────────────────────────

echo "📦 Installing test dependencies..."
pip install pytest httpx scikit-learn --quiet

# ── Run Tests ──────────────────────────────────────────────────────────────────

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

run_test_suite() {
    local suite_name="$1"
    local test_file="$2"
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  🧪 $suite_name"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    if python -m pytest "$test_file" -v --tb=short 2>&1 | tee -a "$LOG_FILE"; then
        echo "  ✅ $suite_name PASSED"
        ((PASS_COUNT++)) || true
    else
        echo "  ❌ $suite_name FAILED (check $LOG_FILE for details)"
        ((FAIL_COUNT++)) || true
    fi
}

# Unit tests (no LLM, no network) — always run
run_test_suite "Retriever Unit Tests" "docs/tests/test_retriever.py"

# API integration tests — require backend to be running
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🌐 Checking if backend is running at ${BASE_URL:-http://localhost:8000}..."
if curl -sf "${BASE_URL:-http://localhost:8000}/" > /dev/null 2>&1; then
    echo "  ✅ Backend is running"
    run_test_suite "API Integration Tests" "docs/tests/test_api.py"
else
    echo "  ⚠️  Backend is NOT running — skipping API tests"
    echo "     Start with: uvicorn backend.main:app --reload --port 8000"
    ((SKIP_COUNT++)) || true
fi

# LLM tests — only run if SKIP_LLM is not set
if [ -z "$SKIP_LLM" ]; then
    echo ""
    echo "  🤖 LLM Tests (set SKIP_LLM=1 to skip these)"
    run_test_suite "Intent Classification Tests" "docs/tests/test_intent.py"
    run_test_suite "NER Extraction Tests" "docs/tests/test_ner.py"
else
    echo ""
    echo "  ⏭️  LLM tests SKIPPED (SKIP_LLM=1)"
    ((SKIP_COUNT+=2)) || true
fi

# ── Run Benchmark ──────────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  📊 Running Pipeline Benchmark..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -n "$SKIP_LLM" ]; then
    python docs/tests/benchmark_pipeline.py --skip-llm --output "$REPORT_FILE" 2>&1 | tee -a "$LOG_FILE"
else
    python docs/tests/benchmark_pipeline.py --output "$REPORT_FILE" 2>&1 | tee -a "$LOG_FILE"
fi

# ── Summary ───────────────────────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                     TEST SUMMARY                         ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  ✅ Passed:  $PASS_COUNT suite(s)                                   ║"
echo "║  ❌ Failed:  $FAIL_COUNT suite(s)                                   ║"
echo "║  ⏭️  Skipped: $SKIP_COUNT suite(s)                                  ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Full log:   $LOG_FILE"
echo "║  Benchmark:  $REPORT_FILE"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

if [ "$FAIL_COUNT" -gt 0 ]; then
    exit 1
fi
exit 0
