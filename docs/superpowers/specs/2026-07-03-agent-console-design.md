# Agent Console — Design Spec

**Ngày:** 2026-07-03 · **Trạng thái:** design (chờ user duyệt) · **Vị trí:** `~/.mcp/agent-console`

## 1. Mục tiêu

Giao diện **web local, đàm thoại bằng giọng nói** để làm việc với **nhiều AI agent CLI** cùng lúc (Claude, Codex, Gemini), theo mô hình **Lead điều phối**: bạn nói → Claude (Lead) phân rã & giao việc cho các agent → tổng hợp → đọc trả lời. Tận dụng đồ đã có: **OmniVoice** (TTS, giọng clone), **faster-whisper** (STT), **PageIndex RAG** (tài liệu dài), governance **OpcOS core.md**.

## 2. Non-goals (YAGNI)
- KHÔNG dựng dashboard số liệu kinh doanh (đã có Power BI).
- KHÔNG điều khiển app GUI (Claude Desktop / Antigravity IDE) — chỉ CLI headless.
- KHÔNG train model / không cloud multi-user. Chạy 1 máy, 1 người.
- KHÔNG thay thế remote-control gốc — chỉ *bật* nó cho truy cập từ xa.

## 3. Kiến trúc (7 unit tách bạch)

```
FRONTEND (localhost, vanilla JS + WebSocket)
  push-to-talk · transcript nhiều làn (mỗi instance 1 màu/giọng) · phát audio
  · quản lý Agent Library & Instances · nạp context · điều khiển phiên
        │ WebSocket (2 chiều, streaming)
BACKEND (FastAPI, Python)
  stt              faster-whisper: audio → text                    [đã có]
  tts              OmniVoice: text → audio, profile riêng/instance  [đã có]
  agent_adapter    spawn CLI; 2 chế độ: session-bền (Claude) | one-shot+transcript
  orchestrator     vòng Lead điều phối; parse marker; chạy DELEGATE song song
  context_manager  quét folder / upload / link; định tuyến (doc dài → PageIndex)
  agent_library    quản lý agent .md; tạo/đặt tên instance
  web/ws           HTTP + WebSocket, phục vụ frontend
  blackboard       transcript chung = bus giao tiếp giữa agent + persist phiên
```

## 4. Đơn vị chi tiết

### 4.1 stt
Input audio (WAV/webm từ mic) → `faster-whisper` (đã dùng cho ASR verify) → text tiếng Việt. Interface: `transcribe(audio_bytes) -> str`. Lỗi → trả rỗng + UI cho gõ tay.

### 4.2 tts
`OmniVoice` (MCP/Python `.tts/omnivoice`) → audio. Mỗi instance gán 1 **voice profile** (mặc định `my-voice`; các instance khác dùng profile khác để phân biệt). Interface: `synth(text, profile) -> audio`. Lỗi → UI hiện text (không đọc).

### 4.3 agent_adapter
1 interface, nhiều engine. Spawn CLI headless, stream stdout.
- **Claude — session-bền:** `claude` với `--resume <session_id>` (hoặc Agent SDK session) → nhớ nhiều lượt; hỗ trợ **rename** (đổi tiêu đề) + **resume** session cũ + bật **remote-control**.
- **Codex:** `codex exec` (+ resume nếu có).
- **Gemini:** `gemini -p` (one-shot + transcript nếu chưa có session).
- Vai được "khoác" khi spawn: chèn **system-prompt của agent .md** (Claude: `--append-system-prompt` hoặc gọi subagent; Codex/Gemini: prefix prompt) + mở skill liên quan.
- Interface: `run(instance, prompt, context) -> stream[str]`. Timeout + cô lập lỗi.

### 4.4 orchestrator (Lead điều phối)
Vòng 1 lượt: STT → gửi cho **Lead (Claude)** → Lead phát **marker** → backend thực thi → gom blackboard → Lead tổng hợp → TTS.
Marker Lead phát ra:
```
[APPOINT codex=Coder, gemini=Researcher]           cấu hình vai instance cho task
[ATTACH coder-1: <path>; researcher-1: <doc_id>]   đính context đúng agent
[DELEGATE researcher-1:"..."; coder-1:"..."]        giao việc (song song nếu độc lập)
[SAY: <câu trả lời cuối>]                           đọc ra loa (giọng Lead)
[ASK: <hỏi lại người dùng>]                         đọc + chờ voice
```
Chống vô hạn: tối đa `N` vòng/lượt, cap số instance đồng thời, budget thời gian/token.

