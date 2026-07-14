# =============================================================================
# start_all_services.ps1 - Unified Medical Monitoring System launcher for Windows
# =============================================================================

$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$logDir = Join-Path $projectRoot "runtime\logs"

# Create logs directory if it doesn't exist
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

# -- 1. Load environment variables ---------------------------------------------
$envFile = Join-Path $projectRoot ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#")) {
            $key, $value = $line -split '=', 2
            if ($key -and $value) {
                [System.Environment]::SetEnvironmentVariable($key.Trim(), $value.Trim(), "Process")
            }
        }
    }
    Write-Host "[OK] Loaded .env" -ForegroundColor Green
} else {
    Write-Host "[WARNING] .env not found. Using defaults." -ForegroundColor Yellow
}

# -- 2. Pick Python Interpreter ------------------------------------------------
# Use the python from the active conda/venv environment, or fall back to PATH.
$pythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonPath) {
    $pythonPath = "python"
}
Write-Host "[OK] Using Python: $pythonPath" -ForegroundColor Cyan

# -- 3. Ports Configuration ----------------------------------------------------
$mainPort = $env:MAIN_PORT; if (-not $mainPort) { $mainPort = "8000" }
$arrPort  = $env:ARRHYTHMIA_PORT; if (-not $arrPort) { $arrPort = "8001" }
$fallPort = $env:FALL_DETECTION_PORT; if (-not $fallPort) { $fallPort = "8002" }
$seizPort = $env:SEIZURE_DETECTION_PORT; if (-not $seizPort) { $seizPort = "8003" }

Write-Host "`n============================================================" -ForegroundColor Gray
Write-Host "     Medical Monitoring System - Starting services on Windows" -ForegroundColor White
Write-Host "============================================================`n" -ForegroundColor Gray

$processes = @()

# Helper function to launch a process
function Start-ServiceProcess {
    param (
        [string]$Name,
        [string]$AppDir,
        [string]$Port,
        [string]$LogName,
        [string[]]$ArgsList
    )
    
    $serviceLogDir = Join-Path $logDir $LogName
    if (-not (Test-Path $serviceLogDir)) {
        New-Item -ItemType Directory -Path $serviceLogDir | Out-Null
    }
    $stdoutPath = Join-Path $serviceLogDir "$LogName.log"
    $stderrPath = Join-Path $serviceLogDir "$LogName.err.log"
    $env:PORT = $Port
    
    Write-Host "[*] Starting $Name on port $Port ..."
    $proc = Start-Process -FilePath $pythonPath -ArgumentList $ArgsList -WorkingDirectory $AppDir -NoNewWindow -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    Write-Host "    PID = $($proc.Id) | Logs = runtime/logs/$LogName/$LogName.log"
    return $proc
}

try {
    # -- 3.1 Arrhythmia Service ------------------------------------------------
    $portActive = Get-NetTCPConnection -LocalPort $arrPort -State Listen -ErrorAction SilentlyContinue
    if (-not $portActive) {
        $arrDir = Join-Path $projectRoot "services\arrhythmia"
        $processes += Start-ServiceProcess -Name "Arrhythmia Service" -AppDir $arrDir -Port $arrPort -LogName "arrhythmia" -ArgsList @("-m", "uvicorn", "service:app", "--host", "0.0.0.0", "--port", $arrPort, "--no-access-log")
    } else {
        Write-Host "[*] Arrhythmia Service is already running on port $arrPort. Skipping startup." -ForegroundColor Yellow
    }

    # -- 3.2 Fall Detection Service --------------------------------------------
    $portActive = Get-NetTCPConnection -LocalPort $fallPort -State Listen -ErrorAction SilentlyContinue
    if (-not $portActive) {
        $fallDir = Join-Path $projectRoot "services\fall_detection"
        $processes += Start-ServiceProcess -Name "Fall Detection Service" -AppDir $fallDir -Port $fallPort -LogName "fall" -ArgsList @("-m", "uvicorn", "service:app", "--host", "0.0.0.0", "--port", $fallPort, "--no-access-log")
    } else {
        Write-Host "[*] Fall Detection Service is already running on port $fallPort. Skipping startup." -ForegroundColor Yellow
    }

    # -- 3.3 Seizure Detection Service -----------------------------------------
    $portActive = Get-NetTCPConnection -LocalPort $seizPort -State Listen -ErrorAction SilentlyContinue
    if (-not $portActive) {
        $seizDir = Join-Path $projectRoot "services\seizure_detection"
        $processes += Start-ServiceProcess -Name "Seizure Detection Service" -AppDir $seizDir -Port $seizPort -LogName "seizure" -ArgsList @("-m", "uvicorn", "service:app", "--host", "0.0.0.0", "--port", $seizPort, "--no-access-log")
    } else {
        Write-Host "[*] Seizure Detection Service is already running on port $seizPort. Skipping startup." -ForegroundColor Yellow
    }

    # -- 3.4 Main FastAPI Backend ----------------------------------------------
    $portActive = Get-NetTCPConnection -LocalPort $mainPort -State Listen -ErrorAction SilentlyContinue
    if (-not $portActive) {
        $processes += Start-ServiceProcess -Name "Main Backend" -AppDir $projectRoot -Port $mainPort -LogName "backend" -ArgsList @("-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", $mainPort, "--reload")
    } else {
        Write-Host "[*] Main Backend is already running on port $mainPort. Skipping startup." -ForegroundColor Yellow
    }

    Write-Host "`n============================================================" -ForegroundColor Gray
    Write-Host "  All services started. Press Ctrl+C to stop all." -ForegroundColor Green
    Write-Host "  Main Backend      -> http://localhost:$mainPort"
    Write-Host "  Arrhythmia Svc    -> http://localhost:$arrPort"
    Write-Host "  Fall Detection    -> http://localhost:$fallPort"
    Write-Host "  Seizure Detection -> http://localhost:$seizPort"
    Write-Host "  Swagger UI Docs   -> http://localhost:$mainPort/docs"
    Write-Host "============================================================`n" -ForegroundColor Gray

    # Keep script running and monitor processes
    while ($true) {
        Start-Sleep -Seconds 1
        foreach ($proc in $processes) {
            if ($proc.HasExited) {
                Write-Host "[!] A service has stopped unexpectedly: ID $($proc.Id)" -ForegroundColor Red
                exit
            }
        }
    }
}
finally {
    Write-Host "`nStopping all services..." -ForegroundColor Yellow
    foreach ($proc in $processes) {
        if ($proc -and -not $proc.HasExited) {
            Write-Host "Killing process $($proc.Id)..."
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host "All services stopped." -ForegroundColor Green
}
