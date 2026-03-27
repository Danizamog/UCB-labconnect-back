param()

$ErrorActionPreference = "Stop"

$backendRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $backendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    throw "No se encontro el Python del entorno virtual en $pythonExe"
}

Write-Host "Sincronizando inventory-service hacia PocketBase..."
@'
import sys
sys.path.insert(0, r"__INVENTORY_PATH__")
from app.db.bootstrap import initialize_inventory_database
from app.infrastructure.pocketbase_sync import initialize_inventory_pocketbase_sync

initialize_inventory_database()
initialize_inventory_pocketbase_sync()
print("inventory-service sincronizado")
'@.Replace("__INVENTORY_PATH__", (Join-Path $backendRoot "inventory-service")) | & $pythonExe -

Write-Host "Sincronizando reservations-service hacia PocketBase..."
@'
import sys
sys.path.insert(0, r"__RESERVATIONS_PATH__")
from app.db.bootstrap import initialize_reservations_database
from app.infrastructure.pocketbase_sync import initialize_reservations_pocketbase_sync

initialize_reservations_database()
initialize_reservations_pocketbase_sync()
print("reservations-service sincronizado")
'@.Replace("__RESERVATIONS_PATH__", (Join-Path $backendRoot "reservations-service")) | & $pythonExe -

Write-Host "PocketBase quedo sincronizado con inventario y reservas."
