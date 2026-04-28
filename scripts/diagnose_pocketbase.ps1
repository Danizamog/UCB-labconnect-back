# diagnose_pocketbase.ps1
# Propósito: diagnosticar conexión y autenticación contra PocketBase usando las variables en .env
# Ejecutar desde la raíz del repo (PowerShell):
#   pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\diagnose_pocketbase.ps1
#   o desde PowerShell: .\scripts\diagnose_pocketbase.ps1

$envFile = ".env"
if (-not (Test-Path $envFile)) {
  Write-Output ".env not found in repo root. Create or copy it and re-run this script."; exit 1
}

# Cargar .env en variables de proceso (no impresas)
Get-Content $envFile | ForEach-Object {
  $line = $_.Trim()
  if ($line -and -not $line.StartsWith('#') -and $line.Contains('=')) {
    $parts = $line -split '=',2
    $key = $parts[0].Trim()
    $value = $parts[1].Trim()
    if ($value.Length -gt 0) {
      if ($value.StartsWith("'") -or $value.StartsWith('"')) { $value = $value.Substring(1) }
      if ($value.Length -gt 0 -and ($value.EndsWith("'") -or $value.EndsWith('"'))) { $value = $value.Substring(0, $value.Length - 1) }
    }
    [System.Environment]::SetEnvironmentVariable($key, $value, 'Process')
  }
}

$pb = $env:POCKETBASE_URL
Write-Output "POCKETBASE_URL=$pb"
if (-not $pb) { Write-Output "POCKETBASE_URL not set in .env"; exit 1 }

# Detectar caracteres invisibles y validar la URL sin lanzar excepción
$pbTrim = $pb.Trim()
Write-Output ("POCKETBASE_URL_LEN={0}" -f $pbTrim.Length)
try {
  $chars = $pbTrim.ToCharArray()
  $firstCount = [Math]::Min(5, $chars.Length)
  $lastCount = [Math]::Min(5, $chars.Length)
  $firstHex = -join ($chars[0..($firstCount - 1)] | ForEach-Object { ('{0:X4}' -f [int][char]$_) })
  $lastHex = -join ($chars[($chars.Length - $lastCount)..($chars.Length - 1)] | ForEach-Object { ('{0:X4}' -f [int][char]$_) })
  Write-Output ("POCKETBASE_URL_FIRST5_HEX=$firstHex")
  Write-Output ("POCKETBASE_URL_LAST5_HEX=$lastHex")
} catch {
  Write-Output "URL_HEX_FAIL: $($_.Exception.Message)"
}
$uriRef = $null
$ok = [System.Uri]::TryCreate($pbTrim, [System.UriKind]::Absolute, [ref]$uriRef)
if ($ok -and $uriRef -ne $null) {
  Write-Output ("Host={0}" -f $uriRef.Host)
  # use a distinct variable name to avoid collision with automatic $Host
  $hostName = $uriRef.Host
} else {
  Write-Output ("Invalid POCKETBASE_URL (TryCreate failed): '$pb'")
  exit 1
}

# DNS resolution
try {
  $addrs = [System.Net.Dns]::GetHostAddresses($hostName) | ForEach-Object { $_.ToString() }
  Write-Output "DNS_OK: $($addrs -join ',')"
} catch {
  Write-Output "DNS_FAIL: $($_.Exception.Message)"
}

# TCP connect a 443
try {
  $tcp = New-Object System.Net.Sockets.TcpClient
  $async = $tcp.BeginConnect($hostName, 443, $null, $null)
  $wait = $async.AsyncWaitHandle.WaitOne(5000)
  if (-not $wait) { Write-Output 'TCP_CONNECT_TIMEOUT'; exit 2 }
  $tcp.EndConnect($async); $tcp.Close(); Write-Output 'TCP_OK'
} catch {
  Write-Output "TCP_FAIL: $($_.Exception.Message)"
}

# HEAD request
try {
  $resp = Invoke-WebRequest -Uri $pb -Method Head -UseBasicParsing -TimeoutSec 10
  Write-Output "HEAD_OK: $($resp.StatusCode)"
} catch {
  Write-Output "HEAD_FAIL: $($_.Exception.Message)"
}

# Preparar payload de autenticación (no se imprimen contraseñas)
$payload = @{ identity = $env:POCKETBASE_AUTH_IDENTITY; password = $env:POCKETBASE_AUTH_PASSWORD }
Write-Output "AUTH_IDENTITY = $($env:POCKETBASE_AUTH_IDENTITY)"

# Intentar autenticación admin
$token = $null
try {
  $resp = Invoke-RestMethod -Method Post -Uri "$pb/api/admins/auth-with-password" -Body ($payload | ConvertTo-Json) -ContentType 'application/json' -TimeoutSec 15
  if ($resp.token) { Write-Output 'AUTH_ADMIN_OK'; $token = $resp.token } else { Write-Output 'AUTH_ADMIN_NO_TOKEN' }
} catch {
  Write-Output "AUTH_ADMIN_FAIL: $($_.Exception.Message)"
}

# Si no hay token, intentar autenticación por colección (si está configurada)
if (-not $token -and $env:POCKETBASE_AUTH_COLLECTION) {
  try {
    $resp2 = Invoke-RestMethod -Method Post -Uri "$pb/api/collections/$($env:POCKETBASE_AUTH_COLLECTION)/auth-with-password" -Body ($payload | ConvertTo-Json) -ContentType 'application/json' -TimeoutSec 15
    if ($resp2.token) { Write-Output 'AUTH_COLLECTION_OK'; $token = $resp2.token } else { Write-Output 'AUTH_COLLECTION_NO_TOKEN' }
  } catch {
    Write-Output "AUTH_COLLECTION_FAIL: $($_.Exception.Message)"
  }
}

if ($token) {
  Write-Output "AUTH_TOKEN_OBTAINED: token present (not displayed)"
  $headers = @{ Authorization = "Bearer $token" }
  # Fetch small samples; if collection env vars are not set, use sensible defaults
  $tutorialColl = if ($env:POCKETBASE_TUTORIAL_SESSION_COLLECTION) { $env:POCKETBASE_TUTORIAL_SESSION_COLLECTION } else { 'tutorial_session' }
  $labColl = if ($env:POCKETBASE_LABORATORY_COLLECTION) { $env:POCKETBASE_LABORATORY_COLLECTION } else { 'laboratory' }
  try {
    $t = Invoke-RestMethod -Method Get -Uri "$pb/api/collections/$tutorialColl/records?page=1&perPage=3" -Headers $headers -TimeoutSec 15
    Write-Output "TUTORIALS_OK: $($t.items.Count) items"
    $t.items | Select id,topic,session_date,start_time,end_time,is_published | ConvertTo-Json -Depth 3
  } catch {
    Write-Output "TUTORIALS_FETCH_FAIL: $($_.Exception.Message)"
  }
  try {
    $l = Invoke-RestMethod -Method Get -Uri "$pb/api/collections/$labColl/records?page=1&perPage=3" -Headers $headers -TimeoutSec 15
    Write-Output "LABS_OK: $($l.items.Count) items"
    $l.items | Select id,name,location,is_active,area_id | ConvertTo-Json -Depth 3
  } catch {
    Write-Output "LABS_FETCH_FAIL: $($_.Exception.Message)"
  }
} else {
  Write-Output "NO_TOKEN: authentication failed"
}

Write-Output "DONE"
