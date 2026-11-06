---
name: orbit-control
description: "Introduce, install, start and stop OpcOS Orbit - the optional local web UI (localhost:7788) to manage and talk to several agents (Claude/Codex/Gemini). Windows only, requires OpcOS (OPCOS_ROOT). Use when: what is Orbit, install Orbit, start/open Orbit, stop/close Orbit, agent console, khoi dong/mo/bat agent console, mo giao dien quan ly agent, chay UI agent, tat/dong console, Orbit la gi, cai giao dien Orbit. Not: giao viec cho agent -> Agent tool."
---

# orbit-control — giới thiệu, cài, bật/tắt OpcOS Orbit

> Quy ước: `<opcos>` = gốc OpcOS = biến `OPCOS_ROOT`, mặc định `~/OpcOS` (biến trống thì dùng `$HOME\OpcOS`). `<orbit>` = `<opcos>\orbit`.

Orbit (trước gọi Agent Console) là repo git riêng, **tuỳ chọn**, ở `<opcos>\orbit`. "orbit / agent console / console / giao diện quản lý agent / UI agent" = CÙNG 1 thứ.

## Orbit là gì
Web local (chỉ nghe localhost, cổng 7788) để điều phối và đàm thoại với nhiều agent (Claude, Codex, Gemini/agy, Ollama): Mission Control theo dõi job working/blocked/done, voice STT/TTS (tuỳ chọn), System pane đọc registry của OpcOS. Nặng vài GB, cần Python 3.10–3.13. Không bắt buộc.

Dưới `full`: claude/codex chỉ đọc, gemini/agy bị từ chối; nâng `autonomy` trong `config.json` cục bộ (chi tiết: `README.md` Orbit).

## Cổng chặn (làm trước mọi việc)
Mỗi khối dưới đây tự suy lại `$opcos`/`$root` (mỗi lần gọi PowerShell là tiến trình mới).
```powershell
if ($env:OS -ne 'Windows_NT') { 'khong-ho-tro-os' } else {
  $opcos = if ($env:OPCOS_ROOT) { $env:OPCOS_ROOT } else { Join-Path $HOME 'OpcOS' }
  $root  = [IO.Path]::GetFullPath((Join-Path $opcos 'orbit')).TrimEnd('\')
  if (-not (Test-Path (Join-Path $opcos 'system'))) { 'thieu-opcos' }
  elseif (-not (Test-Path (Join-Path $root '.git'))) { 'chua-clone' }
  elseif (-not ((Test-Path (Join-Path $root '.venv\Scripts\uvicorn.exe')) -and (Test-Path (Join-Path $root 'config.json')))) { 'chua-install' }
  else { 'san-sang' }
}
```
- `khong-ho-tro-os` → báo «chưa hỗ trợ hệ điều hành này (Orbit chỉ chạy Windows)», **không chạy lệnh nào**, dừng.
- `thieu-opcos` → báo «thiếu OpcOS» (không thấy `<opcos>\system`; kiểm `OPCOS_ROOT`), dừng. Không tự cài OpcOS.
- `chua-clone` → mục **Chưa cài**. `chua-install` (thiếu `.venv` hoặc `config.json`) → mục **Thiếu venv**. `san-sang` → bật/tắt.

## Chưa cài (`chua-clone`)
Giải thích Orbit ngắn, **hỏi Đức có muốn cài không**; gật mới làm, không tự cài. Lệnh (chỉ nêu, chạy sau khi được gật):
1. Lệnh chính: `powershell -NoProfile -File <opcos>\system\operations\install.ps1 -Siblings opcos-orbit` (clone + cài plugin).
2. Phương án tay: `powershell -NoProfile -File <opcos>\system\operations\tasks\clone-sibling.ps1 -Id opcos-orbit`.
3. Rồi `<orbit>\install.ps1` (dựng venv + deps, tạo `config.json`; lần đầu lâu), rồi bật.

## Thiếu venv (`chua-install`)
Không clone lại. Nêu `<orbit>\install.ps1`, hỏi Đức, gật mới chạy; xong thì bật.

## Bật
Trigger: khởi động / mở / bật / chạy / launch / start / open + (orbit | agent console | console | giao diện agent | UI agent…). Chỉ khi cổng chặn ra `san-sang`:
```powershell
$opcos = if ($env:OPCOS_ROOT) { $env:OPCOS_ROOT } else { Join-Path $HOME 'OpcOS' }
$root  = [IO.Path]::GetFullPath((Join-Path $opcos 'orbit')).TrimEnd('\')
& (Join-Path $root 'run.ps1') -Detached   # chạy nền, PID ở .server.pid; run.ps1 mở trình duyệt
```
Báo: «Orbit đang chạy tại http://localhost:7788». Trạng thái khác `san-sang` → làm theo mục tương ứng.

