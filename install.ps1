# install.ps1 - Cai dat OpcOS Orbit (venv + deps + config)
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "== OpcOS Orbit: Install ==" -ForegroundColor Cyan

# 1. Tao venv neu chua co
if (-not (Test-Path ".venv")) {
    Write-Host "Tao virtual environment (.venv)..." -ForegroundColor Yellow
    python -m venv .venv
} else {
    Write-Host ".venv da ton tai, bo qua." -ForegroundColor DarkGray
}

# 2. Cai dependencies
Write-Host "Cai dat dependencies tu requirements.txt..." -ForegroundColor Yellow
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt

# 3. Copy config.example.json -> config.json neu chua co
if (-not (Test-Path "config.json")) {
    Copy-Item "config.example.json" "config.json"
    Write-Host "Da tao config.json tu config.example.json. Hay chinh sua instances/voice truoc khi chay." -ForegroundColor Green
} else {
    Write-Host "config.json da ton tai, khong ghi de." -ForegroundColor DarkGray
}

# 4. Kiem tra CLI can thiet (claude / codex / gemini)
Write-Host ""
Write-Host "== Kiem tra CLI ==" -ForegroundColor Cyan
foreach ($cli in @("claude", "codex", "gemini")) {
    $cmd = Get-Command $cli -ErrorAction SilentlyContinue
    if ($cmd) {
        Write-Host "  [OK] $cli tim thay: $($cmd.Source)" -ForegroundColor Green
    } else {
        Write-Host "  [!!] $cli KHONG tim thay trong PATH." -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "== Huong dan xac thuc Gemini CLI ==" -ForegroundColor Cyan
Write-Host "Neu 'gemini' chua dang nhap, chay:"
Write-Host "  gemini auth login"
Write-Host "(hoac lam theo huong dan chinh thuc cua Gemini CLI de cap Google account / API key)."
Write-Host "Claude va Codex CLI cung can dang nhap rieng (claude / codex login) neu chua co."

# 5. OmniVoice (BAT BUOC - dependency cho Voice Studio / TTS)
Write-Host ""
Write-Host "== OmniVoice (bat buoc cho Voice Studio / TTS) ==" -ForegroundColor Cyan
$omniDir = Join-Path $env:USERPROFILE ".tts\omnivoice"
$omniVenvPy = Join-Path $omniDir ".venv\Scripts\python.exe"

if (-not (Test-Path $omniVenvPy)) {
    Write-Host "  [!!] Khong tim thay OmniVoice venv tai $omniVenvPy" -ForegroundColor Red
    try {
        $omniInstaller = Join-Path $omniDir "install.ps1"
        if (-not (Test-Path $omniInstaller)) {
            $bundledInstaller = Join-Path $root "assets\omnivoice-install.ps1"
            if (Test-Path $bundledInstaller) {
                Write-Host "  Chua co installer OmniVoice tai may nay -> copy tu assets\omnivoice-install.ps1" -ForegroundColor Yellow
                New-Item -ItemType Directory -Force -Path $omniDir | Out-Null
                Copy-Item $bundledInstaller $omniInstaller -Force
            } else {
                throw "Khong tim thay assets\omnivoice-install.ps1 (installer OmniVoice) trong repo nay."
            }
        }
        Write-Host "  Chay OmniVoice installer (best-effort, co the mat vai phut / can GPU)..." -ForegroundColor Yellow
        & $omniInstaller
    } catch {
        Write-Host "  [!!] OmniVoice chua cai duoc tu dong: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "  Voice Studio se KHONG hoat dong cho toi khi OmniVoice duoc cai xong thu cong tai $omniDir." -ForegroundColor Red
    }
} else {
    Write-Host "  [OK] OmniVoice venv da co: $omniVenvPy" -ForegroundColor Green
}

# 6. Restore bundle giong my-voice (assets/voices -> ~/.tts/omnivoice/voices)
if (Test-Path $omniVenvPy) {
    Write-Host ""
    Write-Host "== Restore bundle giong my-voice ==" -ForegroundColor Cyan
    try {
        $restoreOut = & ".venv\Scripts\python.exe" -c "from server.voice_setup import restore_bundled_voices, ASSETS_VOICES_DIR, OV_VOICES_DIR, set_bundled_default; print(restore_bundled_voices(ASSETS_VOICES_DIR, OV_VOICES_DIR)); print(set_bundled_default('my-voice'))"
        Write-Host "  $restoreOut" -ForegroundColor Green
    } catch {
        Write-Host "  [!!] Restore bundle giong that bai: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "  Ban co the restore thu cong sau: python -m server.voice_setup --set-default" -ForegroundColor Yellow
    }
} else {
    Write-Host "  Bo qua restore bundle giong (OmniVoice chua san sang)." -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Cai dat xong. Chay '.\run.ps1' de khoi dong server." -ForegroundColor Green
