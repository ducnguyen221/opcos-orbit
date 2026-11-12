# stop.ps1 - Tat OpcOS Orbit server dang chay nen (di cap voi run.ps1 -Detached)
#   -WithMaus : tat ca OpenMausBot (di cap voi run.ps1 -WithMaus) qua .\maus.ps1 stop
param([switch]$WithMaus)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if ($WithMaus) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "maus.ps1") stop
}

if (-not (Test-Path ".server.pid")) {
    Write-Host "Khong thay .server.pid - server khong chay nen (hoac dang chay foreground)." -ForegroundColor Yellow
    exit 0
}
$srvPid = Get-Content ".server.pid" -ErrorAction SilentlyContinue
$proc = Get-CimInstance Win32_Process -Filter "ProcessId=$srvPid" -ErrorAction SilentlyContinue
if ($proc) {
    # Xac minh PID that su la Orbit (uvicorn server.app:app) truoc khi giet - chong PID bi tai su dung.
    if ($proc.CommandLine -notmatch 'server\.app:app') {
        Write-Host "PID $srvPid KHONG phai Orbit (CommandLine: $($proc.CommandLine)) - khong giet." -ForegroundColor Red
        exit 1
    }
    # kill ca cay (uvicorn co the co worker con)
    taskkill /PID $srvPid /T /F | Out-Null
    Write-Host "Da tat server (PID $srvPid)." -ForegroundColor Green
} else {
    Write-Host "PID $srvPid khong con chay." -ForegroundColor Yellow
}
Remove-Item ".server.pid" -Force -ErrorAction SilentlyContinue
