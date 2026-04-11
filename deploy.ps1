# deploy.ps1 — Deploy seguro: corre tests locales antes de subir a Railway.
#
# Uso:
#   .\deploy.ps1              # tests + deploy
#   .\deploy.ps1 -SkipTests   # solo deploy (emergencias)
#   .\deploy.ps1 -TestsOnly   # solo tests, sin deploy
#
# Tests live contra Railway (opcional):
#   $env:ADMIN_API_KEY = "tu-key"
#   .\deploy.ps1

param(
    [switch]$SkipTests,
    [switch]$TestsOnly
)

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ROOT

function Write-Step($msg) {
    Write-Host "`n==> $msg" -ForegroundColor Cyan
}
function Write-Ok($msg) {
    Write-Host "    OK: $msg" -ForegroundColor Green
}
function Write-Fail($msg) {
    Write-Host "    FAIL: $msg" -ForegroundColor Red
}

# ─── Syntax check ─────────────────────────────────────────────────────────────
Write-Step "Verificando sintaxis Python..."
$files = @("api.py","wa_bot.py","db.py","scraper.py","messages.py","config.py")
foreach ($f in $files) {
    python -m py_compile $f
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Error de sintaxis en $f"
        exit 1
    }
}
Write-Ok "Todos los archivos tienen sintaxis válida"

# ─── Tests ────────────────────────────────────────────────────────────────────
if (-not $SkipTests) {
    Write-Step "Corriendo tests locales..."
    python -m pytest tests/ -x -q --tb=short `
        --ignore=tests/test_admin_api.py  # tests live son opcionales
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Tests fallaron — deploy abortado"
        Write-Host "  Usa -SkipTests para forzar el deploy (solo en emergencias)" -ForegroundColor Yellow
        exit 1
    }
    Write-Ok "Todos los tests pasan"

    # Tests live si ADMIN_API_KEY está configurada
    if ($env:ADMIN_API_KEY) {
        Write-Step "Corriendo tests live contra Railway..."
        python -m pytest tests/test_admin_api.py -x -q --tb=short
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "Tests live fallaron — revisa Railway antes de continuar"
            exit 1
        }
        Write-Ok "Tests live OK"
    }
}

if ($TestsOnly) {
    Write-Host "`nTests completados. Deploy omitido (-TestsOnly)." -ForegroundColor Yellow
    exit 0
}

# ─── Deploy ───────────────────────────────────────────────────────────────────
Write-Step "Desplegando en Railway..."
railway up --detach
if ($LASTEXITCODE -ne 0) {
    Write-Fail "railway up falló"
    exit 1
}

Write-Host "`n✅ Deploy iniciado. Verifica los logs con: railway logs --tail 20" -ForegroundColor Green
