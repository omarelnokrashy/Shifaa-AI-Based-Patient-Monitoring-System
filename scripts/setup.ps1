#Requires -Version 5.1
<#
.SYNOPSIS
    One-shot setup script for Shifaa Medical Monitoring System (Windows).

.DESCRIPTION
    This script performs the complete first-time setup:
      1. Creates a conda environment (or validates an existing one)
      2. Installs CUDA-enabled PyTorch (requires NVIDIA GPU + CUDA drivers)
      3. Installs all Python dependencies
      4. Copies .env from .env.example if .env does not exist
      5. Seeds the database
      6. Downloads the ViViT model weights from HuggingFace (first-time only)

.USAGE
    # From repo root, with conda activated:
    powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1

    # To skip GPU torch and use CPU only (slower inference):
    powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -CpuOnly

.PARAMETER CpuOnly
    Skip CUDA PyTorch installation. Installs CPU-only torch from PyPI.
    Inference will be significantly slower on all three AI services.

.PARAMETER SkipVivit
    Skip downloading the ViViT HuggingFace model.
    Use this if you are on an air-gapped machine and have pre-copied the cache.
#>

param(
    [switch]$CpuOnly,
    [switch]$SkipVivit
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ROOT = Split-Path -Parent $PSScriptRoot

function Write-Step {
    param([string]$msg)
    Write-Host "`n[SETUP] $msg" -ForegroundColor Cyan
}

function Write-OK   { param([string]$msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn { param([string]$msg) Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Fail { param([string]$msg) Write-Host "  [FAIL] $msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "============================================" -ForegroundColor Magenta
Write-Host "  Shifaa — First-Time Setup (Windows)       " -ForegroundColor Magenta
Write-Host "============================================" -ForegroundColor Magenta
Write-Host ""

# ── Step 1: Verify Python ─────────────────────────────────────────────────────
Write-Step "Checking Python..."
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) {
    Write-Fail "Python not found in PATH. Activate your conda environment first:`n  conda activate shifaa"
}
$pyVersion = & $python --version 2>&1
Write-OK "Python: $pyVersion at $python"

# ── Step 2: Install PyTorch ───────────────────────────────────────────────────
Write-Step "Installing PyTorch..."
if ($CpuOnly) {
    Write-Warn "CpuOnly flag set — installing CPU-only torch. Inference will be slow."
    & $python -m pip install torch torchvision --quiet
} else {
    Write-Host "  Detecting CUDA version..."
    $nvcc = Get-Command nvcc -ErrorAction SilentlyContinue
    if ($nvcc) {
        $cudaVerLine = & nvcc --version 2>&1 | Select-String "release"
        $cudaMajor = if ($cudaVerLine -match "release (\d+)\.") { $matches[1] } else { "12" }
        if ($cudaMajor -eq "11") {
            $indexUrl = "https://download.pytorch.org/whl/cu118"
        } else {
            $indexUrl = "https://download.pytorch.org/whl/cu121"
        }
        Write-OK "CUDA $cudaMajor detected — installing torch from $indexUrl"
        & $python -m pip install torch torchvision --index-url $indexUrl --quiet
    } else {
        Write-Warn "CUDA/nvcc not found in PATH — falling back to CPU-only torch."
        Write-Warn "If you have a GPU, ensure CUDA Toolkit is installed and nvcc is in PATH."
        & $python -m pip install torch torchvision --quiet
    }
    # Install onnxruntime-gpu for GPU-accelerated ONNX inference
    Write-Host "  Installing onnxruntime-gpu..."
    & $python -m pip install "onnxruntime-gpu>=1.23.0" --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "onnxruntime-gpu install failed — falling back to CPU onnxruntime."
        & $python -m pip install "onnxruntime>=1.16.0" --quiet
    }
}
Write-OK "PyTorch installed."

# ── Step 3: Install all other Python dependencies ─────────────────────────────
Write-Step "Installing Python dependencies from requirements.txt..."
& $python -m pip install -r "$ROOT\requirements.txt" --quiet
Write-OK "Dependencies installed."

# ── Step 4: Node.js / Frontend ────────────────────────────────────────────────
Write-Step "Installing frontend dependencies..."
$npm = Get-Command npm -ErrorAction SilentlyContinue
if ($npm) {
    Push-Location "$ROOT\frontend"
    & npm install --silent 2>&1 | Out-Null
    Pop-Location
    Write-OK "npm install complete."
} else {
    Write-Warn "npm not found — skipping frontend install. Install Node.js 18+ and re-run."
}

# ── Step 5: Create .env ───────────────────────────────────────────────────────
Write-Step "Configuring environment variables..."
if (-not (Test-Path "$ROOT\.env")) {
    Copy-Item "$ROOT\.env.example" "$ROOT\.env"
    Write-OK ".env created from .env.example (SQLite, default settings)."
    Write-Warn "Review $ROOT\.env and set SECRET_KEY to a long random string."
} else {
    Write-OK ".env already exists — skipping."
}

# Frontend .env
if (-not (Test-Path "$ROOT\frontend\.env")) {
    if (Test-Path "$ROOT\frontend\.env.example") {
        Copy-Item "$ROOT\frontend\.env.example" "$ROOT\frontend\.env"
        Write-OK "frontend/.env created."
    }
}

# ── Step 6: Seed Database ─────────────────────────────────────────────────────
Write-Step "Seeding database..."
Push-Location $ROOT
& $python tools/seed.py
& $python tools/migrate_db_rooms.py
Pop-Location
Write-OK "Database seeded."

# ── Step 7: Download ViViT Model ──────────────────────────────────────────────
if (-not $SkipVivit) {
    Write-Step "Downloading ViViT model from HuggingFace (first-time only, ~300 MB)..."
    & $python "$ROOT\scripts\download_vivit.py"
    if ($LASTEXITCODE -eq 0) {
        Write-OK "ViViT model cached."
    } else {
        Write-Warn "ViViT download failed. Run 'python scripts\download_vivit.py' manually when you have internet access."
    }
} else {
    Write-OK "SkipVivit flag set — skipping ViViT download."
}

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Setup complete!                           " -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Next steps:"
Write-Host "  1. Start all services:   .\scripts\start_all_services.ps1"
Write-Host "  2. Start frontend:       cd frontend && npm run dev"
Write-Host "  3. Open browser:         http://localhost:5173"
Write-Host "  4. API docs:             http://localhost:8000/docs"
Write-Host ""
