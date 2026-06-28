# =============================================================================
# stop_all_services.ps1 - Stop any running monitoring services on local ports
# =============================================================================

$ports = @("8000", "8001", "8002", "8003")

Write-Host "Checking for processes on ward monitoring ports: $ports" -ForegroundColor Cyan

foreach ($port in $ports) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        $pid = $conn.OwningProcess
        Write-Host "Found process on port $port with PID: $pid. Stopping it..." -ForegroundColor Yellow
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped process on port $port." -ForegroundColor Green
    } else {
        Write-Host "Port $port is free." -ForegroundColor Gray
    }
}

Write-Host "All checks complete." -ForegroundColor Green