### 4.5 context_manager
- **Quét folder**: cây file (lọc loại, bỏ `node_modules`/`.git`, cap số/kích thước, tôn trọng `.gitignore`) → tick chọn.
- **Upload**: kéo-thả → lưu `workspace/` (gitignored).
- **Link/path/URL**: validate → gắn.
- **Định tuyến**: text ngắn → chèn thẳng; **doc dài (PDF…) → PageIndex RAG** (`pi_build_index`) → agent hỏi-đáp **trích trang**; URL → fetch text.
- **PROTECTED** (`.env*`, key, token, `.claude.json`…) → chặn, cảnh báo, không tự nạp.

### 4.6 agent_library
- **Agent .md** = `{name, role, engine, model, skills}` (frontmatter, chuẩn Claude subagent) + body (persona/kinh nghiệm/hướng dẫn).
- Nguồn: (1) tự quét `~/.opcos/plugins/*/agents`, `~/.claude/agents`, agent KPIM; (2) quét folder người dùng chỉ → nạp `.md`; (3) tạo mới / clone-sửa.
- **Instance**: từ 1 agent def → "Tạo CLI" → tên mặc định `<slug>-<n>` (vd `front-end-dev-1`), **đổi tên được**. Cho **nhiều instance** (cùng/khác agent) → đa nhiệm. Mỗi instance gán engine + voice profile.
- UI: xem/sửa/tạo/xoá/nhân bản agent; dựng/đặt tên/xoá instance.

### 4.7 blackboard + phiên
- Transcript chung `{speaker, role, content, refs, ts}`; instance đọc/ghi QUA orchestrator (không nói trực tiếp).
- Persist `sessions/*.jsonl` (roster instance + transcript) → **resume** phiên.
- **3 mức tự trị** (từ core.md): instance mặc định `suggest`; hành động chạm file/outward (ghi/push/đăng) cần `auto-safe`/`full` → **gate duyệt** trước khi thực thi thật. Mọi thao tác ghi hiện trong transcript.

## 5. Data flow (1 lượt điển hình)
🎙️ nói → stt → orchestrator gửi Lead → `[APPOINT]`/`[ATTACH]`/`[DELEGATE]` → agent_adapter chạy song song → blackboard → Lead `[SAY]` → tts (giọng Lead) → phát + transcript. Khi Lead trích ý agent khác → phát kèm giọng tương ứng.

## 6. Xử lý lỗi
- Instance timeout/crash/rỗng → ghi "‹tên› không phản hồi", Lead tổng hợp phần còn lại.
- STT/TTS lỗi → rơi về text.
- Runaway (quá N vòng / quá budget) → dừng + báo.
- Context lỗi (file không đọc được / PROTECTED) → bỏ qua + cảnh báo.

## 7. Tech stack
FastAPI + WebSocket (Python — cùng tiến trình với OmniVoice/Whisper, không cầu chéo) · frontend vanilla JS (không framework, nhẹ cho local) · venv riêng + `install.ps1` (đăng ký/khởi động, BOM, pattern powerbi-mcp) · tích hợp `pageindex-mcp` cho doc dài.

## 8. Bảo mật & governance
Kế thừa core.md (Safety 3 tầng, 3 mức tự trị). Không nạp PROTECTED. Chạy localhost mặc định; remote-control là opt-in. Không đưa nội dung `~/Brain` vào artifact phân phối.

## 9. Lộ trình (phân pha — chống phình, mỗi pha 1 plan riêng)
- **Phase 1 — MVP (plan đầu tiên):** web + push-to-talk + Whisper + OmniVoice + 3 engine từ config (Claude/Codex/Gemini, chưa cần UI library) + orchestrator Lead (APPOINT/DELEGATE/SAY) + blackboard + voice/agent + transcript. Claude session-resume cơ bản. Context = nhập path.
- **Phase 2:** Agent Library UI (quét/nạp/tạo .md) + instance có tên + đa nhiệm/nhân bản.
- **Phase 3:** context_manager đầy đủ (quét folder/upload) + định tuyến PageIndex RAG.
- **Phase 4:** rename/resume session UI + nút remote-control + gate tự trị hoàn chỉnh.

## 10. Assumptions
- **A1:** ✅ Gemini CLI đã cài (`@google/gemini-cli` v0.49.0, 2026-07-03) → MVP đủ 3 agent. Cần `gemini` auth Google/API key lần đầu (user tự làm).
- **A2:** Claude CLI hỗ trợ `--resume`/session id ổn định cho adapter (xác minh ở Phase 1; nếu không, dùng Agent SDK).
- **A3:** faster-whisper realtime đủ nhanh trên máy (GPU sẵn); nếu chậm → cân nhắc model nhỏ hơn.
- **A4:** OmniVoice độ trễ chấp nhận được cho hội thoại (không realtime tuyệt đối; chấp nhận 1-2s).
