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
**Chỉ dừng tiến trình đã xác minh là Orbit.** Không `Stop-Process -Force` mù theo cổng. Chạy MỘT khối (thu ứng viên, xác minh, dừng, xoá pid, báo):
```powershell
$opcos = if ($env:OPCOS_ROOT) { $env:OPCOS_ROOT } else { Join-Path $HOME 'OpcOS' }
$root  = [IO.Path]::GetFullPath((Join-Path $opcos 'orbit')).TrimEnd('\')
$pf = Join-Path $root '.server.pid'
$cands = @()
if (Test-Path $pf) { $n = 0; if ([int]::TryParse(("$(Get-Content $pf -ErrorAction SilentlyContinue | Select-Object -First 1)").Trim(), [ref]$n) -and $n -gt 0) { $cands += $n } }
$cands += @(Get-NetTCPConnection -LocalPort 7788 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { [int]$_.OwningProcess })
$cands = @($cands | Where-Object { $_ -gt 0 } | Select-Object -Unique)
$stopped = 0
foreach ($id in $cands) {
  $w = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
  if (-not $w) { "PID $id không còn chạy (tệp .server.pid cũ)."; continue }
  $cmd = "$($w.CommandLine)"; $exe = "$($w.ExecutablePath)"
  $ok = ($cmd -match 'uvicorn') -and ($cmd -match 'server\.app') -and
        ($exe -and [IO.Path]::GetFullPath($exe).StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase))
  if ($ok) { taskkill /PID $id /T /F | Out-Null; $stopped++; "Đã tắt Orbit (PID $id)." }
  else { "PID $id ($($w.Name)) KHÔNG phải Orbit của $root - không tắt." }
}
if ((Test-Path $pf) -and ($stopped -gt 0 -or -not (@($cands) | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue }))) { Remove-Item $pf -Force -ErrorAction SilentlyContinue }
if ($cands.Count -eq 0) { 'Orbit không chạy.' }
```
- Tiến trình lạ nghe 7788 (hoặc PID trong `.server.pid` đã bị tái dùng) → khối chỉ **báo PID + tên**, không tắt; nói lại cho Đức.
- «Là Orbit» = dòng lệnh có `uvicorn` + `server.app` và tệp chạy nằm dưới thư mục Orbit đó (không phân biệt hoa thường, đã chuẩn hoá tên 8.3). Orbit chạy từ một worktree con **bên trong** thư mục Orbit cũng được coi là Orbit; từ nơi khác thì coi là lạ.
- `stop.ps1` của Orbit chỉ kiểm PID trong `.server.pid` còn sống chứ không xác minh đó là Orbit, nên skill dùng khối trên thay vì gọi nó mù.

## Nguyên tắc
- Chỉ giới thiệu / cài (khi được gật) / bật / tắt + mở URL — không tự làm gì thêm trong Orbit.
- Liệt kê lệnh trước khi chạy nếu ở chế độ cần duyệt.
- Cổng mặc định 7788 (khớp `run.ps1`); đổi cổng thì sửa cả đây.
- Orbit cần OmniVoice (voice, tuỳ chọn) + Claude/Codex/Gemini CLI — chi tiết ở `README.md` Orbit và registry OpcOS (`opcos-orbit`).
