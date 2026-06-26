# Publica la release v1.0.0 en GitHub (usa ruta completa de gh; no depende del PATH).
$ErrorActionPreference = "Stop"
$gh = "C:\Program Files\GitHub CLI\gh.exe"
$repo = "Javierlw60/Bot-Agencia"
$tag = "v1.0.0"
$notes = Join-Path $PSScriptRoot ".release-v1.0.0-notes.md"

if (-not (Test-Path $gh)) {
    Write-Host "No se encontro GitHub CLI. Instalalo con: winget install GitHub.cli" -ForegroundColor Red
    exit 1
}

Write-Host "GitHub CLI: $(& $gh --version)" -ForegroundColor Cyan

$authOk = $false
try {
    & $gh auth status 2>$null
    if ($LASTEXITCODE -eq 0) { $authOk = $true }
} catch { }

if (-not $authOk) {
    Write-Host ""
    Write-Host "=== Login en GitHub (solo una vez) ===" -ForegroundColor Yellow
    Write-Host "1. Aparecera un codigo (ej. ABCD-1234)"
    Write-Host "2. Abri https://github.com/login/device en el navegador"
    Write-Host "3. Pega el codigo AHI (no en esta terminal)"
    Write-Host "4. Autoriza el acceso y volve aca"
    Write-Host ""
    & $gh auth login --hostname github.com --git-protocol https --web
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Login cancelado o fallido." -ForegroundColor Red
        exit 1
    }
}

if (-not (Test-Path $notes)) {
    Write-Host "Falta el archivo de notas: $notes" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Publicando release $tag..." -ForegroundColor Cyan
& $gh release create $tag `
    --repo $repo `
    --title "Bot Agencias v1.0.0" `
    --notes-file $notes

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Release publicada:" -ForegroundColor Green
    Write-Host "https://github.com/$repo/releases/tag/$tag"
} else {
    Write-Host "No se pudo crear la release (puede que ya exista)." -ForegroundColor Red
    exit 1
}
