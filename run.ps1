# run.ps1 - Khoi dong OpcOS Orbit server + mo trinh duyet
#   -Detached : chay NEN (khong cua so, song doc lap terminal - kieu herdr detach).
#               Dung .\stop.ps1 de tat. PID ghi o .server.pid
param([switch]$Detached)
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path ".venv\Scripts\uvicorn.exe")) {
    Write-Host "Chua cai dat. Hay chay '.\install.ps1' truoc." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path "config.json")) {
    Write-Host "Chua co config.json. Hay chay '.\install.ps1' truoc (hoac tu copy config.example.json -> config.json)." -ForegroundColor Red
    exit 1
}

$port = 7788
$url = "http://localhost:$port"

Write-Host "Khoi dong OpcOS Orbit tai $url ..." -ForegroundColor Cyan

try {
    $lanIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
        Where-Object { $_.InterfaceAlias -notmatch "Loopback" -and $_.IPAddress -notlike "169.254.*" } |
        Select-Object -First 1 -ExpandProperty IPAddress)
    if ($lanIp) {
        Write-Host "Truy cap tu dien thoai/may khac trong cung mang LAN: http://${lanIp}:$port" -ForegroundColor DarkGray
    }
} catch {
    # bo qua neu khong lay duoc IP LAN
}
Write-Host "Muon truy cap tu xa (ngoai mang LAN): dung panel 'Remote control' tren web, hoac xem huong dan trong /api/remote/toggle." -ForegroundColor DarkGray
Write-Host "Mac dinh server CHI lang nghe localhost (an toan). Bat 'Remote' tren panel se thu goi 'claude remote-control on' neu CLI ho tro." -ForegroundColor DarkGray

if ($Detached) {
    # Detach that su (distill herdr): server song doc lap cua so goi no.
    $existing = $null
    if (Test-Path ".server.pid") {
        $oldPid = Get-Content ".server.pid" -ErrorAction SilentlyContinue
        $existing = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
    }
    if ($existing) {
        Write-Host "Server da chay nen (PID $($existing.Id))." -ForegroundColor Yellow
    } else {
        $p = Start-Process -FilePath ".venv\Scripts\uvicorn.exe" `
            -ArgumentList "server.app:app", "--port", "$port" `
            -WorkingDirectory $root -WindowStyle Hidden -PassThru
        $p.Id | Set-Content ".server.pid"
        Write-Host "Server chay NEN (PID $($p.Id)) - dong terminal thoai mai. Tat: .\stop.ps1" -ForegroundColor Green
    }
    Start-Process $url
    exit 0
}

Start-Process $url

& ".venv\Scripts\uvicorn.exe" server.app:app --port $port
