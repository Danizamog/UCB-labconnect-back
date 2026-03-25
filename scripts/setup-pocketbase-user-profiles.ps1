param(
    [Parameter(Mandatory = $true)]
    [string]$BaseUrl,

    [Parameter(Mandatory = $true)]
    [string]$Identity,

    [Parameter(Mandatory = $true)]
    [string]$Password,

    [string]$CollectionName = "users"
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
            # continuar con el siguiente endpoint
        }
    }

    throw "No se pudo autenticar en PocketBase."
}

function Get-CollectionDefinition {
    param(
        [string]$Url,
        [string]$Token,
        [string]$Name
    )

    Invoke-RestMethod -Method Get -Uri "$Url/api/collections/$Name" -Headers @{ Authorization = "Bearer $Token" }
}

function Ensure-Field {
    param(
        [System.Collections.ArrayList]$Fields,
        [string]$Name,
        [hashtable]$Definition
    )

    $existing = $Fields | Where-Object { $_.name -eq $Name }
    if (-not $existing) {
        [void]$Fields.Add($Definition)
        return $true
    }
    return $false
}

$cleanUrl = $BaseUrl.TrimEnd("/")
$token = Invoke-PbAuth -Url $cleanUrl -User $Identity -Pass $Password
$collection = Get-CollectionDefinition -Url $cleanUrl -Token $token -Name $CollectionName
$fields = [System.Collections.ArrayList]::new()

foreach ($field in $collection.fields) {
    [void]$fields.Add($field)
}

$changed = $false
$changed = (Ensure-Field -Fields $fields -Name "profile_type" -Definition @{
    name = "profile_type"
    type = "select"
    required = $false
    maxSelect = 1
    values = @("student", "teacher", "staff", "guest", "lab_manager")
}) -or $changed
$changed = (Ensure-Field -Fields $fields -Name "phone" -Definition @{
    name = "phone"
    type = "text"
    required = $false
    max = 60
}) -or $changed
$changed = (Ensure-Field -Fields $fields -Name "academic_page" -Definition @{
    name = "academic_page"
    type = "url"
    required = $false
    exceptDomains = $null
    onlyDomains = $null
}) -or $changed
$changed = (Ensure-Field -Fields $fields -Name "faculty" -Definition @{
    name = "faculty"
    type = "text"
    required = $false
    max = 140
}) -or $changed
$changed = (Ensure-Field -Fields $fields -Name "career" -Definition @{
    name = "career"
    type = "text"
    required = $false
    max = 140
}) -or $changed
$changed = (Ensure-Field -Fields $fields -Name "student_code" -Definition @{
    name = "student_code"
    type = "text"
    required = $false
    max = 80
}) -or $changed
$changed = (Ensure-Field -Fields $fields -Name "campus" -Definition @{
    name = "campus"
    type = "text"
    required = $false
    max = 120
}) -or $changed
$changed = (Ensure-Field -Fields $fields -Name "bio" -Definition @{
    name = "bio"
    type = "editor"
    required = $false
    convertURLs = $true
}) -or $changed
$changed = (Ensure-Field -Fields $fields -Name "is_active" -Definition @{
    name = "is_active"
    type = "bool"
    required = $false
}) -or $changed

if (-not $changed) {
    Write-Host "La colección '$CollectionName' ya tiene los campos de perfiles."
    exit 0
}

$payload = @{ fields = $fields } | ConvertTo-Json -Depth 20
Invoke-RestMethod -Method Patch -Uri "$cleanUrl/api/collections/$CollectionName" -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" -Body $payload | Out-Null
Write-Host "Colección '$CollectionName' actualizada con campos de perfiles."
