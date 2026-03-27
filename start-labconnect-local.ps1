$ErrorActionPreference = "Stop"

$backendRoot = $PSScriptRoot
$pythonExe = Join-Path $backendRoot ".venv\Scripts\python.exe"
$backendEnvPath = Join-Path $backendRoot ".env"
$runDir = Join-Path $backendRoot ".run"
$pidFile = Join-Path $runDir "labconnect-back-pids.json"
$logsDir = Join-Path $runDir "logs"

$authPort = 8101
$inventoryPort = 8103
$rolePort = 8104
$reservationsPort = 8005
$gatewayPort = 8000

New-Item -ItemType Directory -Force $runDir | Out-Null
New-Item -ItemType Directory -Force $logsDir | Out-Null

if (-not (Test-Path $pythonExe)) {
    throw "No se encontro el entorno virtual en $pythonExe. Primero crea .venv e instala dependencias."
}

if (-not (Test-Path $backendEnvPath)) {
    throw "Falta el archivo .env en $backendRoot"
}

$envConfig = @{}
foreach ($line in Get-Content $backendEnvPath) {
    if ($line -match '^[^#].*=') {
        $parts = $line.Split('=', 2)
        $envConfig[$parts[0].Trim()] = $parts[1].Trim()
    }
}

if ($envConfig["POCKETBASE_URL"] -and $envConfig["POCKETBASE_AUTH_IDENTITY"] -and $envConfig["POCKETBASE_AUTH_PASSWORD"]) {
    try {
        & (Join-Path $backendRoot "scripts\setup-pocketbase-user-profiles.ps1") `
            -BaseUrl $envConfig["POCKETBASE_URL"] `
            -Identity $envConfig["POCKETBASE_AUTH_IDENTITY"] `
            -Password $envConfig["POCKETBASE_AUTH_PASSWORD"] | Out-Null
    }
    catch {
        Write-Host "No se pudo preparar PocketBase para perfiles de usuario: $($_.Exception.Message)"
    }
}

function Stop-ServicePorts {
    param([int[]]$Ports)

    foreach ($port in $Ports) {
        $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        foreach ($listener in $listeners) {
            try {
                Stop-Process -Id $listener.OwningProcess -Force -ErrorAction Stop
            }
            catch {
                Write-Host "No se pudo liberar el puerto $port (PID $($listener.OwningProcess))."
            }
        }
    }
}

function Start-BackendService {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][hashtable]$Environment
    )

    $commandLines = @("Set-Location -LiteralPath '$($WorkingDirectory.Replace("'", "''"))'")
    foreach ($entry in $Environment.GetEnumerator()) {
        $commandLines += "`$env:$($entry.Key)='$($entry.Value.Replace("'", "''"))'"
    }
    $commandLines += "& '$($pythonExe.Replace("'", "''"))' -m uvicorn app.main:app --host 127.0.0.1 --port $Port"
    $command = $commandLines -join "; "

    $stdout = Join-Path $logsDir "$Name.out.log"
    $stderr = Join-Path $logsDir "$Name.err.log"
    if (Test-Path $stdout) { Remove-Item $stdout -Force }
    if (Test-Path $stderr) { Remove-Item $stderr -Force }

    $process = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList "-NoLogo", "-NoProfile", "-Command", $command `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden `
        -PassThru

    return [pscustomobject]@{
        name = $Name
        pid = $process.Id
        port = $Port
        stdout = $stdout
        stderr = $stderr
    }
}

function Wait-ForHealth {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$LogPath
    )

    $deadline = (Get-Date).AddSeconds(40)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 5
            if ($response.StatusCode -eq 200) {
                return
            }
        }
        catch {
            Start-Sleep -Milliseconds 800
        }
    }

    $logTail = ""
    if (Test-Path $LogPath) {
        $logTail = (Get-Content $LogPath -Tail 40 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
    }

    throw "El servicio $Name no levanto correctamente. Revisa $LogPath`n$logTail"
}

$managedPorts = @($authPort, $inventoryPort, $rolePort, $reservationsPort, $gatewayPort)
Stop-ServicePorts -Ports $managedPorts

$processes = @()

$processes += Start-BackendService `
    -Name "auth-service" `
    -WorkingDirectory (Join-Path $backendRoot "auth-service") `
    -Port $authPort `
    -Environment @{}

$processes += Start-BackendService `
    -Name "inventory-service" `
    -WorkingDirectory (Join-Path $backendRoot "inventory-service") `
    -Port $inventoryPort `
    -Environment @{ AUTH_SERVICE_URL = "http://127.0.0.1:$authPort" }

$processes += Start-BackendService `
    -Name "role-service" `
    -WorkingDirectory (Join-Path $backendRoot "role-service") `
    -Port $rolePort `
    -Environment @{ AUTH_SERVICE_URL = "http://127.0.0.1:$authPort" }

$processes += Start-BackendService `
    -Name "reservations-service" `
    -WorkingDirectory (Join-Path $backendRoot "reservations-service") `
    -Port $reservationsPort `
    -Environment @{
        AUTH_SERVICE_URL = "http://127.0.0.1:$authPort"
        INVENTORY_SERVICE_URL = "http://127.0.0.1:$inventoryPort"
    }

$processes += Start-BackendService `
    -Name "api-gateway" `
    -WorkingDirectory (Join-Path $backendRoot "api-gateway") `
    -Port $gatewayPort `
    -Environment @{
        AUTH_SERVICE_URL = "http://127.0.0.1:$authPort"
        INVENTORY_SERVICE_URL = "http://127.0.0.1:$inventoryPort"
        ROLE_SERVICE_URL = "http://127.0.0.1:$rolePort"
        RESERVATIONS_SERVICE_URL = "http://127.0.0.1:$reservationsPort"
        CORS_ALLOWED_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173"
    }

$processes | ConvertTo-Json | Set-Content -Path $pidFile

Wait-ForHealth -Name "auth-service" -Url "http://127.0.0.1:$authPort/health" -LogPath (Join-Path $logsDir "auth-service.err.log")
Wait-ForHealth -Name "inventory-service" -Url "http://127.0.0.1:$inventoryPort/health" -LogPath (Join-Path $logsDir "inventory-service.err.log")
Wait-ForHealth -Name "role-service" -Url "http://127.0.0.1:$rolePort/health" -LogPath (Join-Path $logsDir "role-service.err.log")
Wait-ForHealth -Name "reservations-service" -Url "http://127.0.0.1:$reservationsPort/health" -LogPath (Join-Path $logsDir "reservations-service.err.log")
Wait-ForHealth -Name "api-gateway" -Url "http://127.0.0.1:$gatewayPort/health" -LogPath (Join-Path $logsDir "api-gateway.err.log")

Write-Host "LabConnect backend levantado."
Write-Host "Gateway:      http://localhost:$gatewayPort"
Write-Host "Auth:         http://localhost:$authPort/health"
Write-Host "Inventory:    http://localhost:$inventoryPort/health"
Write-Host "Role:         http://localhost:$rolePort/health"
Write-Host "Reservations: http://localhost:$reservationsPort/health"
