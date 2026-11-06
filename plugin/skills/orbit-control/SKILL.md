---
name: orbit-control
description: "Introduce, install, start and stop OpcOS Orbit - the optional local web UI (localhost:7788) to manage and talk to several agents (Claude/Codex/Gemini). Windows only, requires OpcOS (OPCOS_ROOT). Use when: what is Orbit, install Orbit, start/open Orbit, stop/close Orbit, agent console, khoi dong/mo/bat agent console, mo giao dien quan ly agent, chay UI agent, tat/dong console, Orbit la gi, cai giao dien Orbit. Not: giao viec cho agent -> Agent tool."
---

# orbit-control — giới thiệu, cài, bật/tắt OpcOS Orbit

> Quy ước: `<opcos>` = gốc OpcOS = biến `OPCOS_ROOT`, mặc định `~/OpcOS` (biến trống thì dùng `$HOME\OpcOS`). `<orbit>` = `<opcos>\orbit`.

Orbit (trước gọi Agent Console) là repo git riêng, **tuỳ chọn**, nằm ở `<opcos>\orbit`. Nghe keyword là **giới thiệu** / **cài** / **bật** / **tắt**, báo trạng thái gọn.
"orbit / agent console / console / giao diện tương tác / giao diện quản lý agent / UI agent" = CÙNG 1 thứ.

## Orbit là gì
Web local (chỉ nghe localhost, cổng 7788) để điều phối và đàm thoại với nhiều agent (Claude, Codex, Gemini/agy, Ollama): Mission Control theo dõi job working/blocked/done, voice STT/TTS (tuỳ chọn), System pane đọc registry của OpcOS. Nặng vài GB (venv + model), cần Python 3.10–3.13. Không bắt buộc — OpcOS chạy đủ không cần nó.

Mức tự trị: instance chạy dưới `full` thì claude/codex chỉ đọc, gemini/agy bị từ chối; nâng `autonomy` trong `config.json` cục bộ. Chi tiết ở `README.md` của Orbit — không lặp ở đây.

## Cổng chặn (làm trước mọi việc)
Mỗi lần gọi PowerShell là tiến trình mới: **mỗi khối dưới đây tự suy lại `$opcos`/`$root`**, đừng dựa biến của khối trước.
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
1. Lệnh chính: `powershell -NoProfile -File <opcos>\system\operations\install.ps1 -Siblings opcos-orbit` (install.ps1 của OpcOS: clone Orbit vào `<opcos>\orbit` và cài plugin).
2. Phương án tay: `powershell -NoProfile -File <opcos>\system\operations\tasks\clone-sibling.ps1 -Id opcos-orbit`.
3. Rồi `<orbit>\install.ps1` (dựng venv + deps, tạo `config.json`; lần đầu lâu, báo «đang cài lần đầu»), sau đó bật.
`<opcos>\orbit` bị `.gitignore` của OpcOS bỏ qua (repo riêng).

## Thiếu venv (`chua-install`)
Đừng clone lại. Nêu `<orbit>\install.ps1`, hỏi Đức, gật mới chạy; xong thì bật.

## Bật
Trigger: khởi động / mở / bật / chạy / launch / start / open + (orbit | agent console | console | giao diện agent | UI agent…). Chỉ khi cổng chặn ra `san-sang`:
```powershell
$opcos = if ($env:OPCOS_ROOT) { $env:OPCOS_ROOT } else { Join-Path $HOME 'OpcOS' }
$root  = [IO.Path]::GetFullPath((Join-Path $opcos 'orbit')).TrimEnd('\')
& (Join-Path $root 'run.ps1') -Detached   # chạy nền, PID ở .server.pid; run.ps1 mở trình duyệt
```
Báo: «Orbit đang chạy tại http://localhost:7788». Trạng thái khác `san-sang` → làm theo mục tương ứng, đừng bịa đường khác.

