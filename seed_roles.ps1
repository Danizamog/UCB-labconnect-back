<#
.SYNOPSIS
Seed principal roles (Administrador, Docente, Estudiante, Ayudante de Laboratorio) to PocketBase.

.DESCRIPTION
Creates 4 principal roles with their permissions in the role-service database via REST API.

.PARAMETER ApiBase
Base URL of the API gateway (default: http://localhost:8000)

.EXAMPLE
.\seed_roles.ps1
.\seed_roles.ps1 -ApiBase "http://api.production.local:8000"
#>

param(
    [string]$ApiBase = 'http://localhost:8000'
)

$ErrorActionPreference = 'Stop'

# Define the 4 principal roles with their permissions
$ROLES = @(
    @{
        nombre = 'Administrador'
        descripcion = 'Acceso total al sistema: gestión de roles, usuarios, inventario y configuración.'
        permisos = @('gestionar_roles_permisos','reactivar_cuentas','gestionar_reservas','gestionar_reservas_materiales','gestionar_reglas_reserva','gestionar_inventario','gestionar_stock','gestionar_estado_equipos','gestionar_mantenimiento','gestionar_prestamos','adjuntar_evidencia_inventario','gestionar_accesos_laboratorio','gestionar_penalizaciones','gestionar_tutorias','gestionar_inscripciones_tutorias','gestionar_asistencia_tutorias','gestionar_observaciones_tutorias','gestionar_notificaciones','generar_reportes','consultar_estadisticas')
    },
    @{
        nombre = 'Docente'
        descripcion = 'Gestión de tutorías, consulta de reservas, acceso a estadísticas de laboratorio.'
        permisos = @('gestionar_tutorias','gestionar_inscripciones_tutorias','gestionar_asistencia_tutorias','gestionar_observaciones_tutorias','gestionar_reservas','consultar_estadisticas','gestionar_notificaciones','gestionar_accesos_laboratorio','autorizar_practicas_riesgo','generar_reportes')
    },
    @{
        nombre = 'Estudiante'
        descripcion = 'Acceso limitado: crear/ver reservas, consultar stock, registrar asistencia a tutorías.'
        permisos = @('gestionar_reservas','gestionar_inscripciones_tutorias','gestionar_asistencia_tutorias')
    },
    @{
        nombre = 'Ayudante de Laboratorio'
        descripcion = 'Gestión de inventario, stock, equipo, mantenimiento y control de acceso.'
        permisos = @('gestionar_inventario','gestionar_stock','gestionar_estado_equipos','gestionar_mantenimiento','gestionar_prestamos','adjuntar_evidencia_inventario','gestionar_accesos_laboratorio','gestionar_reactivos_quimicos','gestionar_hojas_seguridad_msds','gestionar_epp_bioseguridad','gestionar_incidentes_laboratorio','gestionar_calibracion_instrumentos','consultar_estadisticas')
    }
)

Write-Host "=== Seed Principal Roles ===" -ForegroundColor Cyan
Write-Host "API Base: $ApiBase"
Write-Host ""

# Health check
try {
    $health = Invoke-RestMethod "$ApiBase/health"
    Write-Host "✓ API is running" -ForegroundColor Green
} catch {
    Write-Host "✗ Cannot connect to API" -ForegroundColor Red
    exit 1
}

Write-Host ""
$created = 0

foreach ($roleData in $ROLES) {
    $body = @{
        nombre = $roleData.nombre
        descripcion = $roleData.descripcion
        permisos = $roleData.permisos
    } | ConvertTo-Json -Depth 10

    try {
        Invoke-RestMethod "$ApiBase/api/v1/roles" -Method Post -ContentType 'application/json' -Body $body | Out-Null
        Write-Host "✓ Created: $($roleData.nombre)" -ForegroundColor Green
        $created++
    } catch {
        Write-Host "✗ Error creating '$($roleData.nombre)'" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Cyan
Write-Host "Created: $created/4 roles" -ForegroundColor Green
Write-Host "✓ Seeding completed!" -ForegroundColor Green
