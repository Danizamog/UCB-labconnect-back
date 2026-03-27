$ErrorActionPreference = "Stop"

$backendRoot = $PSScriptRoot
$pidFile = Join-Path $backendRoot ".run\labconnect-back-pids.json"
$managedPorts = @(8000, 8005, 8101, 8103, 8104)

if (Test-Path $pidFile) {
    try {
        $processes = Get-Content $pidFile | ConvertFrom-Json
        foreach ($process in $processes) {
            try {
                Stop-Process -Id ([int]$process.pid) -Force -ErrorAction Stop
            }
            catch {
            }
        }
        Remove-Item $pidFile -Force
    }
    catch {
    }
}

foreach ($port in $managedPorts) {
    $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        try {
            Stop-Process -Id $listener.OwningProcess -Force -ErrorAction Stop
        }
        catch {
        }
    }
}

Write-Host "LabConnect backend detenido."
