# omnivoice-install.ps1 - Cai dat OmniVoice (best-effort, may-rieng: GPU/CUDA/model)
# Ban nguon nam trong agent-console (assets/omnivoice-install.ps1).
# install.ps1 cua agent-console se copy file nay sang ~/.tts/omnivoice/install.ps1
# roi chay tai do khi thieu ~/.tts/omnivoice/.venv.
#
# TRIET LY: script nay KHONG duoc fail cung. Moi buoc phu thuoc may-rieng
# (GPU/CUDA, tai model lan dau, dang nhap...) chi in canh bao va CHAY TIEP.

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "== OmniVoice: Install (best-effort) ==" -ForegroundColor Cyan
Write-Host "  Thu muc: $root" -ForegroundColor DarkGray

# 1. Tao virtual environment neu chua co
if (-not (Test-Path ".venv")) {
    Write-Host "Tao virtual environment (.venv)..." -ForegroundColor Yellow
    try {
        python -m venv .venv
    } catch {
        Write-Host "  [!!] Khong tao duoc .venv: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "  Kiem tra 'python' co trong PATH khong, roi chay lai script nay." -ForegroundColor Red
        return
    }
} else {
    Write-Host ".venv da ton tai, bo qua." -ForegroundColor DarkGray
}

$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "  [!!] Khong tim thay $venvPy sau khi tao venv. Dung lai." -ForegroundColor Red
    return
}

# 2. Nang cap pip
Write-Host ""
Write-Host "Nang cap pip..." -ForegroundColor Yellow
try {
    & $venvPy -m pip install --upgrade pip | Out-Null
} catch {
    Write-Host "  [!!] Nang cap pip that bai (bo qua, tiep tuc): $($_.Exception.Message)" -ForegroundColor Red
}

# 3. Cai torch (GPU cu126 truoc, fallback CPU) - day la buoc phu thuoc may-rieng
Write-Host ""
Write-Host "== Cai torch (uu tien GPU CUDA 12.6, fallback CPU) ==" -ForegroundColor Cyan
Write-Host "  Ghi chu: neu may co GPU NVIDIA + driver ho tro CUDA 12.6, lenh duoi day" -ForegroundColor DarkGray
Write-Host "  se cai ban torch co cu126 (vi du torch==2.12.0+cu126). Neu khong co GPU" -ForegroundColor DarkGray
Write-Host "  hoac lenh GPU that bai, script tu dong fallback sang ban CPU." -ForegroundColor DarkGray
$torchGpuOk = $false
try {
    & $venvPy -m pip install "torch" "torchaudio" --index-url https://download.pytorch.org/whl/cu126
    if ($LASTEXITCODE -eq 0) { $torchGpuOk = $true }
} catch {
    Write-Host "  [!!] Cai torch GPU (cu126) that bai: $($_.Exception.Message)" -ForegroundColor Red
}
if (-not $torchGpuOk) {
    Write-Host "  [!!] Khong cai duoc torch ban GPU (cu126) - co the may khong co CUDA 12.6." -ForegroundColor Red
    Write-Host "  Fallback: cai torch/torchaudio ban CPU (cham hon nhung van chay duoc)." -ForegroundColor Yellow
    try {
        & $venvPy -m pip install "torch" "torchaudio"
    } catch {
        Write-Host "  [!!] Fallback torch CPU cung that bai: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "  Ban se can tu cai torch thu cong: https://pytorch.org/get-started/locally/" -ForegroundColor Red
    }
}

# 4. Cai omnivoice + cac dependency con lai
Write-Host ""
Write-Host "== Cai omnivoice + dependencies ==" -ForegroundColor Cyan
$reqFile = Join-Path $root "requirements.txt"
if (Test-Path $reqFile) {
    Write-Host "  Tim thay requirements.txt -> cai tu file nay." -ForegroundColor Yellow
    try {
        & $venvPy -m pip install -r $reqFile
    } catch {
        Write-Host "  [!!] Cai tu requirements.txt that bai: $($_.Exception.Message)" -ForegroundColor Red
    }
} else {
    Write-Host "  Khong co requirements.txt tai $root." -ForegroundColor Yellow
    Write-Host "  Cai danh sach package can thiet (theo may tham chieu da biet hoat dong):" -ForegroundColor Yellow
    $fallbackPackages = @(
        "omnivoice",
        "soundfile",
        "numpy",
        "scipy",
        "transformers",
        "faster-whisper",
        "mcp"
    )
    Write-Host "    $($fallbackPackages -join ', ')" -ForegroundColor DarkGray
    try {
        & $venvPy -m pip install @fallbackPackages
    } catch {
        Write-Host "  [!!] Cai package fallback that bai: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "  Cai thu cong tung goi neu can: $venvPy -m pip install <ten-goi>" -ForegroundColor Red
    }
}

# 5. Huong dan tai model lan dau (KHONG tu chay o day - can mang/dang nhap/dia gpu)
Write-Host ""
Write-Host "== Model OmniVoice (tai lan dau) ==" -ForegroundColor Cyan
Write-Host "  Script nay KHONG tu tai model (can mang on dinh + co the can dang nhap" -ForegroundColor DarkGray
Write-Host "  Hugging Face / chap nhan license). Lan dau dung OmniVoice (vi du goi" -ForegroundColor DarkGray
Write-Host "  server/voices.py hoac mcp_server.py tu agent-console), thu vien se tu" -ForegroundColor DarkGray
Write-Host "  tai model can thiet ve cache mac dinh (~\.cache\huggingface hoac tuong duong)." -ForegroundColor DarkGray
Write-Host "  Neu gap loi xac thuc, chay:  $venvPy -m pip install -U huggingface_hub" -ForegroundColor DarkGray
Write-Host "  roi:  huggingface-cli login" -ForegroundColor DarkGray

Write-Host ""
Write-Host "== Kiem tra nhanh (best-effort) ==" -ForegroundColor Cyan
try {
    $torchCheck = & $venvPy -c "import torch; print('torch', torch.__version__, 'cuda_available=', torch.cuda.is_available())" 2>&1
    Write-Host "  $torchCheck" -ForegroundColor DarkGray
} catch {
    Write-Host "  [!!] Khong import duoc torch de kiem tra - xem log cai dat o tren." -ForegroundColor Red
}

Write-Host ""
Write-Host "OmniVoice install (best-effort) hoan tat." -ForegroundColor Green
Write-Host "Neu co buoc bao [!!], hay xu ly thu cong theo huong dan tuong ung o tren." -ForegroundColor Yellow