## Tắt
Trigger: tắt / dừng / đóng / stop / turn off / kill + (orbit | console | giao diện agent | UI…).
**Chỉ dừng tiến trình đã xác minh là Orbit**, không kill mù theo cổng. Chạy MỘT khối:
```powershell
$port = 7788
$opcos = if ($env:OPCOS_ROOT) { $env:OPCOS_ROOT } else { Join-Path $HOME 'OpcOS' }
$root  = [IO.Path]::GetFullPath((Join-Path $opcos 'orbit')).TrimEnd('\')
$short = try { (New-Object -ComObject Scripting.FileSystemObject).GetFolder($root).ShortPath } catch { $root }
$pf = Join-Path $root '.server.pid'
function Get-P($i) { Get-CimInstance Win32_Process -Filter "ProcessId=$i" -ErrorAction SilentlyContinue }
function Test-InOrbit($p) { $e = "$($p.ExecutablePath)"; $c = "$($p.CommandLine)"
  ($e -and [IO.Path]::GetFullPath($e).StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) -or
  $c -match ('(?i)(' + [regex]::Escape($root) + '|' + [regex]::Escape($short) + ')(?=$|[\\"\s])') }
$fromFile = 0
if (Test-Path $pf) { $n = 0; if ([int]::TryParse(("$(Get-Content $pf -ErrorAction SilentlyContinue | Select-Object -First 1)").Trim(), [ref]$n) -and $n -gt 0) { $fromFile = $n } }
$cands = @(); if ($fromFile) { $cands += $fromFile }
$cands += @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object { [int]$_.OwningProcess })
$cands = @($cands | Where-Object { $_ -gt 0 } | Select-Object -Unique)
$handled = @(); $stopped = 0; $failed = 0; $any = $false
foreach ($id in $cands) {
  if ($handled -contains $id) { continue }
  $w = Get-P $id
  if (-not $w) { if ($id -eq $fromFile -and $stopped -eq 0) { "GONE pid=$id" }; continue }
  $chain = @($w); $cur = $w
  for ($k = 0; $k -lt 5; $k++) { $par = Get-P $cur.ParentProcessId
    if (-not $par -or $par.CreationDate -gt $cur.CreationDate) { break }; $chain += $par; $cur = $par }
  $sig = @($chain | Where-Object { "$($_.CommandLine)" -match 'uvicorn' -and "$($_.CommandLine)" -match 'server\.app' })
  $inO = @($chain | Where-Object { Test-InOrbit $_ })
  if ($sig.Count -gt 0 -and $inO.Count -gt 0) {
    $any = $true; $t = $sig[-1].ProcessId; $handled += @($chain | ForEach-Object { $_.ProcessId })
    taskkill /PID $t /T /F | Out-Null; Start-Sleep -Milliseconds 500
    if (Get-Process -Id $t -ErrorAction SilentlyContinue) { $failed++; "STOP-FAILED pid=$t" } else { $stopped++; "STOPPED pid=$t" }
  } else { "NOT-ORBIT pid=$id name=$($w.Name)" }
}
if ((Test-Path $pf) -and $failed -eq 0) { Remove-Item $pf -Force -ErrorAction SilentlyContinue; if (-not $any) { 'STALE-PIDFILE' } }
if ($cands.Count -eq 0) { 'NOT-RUNNING' }
```
Khối in mã ASCII; báo Đức bằng tiếng Việt:
- `STOPPED pid=N` đã tắt Orbit (cả cây). `STOP-FAILED pid=N` không tắt được, giữ `.server.pid`, nói Đức.
- `NOT-ORBIT pid=N name=X` PID N (X) giữ cổng/có trong `.server.pid` nhưng KHÔNG phải Orbit — không tắt, báo Đức.
- `GONE pid=N` `.server.pid` cũ, PID không còn. `STALE-PIDFILE` đã xoá `.server.pid` cũ/trỏ tiến trình lạ (không đụng tiến trình đó), Orbit không chạy. `NOT-RUNNING` Orbit không chạy.

- «Là Orbit» = chính nó hoặc tổ tiên (≤ 5 cấp) có `uvicorn` + `server.app` trong dòng lệnh, và có tiến trình trong chuỗi chạy từ dưới thư mục Orbit hoặc dòng lệnh chứa đúng đường Orbit (dài hoặc 8.3, có ranh giới: `orbit-old` không khớp). Venv Windows: `uvicorn.exe` → `python.exe` venv → python gốc ngoài thư mục (python gốc mới nghe cổng) — vẫn nhận nhờ tổ tiên. Chỉ tắt (`/T`) tổ tiên cao nhất **mang dấu `uvicorn`+`server.app`**; shell/editor cha không mang dấu thì sống.
- Orbit chạy từ worktree con **bên trong** thư mục Orbit cũng được coi là Orbit; nơi khác là lạ.
- Không gọi `stop.ps1` (không xác minh PID).

## Nguyên tắc
- Chỉ giới thiệu / cài (khi được gật) / bật / tắt + mở URL — không tự làm gì thêm trong Orbit.
- Liệt kê lệnh trước khi chạy nếu ở chế độ cần duyệt.
- Cổng mặc định 7788 (khớp `run.ps1`); đổi cổng thì sửa cả đây.
