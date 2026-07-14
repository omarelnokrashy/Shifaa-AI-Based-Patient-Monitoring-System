#!/usr/bin/env bash
# =============================================================================
# setup.sh — One-shot first-time setup for Shifaa (Linux / macOS)
# =============================================================================
# Usage:
#   bash scripts/setup.sh           # Full setup with GPU torch
#   bash scripts/setup.sh --cpu     # CPU-only torch (slower inference)
#   bash scripts/setup.sh --skip-vivit  # Skip ViViT download (air-gapped)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

CPU_ONLY=false
SKIP_VIVIT=false

for arg in "$@"; do
    case $arg in
        --cpu)       CPU_ONLY=true ;;
        --skip-vivit) SKIP_VIVIT=true ;;
    esac
done

step()  { echo ""; echo "▶ $*"; }
ok()    { echo "  ✓ $*"; }
warn()  { echo "  ⚠ $*"; }
fail()  { echo "  ✗ $*"; exit 1; }

echo ""
echo "============================================"
echo "  Shifaa — First-Time Setup (Linux/macOS)   "
echo "============================================"
echo ""

# ── Step 1: Verify Python ─────────────────────────────────────────────────────
step "Checking Python..."
PYTHON="$(command -v python3 || command -v python || true)"
[[ -z "$PYTHON" ]] && fail "Python 3.10+ not found. Activate your conda env first."
PY_VER="$("$PYTHON" --version)"
ok "Python: $PY_VER at $PYTHON"

# ── Step 2: Install PyTorch ───────────────────────────────────────────────────
step "Installing PyTorch..."
if $CPU_ONLY; then
    warn "--cpu flag set — installing CPU-only torch."
    "$PYTHON" -m pip install torch torchvision -q
else
    # Detect CUDA version
    if command -v nvcc &>/dev/null; then
        CUDA_VER=$(nvcc --version | grep -oP 'release \K\d+' | head -1)
        if [[ "$CUDA_VER" == "11" ]]; then
            INDEX_URL="https://download.pytorch.org/whl/cu118"
        else
            INDEX_URL="https://download.pytorch.org/whl/cu121"
        fi
        ok "CUDA $CUDA_VER detected — installing from $INDEX_URL"
        "$PYTHON" -m pip install torch torchvision --index-url "$INDEX_URL" -q
        "$PYTHON" -m pip install "onnxruntime-gpu>=1.23.0" -q || {
            warn "onnxruntime-gpu install failed — falling back to CPU onnxruntime."
            "$PYTHON" -m pip install "onnxruntime>=1.16.0" -q
        }
    else
        warn "CUDA/nvcc not found — installing CPU-only torch."
        "$PYTHON" -m pip install torch torchvision -q
    fi
fi
ok "PyTorch installed."

# ── Step 3: Python dependencies ───────────────────────────────────────────────
step "Installing Python dependencies..."
"$PYTHON" -m pip install -r "$ROOT/requirements.txt" -q
ok "Dependencies installed."

# ── Step 4: Node / Frontend ───────────────────────────────────────────────────
step "Installing frontend dependencies..."
if command -v npm &>/dev/null; then
    npm --prefix "$ROOT/frontend" install --silent
    ok "npm install complete."
else
    warn "npm not found — skipping frontend. Install Node.js 18+ and re-run."
fi

# ── Step 5: Environment file ──────────────────────────────────────────────────
step "Configuring environment variables..."
if [[ ! -f "$ROOT/.env" ]]; then
    cp "$ROOT/.env.example" "$ROOT/.env"
    ok ".env created from .env.example (SQLite default)."
    warn "Review .env and set a strong SECRET_KEY before deployment."
else
    ok ".env already exists — skipping."
fi

if [[ ! -f "$ROOT/frontend/.env" ]] && [[ -f "$ROOT/frontend/.env.example" ]]; then
    cp "$ROOT/frontend/.env.example" "$ROOT/frontend/.env"
    ok "frontend/.env created."
fi

# ── Step 6: Seed database ─────────────────────────────────────────────────────
step "Seeding database..."
cd "$ROOT"
"$PYTHON" tools/seed.py
"$PYTHON" tools/migrate_db_rooms.py
ok "Database seeded."

# ── Step 7: ViViT model ───────────────────────────────────────────────────────
if ! $SKIP_VIVIT; then
    step "Downloading ViViT model from HuggingFace (~300 MB, first-time only)..."
    if "$PYTHON" "$ROOT/scripts/download_vivit.py"; then
        ok "ViViT model cached."
    else
        warn "ViViT download failed. Run 'python scripts/download_vivit.py' when connected."
    fi
else
    ok "--skip-vivit set. Run 'python scripts/download_vivit.py' before starting seizure service."
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "============================================"
echo "  Setup complete!"
echo "============================================"
echo ""
echo "  Next steps:"
echo "  1. Start all services:   bash scripts/start_all_services.sh"
echo "  2. Start frontend:       cd frontend && npm run dev"
echo "  3. Open browser:         http://localhost:5173"
echo "  4. API docs:             http://localhost:8000/docs"
echo ""
