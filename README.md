# OpcOS Orbit

Web local đàm thoại voice điều phối nhiều CLI agent (Claude Lead + Codex + Gemini/agy +
Ollama): nói (hoặc gõ) → STT → Lead phân việc bằng marker → tổng hợp → đọc trả lời (TTS) +
hiện transcript trực tiếp trên trình duyệt. Chạy trên nền [opcos](https://github.com/ducnguyen221/opcos)
— đọc agent library + registry từ đó.

> **Trạng thái (2026-07-08):** Phase 1-5 + **Console v2 "Mission Control"** đã xong —
> xem lịch sử ở `docs/superpowers/plans/`.

## Kiến trúc

- **Backend:** FastAPI + WebSocket (Python), cùng tiến trình với STT (faster-whisper)
  và gọi TTS qua OmniVoice (`~/.tts/omnivoice`).
- **Orchestrator:** "Lead điều phối" — Lead (Claude) đọc transcript, phát ra marker
  `[DELEGATE inst:"task"]` để giao việc cho instance khác, hoặc `[SAY: ...]` khi đã
  có câu trả lời cuối, hoặc `[ASK: ...]` khi cần hỏi lại người dùng.
- **Adapter:** spawn từng CLI headless (`claude -p`, `codex exec`, `gemini -p`, `agy -p`)
  hoặc gọi thẳng Ollama HTTP local — gộp kết quả vào **blackboard** (transcript dùng
  chung, tự lưu `.jsonl`).
- **Jobs (Mission Control):** máy trạng thái working/blocked/done/error theo dõi từng
  job agent đang chạy — dashboard realtime + notify trình duyệt khi cần chú ý.
- **System pane:** đọc registry + MCP servers từ opcos đang cài trên máy để hiển thị
  bản đồ "máy này có gì".
- **Frontend:** vanilla JS — nút push-to-talk (MediaRecorder → base64 → WebSocket),
  transcript render theo speaker/role, phát audio trả lời.

## Cài đặt

Yêu cầu: Python 3.11+, các CLI đã cài + đăng nhập sẵn (chọn CLI nào dùng): `claude`,
`codex`, `gemini`/`agy`. **OmniVoice** (`~/.tts/omnivoice`) dùng cho Voice Studio/TTS —
tuỳ chọn (tắt giọng vẫn dùng được console ở dạng text-only).

```powershell
.\install.ps1
```

Script sẽ:
1. Tạo virtual environment `.venv` (nếu chưa có).
2. Cài dependencies từ `requirements.txt`.
3. Copy `config.example.json` → `config.json` nếu `config.json` chưa tồn tại
   (file `config.json` KHÔNG được commit — chứa cấu hình thật của bạn).
4. Kiểm tra `claude` / `codex` / `gemini` có trong PATH không, và in hướng dẫn
   xác thực nếu thiếu.
5. Kiểm tra `~/.tts/omnivoice/.venv` — nếu thiếu, tự copy + chạy
   `assets/omnivoice-install.ps1` (best-effort, không fail cứng cả script nếu thiếu GPU).

## Chạy

```powershell
.\run.ps1              # cửa sổ thấy được
.\run.ps1 -Detached     # chạy nền, đóng terminal thoải mái — tắt bằng .\stop.ps1
```

Mở `http://localhost:7788`. Nhấn giữ nút mic để nói (hoặc gõ text).

## Cấu hình

Chỉnh sửa `config.json` (copy từ `config.example.json`):

```json
{
  "settings": { "max_rounds": 3, "cli_timeout": 120 },
  "instances": [
    { "name": "lead-1", "engine": "claude", "role": "Lead", "voice": "" },
    { "name": "coder-1", "engine": "codex", "role": "Coder", "voice": "" },
    { "name": "researcher-1", "engine": "agy", "role": "Researcher", "voice": "" },
    { "name": "draft-1", "engine": "ollama", "role": "Drafter", "model": "qwen2.5:7b" }
  ]
}
```

- `settings.max_rounds` — số vòng delegate tối đa mỗi lượt hội thoại (chống runaway).
- `settings.cli_timeout` — timeout (giây) cho mỗi lần gọi CLI (mặc định 120s).
- `instances[].name` — id duy nhất, dùng trong marker `[DELEGATE name:"task"]`.
- `instances[].engine` — `claude` | `codex` | `gemini` | `agy` | `ollama`.
- `instances[].role` — vai trò (VD `Lead`, `Coder`, `Researcher`) — đưa vào system
  prompt để agent trả lời đúng vai. Đúng một instance nên có `role: "Lead"`.
- `instances[].voice` — voice profile OmniVoice khi đọc `[SAY: ...]` (để trống nếu
  không dùng TTS).
- `instances[].model` — chỉ dùng với engine `ollama` (mặc định `qwen2.5:7b`).

## Marker cố định

- `[DELEGATE inst:"task"; inst2:"task2"]` — Lead giao việc cho 1 hoặc nhiều instance.
- `[SAY: nội dung]` — câu trả lời cuối cùng, sẽ được đọc bằng TTS + hiện transcript.
- `[ASK: câu hỏi]` — Lead cần hỏi lại người dùng trước khi tiếp tục.
- `[APPOINT ...]`, `[ATTACH ...]` — gán/gắn agent + context vào phiên.

## Chạy test

```powershell
.venv\Scripts\python.exe -m pytest -v
```

## Cấu trúc thư mục

```
server/          # FastAPI app, orchestrator, adapters, jobs (state machine), blackboard,
                 # config, stt, tts, system_info
web/             # frontend tĩnh (index.html, app.js, dashboard.js, style.css)
tests/           # pytest (unit, mock-based — không spawn CLI thật trong CI)
sessions/        # blackboard .jsonl (gitignored)
config.json      # cấu hình thật (gitignored) — copy từ config.example.json
docs/superpowers # spec + plan lịch sử (superpowers workflow)
```

## License

MIT.
