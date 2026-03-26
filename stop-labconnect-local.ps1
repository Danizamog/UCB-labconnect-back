$rootScript = Join-Path $PSScriptRoot "..\stop-labconnect-local.ps1"
$resolvedScript = (Resolve-Path $rootScript).Path

& powershell -ExecutionPolicy Bypass -File $resolvedScript
