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
```powershell
$isWin = ($env:OS -eq 'Windows_NT')
if (-not $isWin) { 'khong-ho-tro-os' } else {
  $opcos = if ($env:OPCOS_ROOT) { $env:OPCOS_ROOT } else { Join-Path $HOME 'OpcOS' }
  $root  = Join-Path $opcos 'orbit'
  if (-not (Test-Path (Join-Path $opcos 'system'))) { 'thieu-opcos' }
  elseif (-not (Test-Path (Join-Path $root '.git'))) { 'chua-clone' }
  elseif (-not (Test-Path (Join-Path $root '.venv\Scripts\uvicorn.exe'))) { 'chua-install' }
  else { 'san-sang' }
}
```
- `khong-ho-tro-os` → báo «chưa hỗ trợ hệ điều hành này (Orbit chỉ chạy Windows)», **không chạy lệnh nào**, dừng.
- `thieu-opcos` → báo «thiếu OpcOS» (không thấy `<opcos>\system`; kiểm `OPCOS_ROOT`), dừng. Không tự cài OpcOS.
- `chua-clone` → mục **Chưa cài**. `chua-install` → mục **Thiếu venv**. `san-sang` → bật/tắt.

## Chưa cài (`chua-clone`)
Giải thích Orbit ngắn, **hỏi Đức có muốn cài không**; gật mới làm, không tự cài. Lệnh (chỉ nêu, chạy sau khi được gật):
1. Lệnh chính: `powershell -NoProfile -File <opcos>\system\operations\install.ps1 -Siblings opcos-orbit` (install.ps1 của OpcOS: clone Orbit vào `<opcos>\orbit` và cài plugin).
2. Phương án tay: `powershell -NoProfile -File <opcos>\system\operations\tasks\clone-sibling.ps1 -Id opcos-orbit`.
3. Rồi `<orbit>\install.ps1` (dựng venv + deps, tạo `config.json`; lần đầu lâu, báo «đang cài lần đầu»), sau đó bật.
`<opcos>\orbit` bị `.gitignore` của OpcOS bỏ qua (repo riêng).

## Thiếu venv (`chua-install`)
Đừng clone lại. Nêu `<orbit>\install.ps1`, hỏi Đức, gật mới chạy; xong thì bật.

## Bật
Trigger: khởi động / mở / bật / chạy / start / open + (orbit | agent console | giao diện agent | UI agent…). Chỉ khi `san-sang`:
```powershell
& (Join-Path $root 'run.ps1') -Detached   # chạy nền, PID ở .server.pid; run.ps1 mở trình duyệt
```
Báo: «Orbit đang chạy tại http://localhost:7788». Trạng thái khác `san-sang` → làm theo mục tương ứng, đừng bịa đường khác.

## Tắt
Trigger: tắt / dừng / đóng / stop / turn off / kill + (orbit | console | giao diện agent | UI…).
**Chỉ dừng tiến trình đã xác minh là Orbit.** Không `Stop-Process -Force` mù theo cổng.

Bước 1 — tìm ứng viên (xong chưa kill gì):
```powershell
$cands = @()
$pf = Join-Path $root '.server.pid'
if (Test-Path $pf) { $p = [int](Get-Content $pf -ErrorAction SilentlyContinue | Select-Object -First 1); if ($p) { $cands += $p } }
$listen = Get-NetTCPConnection -LocalPort 7788 -State Listen -ErrorAction SilentlyContinue
if ($listen) { $cands += ($listen.OwningProcess | Select-Object -Unique) }
$cands = $cands | Select-Object -Unique
```
Bước 2 — xác minh từng ứng viên (CIM, dòng lệnh + đường tệp chạy):
```powershell
$isOrbit = { param($id)
  $w = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
  if (-not $w) { return $false }
  $cmd = "$($w.CommandLine)"; $exe = "$($w.ExecutablePath)"
  ($cmd -match 'uvicorn') -and ($cmd -match 'server\.app') -and
  ($exe.StartsWith($root, [StringComparison]::OrdinalIgnoreCase) -or $cmd.IndexOf($root, [StringComparison]::OrdinalIgnoreCase) -ge 0)
}
```
- Ứng viên qua `$isOrbit` → dừng cây của nó: `taskkill /PID <id> /T /F` (uvicorn có thể có worker con), xoá `.server.pid`, báo «Orbit đã tắt».
- Ứng viên **không** qua (tiến trình lạ nghe 7788, hoặc PID trong `.server.pid` đã bị tái dùng) → **báo cho Đức** (PID, tên tiến trình) và **không tắt**. `.server.pid` trỏ PID không còn/không phải Orbit thì chỉ báo là tệp cũ.
- Không có ứng viên → «Orbit không chạy».
`stop.ps1` của Orbit chỉ kiểm PID trong `.server.pid` còn sống chứ không xác minh đó là Orbit, nên skill dùng cách xác minh trên thay vì gọi nó mù.

## Nguyên tắc
- Chỉ giới thiệu / cài (khi được gật) / bật / tắt + mở URL — không tự làm gì thêm trong Orbit.
- Liệt kê lệnh trước khi chạy nếu ở chế độ cần duyệt.
- Cổng mặc định 7788 (khớp `run.ps1`); đổi cổng thì sửa cả đây.
- Orbit cần OmniVoice (voice, tuỳ chọn) + Claude/Codex/Gemini CLI — chi tiết ở `README.md` Orbit và registry OpcOS (`opcos-orbit`).
