# OpcOS Orbit — AGENTS.md (bàn giao cho phiên làm Orbit)

> File này là **gốc luật của repo**. `CLAUDE.md` chỉ trỏ về đây.
> Đặt ở repo thay vì memory vì **memory của Claude gắn theo thư mục làm việc** — phiên mở
> trong `~/.mcp/agent-console` KHÔNG thấy memory lưu từ phiên home-root. Bàn giao phải đi cùng repo.

Trạng thái khi bàn giao: HEAD `3a820c0`, 79/79 pytest, master clean, local-only (không remote).

---

## 🐞 VIỆC ĐẦU TIÊN — lỗi bảo mật: 3 mức tự trị đang là TRANG TRÍ

**Phát hiện + kiểm chứng 2026-08-09** (Codex nêu, đã tự verify bằng grep).

`check_autonomy(inst, action)` **có thật** ở `server/adapters.py:132` và **logic đúng**:

```
full       -> True
auto-safe  -> action in ("read", "draft", "query")
còn lại    -> action in ("read", "query")
```

Nhưng `grep -rn check_autonomy` cho thấy **chỉ `tests/test_adapters.py:24-25` gọi nó** — **không một đường thực thi production nào gọi**.

⇒ Instance khai `suggest` vẫn làm được mọi thứ engine cho phép. Cộng thêm `adapters.py:19`
hardcode `--dangerously-skip-permissions` cho engine `agy` (bắt buộc, không có thì agy treo)
⇒ **agy instance = toàn quyền máy bất kể tier khai báo**.

### Cần làm
1. Gọi `check_autonomy` ở **đúng biên side-effect** trong `orchestrator`/`adapters`, TRƯỚC khi chạy action.
2. **Fail-closed**: thiếu field `autonomy` → coi như `suggest`, không phải `full`.
3. Cách ly `agy`: chỉ giao việc chỉ-đọc, hoặc chạy trong sandbox riêng.
4. Thêm test chứng minh một instance `suggest` **không** thực hiện được action ghi — hiện tại
   test chỉ kiểm hàm thuần, không kiểm đường thực thi. Đó chính là lý do bug sống sót.

### Bối cảnh luật (đọc trước khi thiết kế)
- `~/.opcos/plugins/kpim-skills/instructions/core.md` — mục *Ba mức tự trị* (`suggest`/`auto-safe`/`full`)
  và *Multi-agent orchestration* (chuẩn gọi agent chéo).
- `~/.opcos/state/ENVELOPES.md` — mô hình "duyệt phạm vi một lần, không duyệt từng bước";
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

- **RESYNC public** `~/Code/opcos-orbit` (remote `github.com/ducnguyen221/opcos-orbit`, HEAD `b2af659`):
  copy `server/ web/ tests/` từ private sang, **re-neutralize default `"my-voice"` → `""`** ở đúng 5 file
  `server/`: `app.py:43 · config.py:8 · instances.py:16 · tts.py:21 · voice_setup.py`.
  `library.js:58` và tests **GIỮ** `"my-voice"` (là nhãn, không phải secret). Rồi pytest → commit →
  **PUSH là outward-facing, phải hỏi người**.
- Dogfood UI mới bằng ảnh (lần trước playwright ngắt giữa chừng, mới verify được chức năng).
- UAT delegate LIVE qua Lead + test mic voice — cần người, không tự làm được.
