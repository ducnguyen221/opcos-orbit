# OpcOS Orbit — AGENTS.md (bàn giao cho phiên làm Orbit)

> File này là **gốc luật của repo**. `CLAUDE.md` chỉ trỏ về đây.
> Đặt ở repo thay vì memory vì **memory của Claude gắn theo thư mục làm việc** — phiên mở
> trong `~/.mcp/agent-console` KHÔNG thấy memory lưu từ phiên home-root. Bàn giao phải đi cùng repo.

Trạng thái: nhánh mặc định `main` (remote `origin` trên GitHub); bộ test pytest nằm ở `tests/`.

---

## Trạng thái cổng tự trị (P9, 06/11/2026)

Lỗi cũ "3 mức tự trị chỉ là trang trí" **đã sửa** — đừng sửa lại cổng.

- `run_agent` (`server/adapters.py`) gọi `check_autonomy` ở biên side-effect, TRƯỚC khi spawn/gọi
  engine; lỗi hay thiếu/giá trị lạ của `autonomy` → coi như `suggest` (fail-closed).
- Dưới `full`: `claude`/`codex` chạy **chỉ-đọc** (cờ chỉ-đọc + prompt đi qua stdin, output có dòng
  `[chỉ-đọc]`); engine không có chế độ chỉ-đọc kiểm được (`gemini`, `agy`) bị **từ chối** trước khi
  chạy (`readonly_refusal`). `ollama` không có công cụ nên được chạy.
- Mức hiệu lực đi theo nguồn tin trên bus: tin từ nguồn không xác thực bị hạ mức.
- **Chỉ-đọc không phải cách ly**: instance chỉ-đọc vẫn **đọc được ổ đĩa** của máy chạy Orbit.
- Test: `tests/test_autonomy_gate.py` (đường thực thi), `tests/test_adapters.py`, `tests/test_orchestrator.py`.

**Việc còn mở** (chi tiết ở hồ sơ `~/OpcOS/system/docs/plans/2026-11-06-p9-orbit-plugin/`):
cwd cách ly theo instance + chặn ghi `config.json` (RF8); `stop.ps1` chưa xác minh pid là Orbit;
prompt còn nằm trong argv ở mức `full` (RF7); RF6, RF11, RF12 — **phải xử lý trước khi push bản công khai**;
khung `[ATTACH …]` thiếu dấu đóng.

### Bối cảnh luật (đọc trước khi đổi cổng)
- `~/OpcOS/system/governance/core.md` — mục *Safety & boundaries* (ba mức tự trị `suggest`/`auto-safe`/`full`
  ở `references/workflow-chi-tiet.md`) và *Multi-agent orchestration* (chuẩn gọi agent chéo).
- `~/OpcOS/system/state/ENVELOPES.md` — mô hình "duyệt phạm vi một lần, không duyệt từng bước";
  phép thử là **THÀNH VIÊN của phạm vi, không phải độ nặng** của hành động.
- Nguyên tắc nền: Brain `50_KNOWLEDGE/57_FRAMEWORKS/57.07_Harness_Engineering_Framework` mục *Memory & Knowledge (H7)*
  và #13/#14 (bảo mật nhiều lớp, lớp cuối ngoài tầm model).

---

## Chuẩn gọi Codex từ trong repo này

`codex exec` **không** nạp `core.md` (hook tự bỏ qua Codex) — nó đọc `~/.codex/AGENTS.md`.
Khi gọi Codex để review/sửa Orbit:

```bash
codex exec --sandbox read-only    --skip-git-repo-check "<prompt>" < /dev/null   # review/audit
codex exec --sandbox workspace-write --skip-git-repo-check "<prompt>" < /dev/null # implement
```

Hai cạm bẫy đã trả giá 1 tiếng ngày 09/08/2026:
- **Không đóng stdin (`< /dev/null`)** → `codex exec` chờ EOF vĩnh viễn. Tiến trình sống nhưng
  CPU đứng im. Phân biệt treo vs chạy bằng **CPU-time tăng theo thời gian**, không phải "còn sống".
- **Không ép `--sandbox`** → Codex dừng lại xin duyệt, không ai bấm, job vẫn báo `completed`.
  Kết quả kiểu *"vui lòng xác nhận…"* = **THẤT BẠI**, chạy lại, cấm báo là xong.

---

## Việc còn treo khác (từ memory `opcos-orbit`)

- **Bản công khai** `github.com/ducnguyen221/opcos-orbit` (remote `origin`, nhánh mặc định `main`): mặc định giọng
  đã trung hoà về `""` ở `app.py · config.py · instances.py · tts.py · voice_setup.py · web/library.js`
  (mẫu giọng cá nhân `assets/voices/my-voice.*` không theo dõi bởi git); tests giữ `"my-voice"` làm nhãn.
  Muốn đồng bộ lên bản công khai: pytest → commit → **PUSH là outward-facing, phải hỏi người**.
- Dogfood UI mới bằng ảnh (lần trước playwright ngắt giữa chừng, mới verify được chức năng).
- UAT delegate LIVE qua Lead + test mic voice — cần người, không tự làm được.