## Tắt
Trigger: tắt / dừng / đóng / stop / turn off / kill + (orbit | console | giao diện agent | UI…).
**Chỉ dừng tiến trình đã xác minh là Orbit.** Không `Stop-Process -Force` mù theo cổng. Chạy MỘT khối (thu ứng viên, xác minh, dừng, xoá pid, in mã):
```powershell
$port = 7788
$opcos = if ($env:OPCOS_ROOT) { $env:OPCOS_ROOT } else { Join-Path $HOME 'OpcOS' }
$root  = [IO.Path]::GetFullPath((Join-Path $opcos 'orbit')).TrimEnd('\')
$short = try { (New-Object -ComObject Scripting.FileSystemObject).GetFolder($root).ShortPath } catch { $root }
$pf = Join-Path $root '.server.pid'
function Get-P($i) { Get-CimInstance Win32_Process -Filter "ProcessId=$i" -ErrorAction SilentlyContinue }
function Test-InOrbit($p) { $e = "$($p.ExecutablePath)"; $c = "$($p.CommandLine)"
  ($e -and [IO.Path]::GetFullPath($e).StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) -or
  $c.IndexOf($root, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or $c.IndexOf($short, [StringComparison]::OrdinalIgnoreCase) -ge 0 }
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
  $marker = @($chain | Where-Object { "$($_.CommandLine)" -match 'uvicorn' -and "$($_.CommandLine)" -match 'server\.app' }).Count -gt 0
  $inO = @($chain | Where-Object { Test-InOrbit $_ })
  if ($marker -and $inO.Count -gt 0) {
    $any = $true; $t = $inO[-1].ProcessId; $handled += @($chain | ForEach-Object { $_.ProcessId })
    taskkill /PID $t /T /F | Out-Null; Start-Sleep -Milliseconds 500
    if (Get-Process -Id $t -ErrorAction SilentlyContinue) { $failed++; "STOP-FAILED pid=$t" } else { $stopped++; "STOPPED pid=$t" }
  } else { "NOT-ORBIT pid=$id name=$($w.Name)" }
}
if ((Test-Path $pf) -and $failed -eq 0) { Remove-Item $pf -Force -ErrorAction SilentlyContinue; if (-not $any) { 'STALE-PIDFILE' } }
if ($cands.Count -eq 0) { 'NOT-RUNNING' }
```
Khối in mã ASCII (tránh lỗi font); báo lại Đức bằng câu tiếng Việt:

| Mã | Báo |
|---|---|
| `STOPPED pid=N` | Đã tắt Orbit (PID N, cả cây tiến trình). |
| `STOP-FAILED pid=N` | Không tắt được PID N; giữ `.server.pid`, nói Đức, đừng thử cách mù. |
| `NOT-ORBIT pid=N name=X` | PID N (X) giữ cổng 7788 hoặc có trong `.server.pid` nhưng KHÔNG phải Orbit của máy này — không tắt, nhờ Đức xem. |
| `GONE pid=N` | `.server.pid` trỏ PID N đã không còn chạy (tệp cũ, đã xoá). |
| `STALE-PIDFILE` | `.server.pid` cũ/trỏ tiến trình lạ nên đã xoá (không đụng tiến trình đó); Orbit không chạy. |
| `NOT-RUNNING` | Orbit không chạy. |

- «Là Orbit» = chính tiến trình hoặc tổ tiên (tối đa 5 cấp) có `uvicorn` + `server.app` trong dòng lệnh, và có tiến trình trong chuỗi có tệp chạy dưới thư mục Orbit hoặc dòng lệnh chứa đường Orbit (không phân biệt hoa thường; cả tên dài lẫn 8.3). Trên Windows venv chạy `uvicorn.exe` → `python.exe` của venv → python gốc ngoài thư mục; python gốc nghe cổng vẫn được nhận nhờ tổ tiên. Khi tắt, khối dừng tổ tiên Orbit cao nhất rồi `/T` dọn cả cây.
- Orbit chạy từ một worktree con **bên trong** thư mục Orbit cũng được coi là Orbit; từ nơi khác thì coi là lạ.
- `stop.ps1` của Orbit chỉ kiểm PID trong `.server.pid` còn sống chứ không xác minh đó là Orbit, nên skill dùng khối trên thay vì gọi nó mù.

## Nguyên tắc
- Chỉ giới thiệu / cài (khi được gật) / bật / tắt + mở URL — không tự làm gì thêm trong Orbit.
- Liệt kê lệnh trước khi chạy nếu ở chế độ cần duyệt.
- Cổng mặc định 7788 (khớp `run.ps1`); đổi cổng thì sửa cả đây.
- Orbit cần OmniVoice (voice, tuỳ chọn) + Claude/Codex/Gemini CLI — chi tiết ở `README.md` Orbit và registry OpcOS (`opcos-orbit`).
