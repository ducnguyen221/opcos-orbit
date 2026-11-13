# maus.ps1 - Khoi dong / tat / xem / dang nhap OpenMausBot (plugins/openmausbot) duoi HOME RIENG, chi nghe 127.0.0.1.
#   .\maus.ps1 start [-Port 8799] [-Dev]   Mac dinh: `openmausbot serve --local --no-open` (trinh duyet phai dang nhap
#                                           bang ma ghep doi dung mot lan). -Dev: dev-server (MOI trinh duyet/tien trinh
#                                           tren may nay la chu so huu - chi de thu, kem canh bao cua OpenMausBot).
#   .\maus.ps1 stop                        Xac minh PID that su la OpenMausBot (CommandLine + gio khoi tao) roi moi tat.
#   .\maus.ps1 status                      Hoi /api/health tren 127.0.0.1.
#   .\maus.ps1 pair                        In ma + lien ket dang nhap dung MOT LAN cho trinh duyet tren may nay.
# HOME rieng : <OpcOS>\workspaces\openmausbot\home      State: ...\data      Log/PID: ...\logs , .pid
# Moi truong : loc con vai bien he thong toi thieu (khong de khoa API cua phien goi lot sang bot).
param(
    [Parameter(Position = 0)][ValidateSet("start", "stop", "status", "pair")][string]$Action = "status",
    [int]$Port = 8799,
    [switch]$Dev
)
$ErrorActionPreference = "Stop"

$OpcRoot = Split-Path -Parent $PSScriptRoot
$P       = Join-Path $OpcRoot "plugins\openmausbot"
$W       = Join-Path $OpcRoot "workspaces\openmausbot"
$H       = Join-Path $W "home"
$pidFile = Join-Path $W ".pid"
$WebhookPort = $Port + 1          # OpenMausBot mac dinh nghe webhook o PORT+1

function Set-MausEnv {
    $keep = 'PATH','SystemRoot','SystemDrive','windir','ComSpec','PATHEXT','TEMP','TMP','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE','OS'
    Get-ChildItem Env: | Where-Object { $keep -notcontains $_.Name } | ForEach-Object { Remove-Item "Env:$($_.Name)" -ErrorAction SilentlyContinue }
    New-Item -ItemType Directory -Force (Join-Path $H "AppData\Local"), (Join-Path $H "AppData\Roaming"), (Join-Path $W "data"), (Join-Path $W "logs") | Out-Null
    $env:USERPROFILE = $H; $env:HOME = $H
    $env:APPDATA = Join-Path $H "AppData\Roaming"; $env:LOCALAPPDATA = Join-Path $H "AppData\Local"
    $env:OMB_DATA_DIR = Join-Path $W "data"
    $env:OMB_STATIC_DIR = Join-Path $P "dist"
    $env:OMB_PORT = "$Port"
}

function Test-PortBusy([int]$p) { [bool](Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue) }

function Get-MausProc {
    if (-not (Test-Path $pidFile)) { return $null }
    $info = Get-Content $pidFile -ErrorAction SilentlyContinue | ConvertFrom-Json
    if (-not $info) { return $null }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($info.pid)" -ErrorAction SilentlyContinue
    if (-not $proc) { return $null }
    # Chong PID bi tai su dung: CommandLine phai la script cua OpenMausBot VA tien trinh khoi tao sat gio da ghi.
    $okCmd = $proc.CommandLine -match 'openmausbot\.ts|dev-server\.ts'
    $okTime = $false
    try { $okTime = [math]::Abs(($proc.CreationDate - [datetime]$info.started).TotalSeconds) -lt 120 } catch {}
    [pscustomobject]@{ Info = $info; Proc = $proc; Verified = ($okCmd -and $okTime) }
}

switch ($Action) {
    "start" {
        if (-not (Test-Path (Join-Path $P "dist\index.html"))) { Write-Host "Chua build OpenMausBot (thieu $P\dist)." -ForegroundColor Red; exit 1 }
        $cur = Get-MausProc
        if ($cur -and $cur.Verified) { Write-Host "OpenMausBot da chay (PID $($cur.Info.pid))." -ForegroundColor Yellow; exit 0 }
        foreach ($pt in @($Port, $WebhookPort)) {
            if (Test-PortBusy $pt) { Write-Host "Cong $pt dang bi tien trinh khac chiem - khong khoi dong." -ForegroundColor Red; exit 1 }
        }
        Set-MausEnv
        if ($Dev) { $nodeArgs = @("--experimental-strip-types", "server/dev-server.ts") }
        else      { $nodeArgs = @("--experimental-strip-types", "server/openmausbot.ts", "serve", "--local", "--no-open", "--port", "$Port", "--data-dir", (Join-Path $W "data")) }
        $p = Start-Process node -ArgumentList $nodeArgs -WorkingDirectory $P -PassThru -WindowStyle Hidden `
                -RedirectStandardOutput (Join-Path $W "logs\out.log") -RedirectStandardError (Join-Path $W "logs\err.log")
        @{ pid = $p.Id; started = (Get-Date).ToString("o"); port = $Port; mode = $(if ($Dev) { "dev" } else { "serve" }) } | ConvertTo-Json | Set-Content $pidFile
        $up = $false
        for ($i = 0; $i -lt 45; $i++) {
            Start-Sleep 1
            if ($p.HasExited) { Write-Host "Server thoat som - xem $W\logs\err.log" -ForegroundColor Red; exit 1 }
            try { if ((Invoke-WebRequest "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { $up = $true; break } } catch {}
        }
        if (-not $up) { Write-Host "OpenMausBot chua tra loi /api/health sau 45s - xem logs." -ForegroundColor Yellow; exit 1 }
        Write-Host "OpenMausBot chay (PID $($p.Id)) tai http://127.0.0.1:$Port . Dang nhap lan dau: .\maus.ps1 pair . Tat: .\maus.ps1 stop" -ForegroundColor Green
    }
    "stop" {
        $cur = Get-MausProc
        if (-not $cur) { Write-Host "Khong co OpenMausBot dang chay (theo .pid)." -ForegroundColor Yellow; Remove-Item $pidFile -Force -ErrorAction SilentlyContinue; exit 0 }
        if (-not $cur.Verified) {
            Write-Host "PID $($cur.Info.pid) KHONG xac minh duoc la OpenMausBot (CommandLine: $($cur.Proc.CommandLine)) - khong giet." -ForegroundColor Red; exit 1
        }
        taskkill /T /F /PID $cur.Info.pid | Out-Null
        Start-Sleep 1
        if (Get-Process -Id $cur.Info.pid -ErrorAction SilentlyContinue) { Write-Host "Chua tat duoc PID $($cur.Info.pid)." -ForegroundColor Red; exit 1 }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        Write-Host "Da tat OpenMausBot (PID $($cur.Info.pid))." -ForegroundColor Green
    }
    "status" {
        try {
            $h = Invoke-WebRequest "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 3
            if (($h.Content | ConvertFrom-Json).app -eq "openmausbot") { Write-Host "OpenMausBot DANG CHAY tai http://127.0.0.1:$Port" -ForegroundColor Green; exit 0 }
        } catch {}
        Write-Host "OpenMausBot chua chay o cong $Port." -ForegroundColor Yellow
    }
    "pair" {
        Set-MausEnv
        Set-Location $P
        & node --experimental-strip-types server/openmausbot.ts pair --data-dir (Join-Path $W "data")
    }
}
