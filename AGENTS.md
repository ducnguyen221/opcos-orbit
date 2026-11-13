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

**Việc còn mở** (chi tiết ở hồ sơ `~/OpcOS/system/docs/plans/2026-11-06-p9-orbit-plugin/` và
`~/OpcOS/system/workshop-records/opcos-orbit/plans/2026-11-13-step6-orbit-maus/SPEC.md`):
mỗi instance đã có cwd riêng (`workspaces/orbit/<tên>`) nhưng **ghi bằng đường tuyệt đối ra ngoài cwd — kể cả
`config.json` — ở mức `full` vẫn được** (cần cờ sandbox của claude/codex, chưa đo; RF8 mới xong phần cwd);
prompt của claude ở mức `full` vẫn nằm trong argv (RF7: chỉ chặn việc prompt bắt đầu bằng `-` thành cờ);
API 7788 không xác thực người gọi (RF13); khung `[ATTACH …]` thiếu dấu đóng. RF6, RF11, RF12 và việc
`stop.ps1` xác minh pid đã xử lý (06b/6a, 13/11/2026).

## Ngoại lệ gọi CLI trực tiếp (Đức chốt phương án A, 13/11/2026)

Orbit gọi `claude`/`codex`/`gemini`/`agy` **trực tiếp**, không qua cầu `ask-*`. Đây là **ngoại lệ có tên** của luật
«đường đi duy nhất là cầu có governor» (`~/OpcOS/system/governance/core.md` mục *Multi-agent orchestration*):
Orbit là giao diện điều phối do chính người dùng mở và gõ tin vào, không phải agent tự gọi chéo. Ngoại lệ chỉ
đứng khi đủ **cả 5 điều kiện** — mất một điều kiện là hết ngoại lệ và phải quay về dùng cầu:

1. Lượt chỉ khởi từ **tin người gõ trong Orbit** (WebSocket) hoặc từ **việc người đã duyệt trên UI** (`approvals.run_approved`).
   Không có lịch, tiến trình nền hay CI tự khởi lượt.
2. Cổng tự trị ba mức giữ nguyên; mức hiệu lực = thấp nhất của Lead, instance đích và nguồn tin (`orchestrator._limit`);
   chỉ cổng duyệt (`override_level`, bước 5) nâng mức, một lần, đúng nội dung đã duyệt, kèm PIN.
3. Mọi lượt vào sổ `sessions/agent-ledger.jsonl` (`server/ledger.py`: nguồn lượt, mức, kết quả, thời lượng — không prompt);
   trần mềm 40 lượt/ngày/engine **chỉ cảnh báo**.
4. Orbit **không gọi `ask-*`**, không bật `allow_autocall`, không mở chuỗi quá `max_rounds` (3 vòng).
5. Sổ của Orbit và sổ cái của cầu là **hai sổ tách nhau**: Orbit không tiêu quota cầu, không có cầu dao — giới hạn đã biết, không phải thay thế governor.

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
