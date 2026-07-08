# stop.ps1 - Tat OpcOS Orbit server dang chay nen (di cap voi run.ps1 -Detached)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path ".server.pid")) {
    Write-Host "Khong thay .server.pid - server khong chay nen (hoac dang chay foreground)." -ForegroundColor Yellow
    exit 0
}
$srvPid = Get-Content ".server.pid" -ErrorAction SilentlyContinue
$proc = Get-Process -Id $srvPid -ErrorAction SilentlyContinue
if ($proc) {
    # kill ca cay (uvicorn co the co worker con)
    taskkill /PID $srvPid /T /F | Out-Null
    Write-Host "Da tat server (PID $srvPid)." -ForegroundColor Green
} else {
    Write-Host "PID $srvPid khong con chay." -ForegroundColor Yellow
}
Remove-Item ".server.pid" -Force -ErrorAction SilentlyContinue
