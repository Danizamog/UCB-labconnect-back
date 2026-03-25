param(
    [Parameter(Mandatory = $true)]
    [string]$BaseUrl,

    [Parameter(Mandatory = $true)]
    [string]$Identity,

    [Parameter(Mandatory = $true)]
    [string]$Password,

    [string]$CollectionName = "assets",

    [switch]$CreateSeed
)

$ErrorActionPreference = "Stop"

function Invoke-PbAuth {
    param(
        [string]$Url,
        [string]$User,
        [string]$Pass
    )

    $payload = @{ identity = $User; password = $Pass } | ConvertTo-Json

    $endpoints = @(
        "$Url/api/collections/_superusers/auth-with-password",
        "$Url/api/admins/auth-with-password"
    )

    foreach ($endpoint in $endpoints) {
        try {
            $resp = Invoke-RestMethod -Method Post -Uri $endpoint -ContentType "application/json" -Body $payload
            if ($resp.token) {
                return $resp.token
            }
        }
        catch {
            # intentar siguiente endpoint
        }
    }

    throw "No se pudo autenticar en PocketBase. Verifica URL/credenciales."
}

function Get-Collection {
    param(
        [string]$Url,
        [string]$Token,
        [string]$Name
    )

    try {
        return Invoke-RestMethod -Method Get -Uri "$Url/api/collections/$Name" -Headers @{ Authorization = "Bearer $Token" }
    }
    catch {
        return $null
    }
}

function New-AssetsCollection {
    param(
        [string]$Url,
        [string]$Token,
        [string]$Name
    )

    $body = @{
        name  = $Name
        type  = "base"
        fields = @(
            @{ name = "name"; type = "text"; required = $true; max = 120 }
            @{ name = "category"; type = "text"; required = $true; max = 120 }
            @{ name = "description"; type = "text"; required = $false; max = 500 }
            @{ name = "serial_number"; type = "text"; required = $false; max = 120 }
            @{ name = "laboratory_id"; type = "number"; required = $false }
            @{ name = "status"; type = "select"; required = $true; maxSelect = 1; values = @("available", "maintenance", "damaged") }
        )
    } | ConvertTo-Json -Depth 8

    Invoke-RestMethod -Method Post -Uri "$Url/api/collections" -Headers @{ Authorization = "Bearer $Token" } -ContentType "application/json" -Body $body
}

function Add-SeedRecord {
    param(
        [string]$Url,
        [string]$Token,
        [string]$Name
    )

    $seed = @{
        name = "Microscopio inicial"
        category = "Biologia"
        description = "Registro semilla"
        serial_number = "MIC-001"
        laboratory_id = 1
        status = "available"
    } | ConvertTo-Json

    Invoke-RestMethod -Method Post -Uri "$Url/api/collections/$Name/records" -Headers @{ Authorization = "Bearer $Token" } -ContentType "application/json" -Body $seed
}

$cleanUrl = $BaseUrl.TrimEnd('/')
Write-Host "Autenticando en $cleanUrl ..."
$token = Invoke-PbAuth -Url $cleanUrl -User $Identity -Pass $Password
Write-Host "Autenticación OK"

$existing = Get-Collection -Url $cleanUrl -Token $token -Name $CollectionName
if ($existing) {
    Write-Host "La colección '$CollectionName' ya existe. No se modifica."
}
else {
    Write-Host "Creando colección '$CollectionName' ..."
    $null = New-AssetsCollection -Url $cleanUrl -Token $token -Name $CollectionName
    Write-Host "Colección '$CollectionName' creada."
}

if ($CreateSeed) {
    Write-Host "Creando registro semilla..."
    $null = Add-SeedRecord -Url $cleanUrl -Token $token -Name $CollectionName
    Write-Host "Registro semilla creado."
}

Write-Host "Listo. Revisa en PocketBase la colección '$CollectionName'."
