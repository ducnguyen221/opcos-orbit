# OpcOS Orbit

Web local đàm thoại voice điều phối nhiều CLI agent (Claude Lead + Codex + Gemini/agy +
Ollama): nói (hoặc gõ) → STT → Lead phân việc bằng marker → tổng hợp → đọc trả lời (TTS) +
hiện transcript trực tiếp trên trình duyệt. Chạy trên nền [opcos](https://github.com/ducnguyen221/opcos)
— đọc agent library + registry từ đó.

> **Trạng thái (2026-07-08):** Phase 1-5 + **Console v2 "Mission Control"** đã xong —
> xem lịch sử ở `docs/superpowers/plans/`.

## Kiến trúc

- **Backend:** FastAPI + WebSocket (Python), cùng tiến trình với STT (faster-whisper)
  và gọi TTS qua OmniVoice (thư mục mặc định `~/.tts/omnivoice`, đổi bằng biến môi trường
  `OMNIVOICE_DIR`; gốc OpcOS mặc định `~/OpcOS`, đổi bằng `OPCOS_ROOT` — xem `server/paths.py`).
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

Yêu cầu: Python 3.11+ (đã kiểm với 3.12.10; `requirements.txt` không ghim phiên bản, chưa đo 3.14), các CLI đã cài + đăng nhập sẵn (chọn CLI nào dùng): `claude`,
`codex`, `gemini`/`agy`. **OmniVoice** (mặc định `~/.tts/omnivoice`, hoặc thư mục trong `OMNIVOICE_DIR`)
dùng cho Voice Studio/TTS — tuỳ chọn (tắt giọng vẫn dùng được console ở dạng text-only).

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
5. Kiểm tra `.venv` trong thư mục OmniVoice (mặc định `~/.tts/omnivoice`, hoặc `OMNIVOICE_DIR`) — nếu thiếu, tự copy + chạy
   `assets/omnivoice-install.ps1` (best-effort, không fail cứng cả script nếu thiếu GPU).

## Chạy

```powershell
.\run.ps1              # cửa sổ thấy được
.\run.ps1 -Detached     # chạy nền, đóng terminal thoải mái — tắt bằng .\stop.ps1
.\run.ps1 -WithMaus     # chạy kèm OpenMausBot (tuỳ chọn, xem dưới) — tắt bằng .\stop.ps1 -WithMaus
```

Mở `http://localhost:7788`. Nhấn giữ nút mic để nói (hoặc gõ text). Server **chỉ nghe localhost** và
API 7788 không xác thực người gọi — **đừng** bind `0.0.0.0` hay phơi cổng này ra mạng (không ngrok);
xem từ xa bằng cổng Kira bên dưới trên mạng riêng đã mã hoá.

## Duyệt quyền (PIN)

Khi một việc bị chặn vì mức tự trị (hiện là `gemini`/`agy` dưới `full`), Orbit tạo một **yêu cầu duyệt**
hết hạn sau 300 giây thay vì chỉ từ chối. Trong tab Mission Control, thẻ "Chờ duyệt" hiện đủ nội dung agent định
chạy; **Duyệt chạy một lần** cần PIN. Việc đó chạy đúng một lần với đúng nội dung đã lưu, không đổi `config.json`
hay `autonomy` của instance. Từ chối và Hoãn không cần PIN; chưa đặt PIN thì nút Duyệt bị tắt.

```powershell
python -m server.approvals set-pin     # chạy trong terminal; PIN >= 8 ký tự chữ-số ASCII; không có API đặt PIN
```

PIN lưu dạng băm scrypt tại `~/.secret/orbit/approval-pin.json` (đổi bằng `ORBIT_PIN_FILE`); đổi PIN cần khởi động lại
Orbit. Nhật ký duyệt ở `sessions/approvals.jsonl` (không ghi prompt/PIN). **Giới hạn:** PIN không chặn được một
tiến trình cục bộ cùng tài khoản gọi được HTTP có chủ đích.

## Cổng Kira (xem + dừng từ thiết bị phụ)

`server/kira_gateway.py` là tiến trình **riêng** cho thiết bị phụ (ESP32, điện thoại) trên mạng riêng: chỉ
`GET /kira/status`, `POST /kira/stop {job_id}`, `GET /kira/approvals`, `POST /kira/approvals/{id}/reject|defer`
(không có Approve). Mỗi tin ký HMAC-SHA256 trên `METHOD\nPATH\nTS\nNONCE\nBODY` (header `X-Kira-Ts`, `X-Kira-Nonce`,
`X-Kira-Sig`), cửa sổ ±30 s, nonce dùng một lần, allowlist IP, giới hạn tần suất.

```powershell
$env:KIRA_BIND = "<IP cụ thể của giao diện mạng riêng>"   # bắt buộc; không chấp nhận 0.0.0.0
$env:KIRA_ALLOWED_IPS = "<IP thiết bị>,<IP khác>"        # bắt buộc; rỗng = từ chối hết
python -m server.kira_gateway                            # khoá HMAC >= 32 byte ở ~/.secret/kira/hmac.key (KIRA_SECRET_FILE), cổng KIRA_PORT=7790
```

## Thêm một máy trạm (đa máy, tuỳ chọn — TẮT mặc định)

Hub (Orbit bạn đang mở) xem việc, **dừng việc, từ chối/hoãn thẻ duyệt** trên các máy phụ qua cổng Kira của chính họ
(`GET /api/fleet`, `POST /api/fleet/<tên>/jobs/<id>/stop`, `.../approvals/<id>/reject|defer`). **Không có Approve và không
giao việc mới** tới máy phụ. Không có `settings.peers` ⇒ chỉ thấy máy này. Chưa có mạng riêng mã hoá giữa các máy thì **đừng bật**:
HTTP không TLS (Tailscale/WireGuard mã hoá đường truyền), phản hồi không được ký.

1. **Mạng:** cài và đăng nhập Tailscale trên cả hub và máy phụ (việc của bạn). Ghi IP Tailscale của hai máy.
2. **Đồng bộ giờ** (NTP) ở cả hai máy: lệch quá ±30 giây ⇒ `unauthorized`; sau khi cổng Kira trên máy phụ khởi động lại, tin có
   thời điểm trước lúc khởi động bị từ chối — hub chậm giờ cũng thấy `unauthorized`.
3. **Trên hub, tạo khoá + ghim URL** (chạy tay, khoá không bao giờ được in ra):
   ```powershell
   python -m server.peer_keys gen <tên> --url http://<IP máy phụ>:7790   # tên chỉ [a-z0-9-], tối đa 32 ký tự
   python -m server.peer_keys show <tên>                                # dấu vân tay + URL ghim
   ```
   Tệp nằm ở thư mục khoá của hub (mặc định `~/.secret/orbit/peers`, đổi bằng `ORBIT_PEER_KEY_DIR`; **không** đổi được từ `config.json`).
4. **Chép khoá sang máy phụ** qua kênh an toàn (không chat/email; vd Taildrop hoặc `scp` qua Tailscale, rồi xoá bản trung gian và đặt
   quyền chỉ-chủ-sở-hữu cho tệp ở máy phụ) và đặt làm `KIRA_SECRET_FILE` của cổng Kira ở đó. So dấu vân tay: trên hub chạy `show <tên>`,
   trên máy phụ chạy `python -m server.peer_keys fingerprint <đường dẫn KIRA_SECRET_FILE>` (chỉ in vân tay) — **hai dấu phải giống nhau**.
   Mỗi cổng Kira chỉ có **một** khoá, dùng chung với Kira/phone của máy đó: **đổi khoá ở máy phụ thì phone/Kira của máy đó mất kết nối
   cho tới khi được cấp khoá mới**; **không dùng một khoá cho hai máy**.
5. **Trên máy phụ** chạy cổng Kira (xem mục trên) với `KIRA_BIND` = IP Tailscale của máy phụ, `KIRA_ALLOWED_IPS` = IP Tailscale của hub
   (+ thiết bị khác), tuỳ chọn `KIRA_MACHINE_NAME`.
6. **Đăng ký peer** trên hub trong `config.json`: `"settings": {"peers": [{"name": "<tên>", "url": "http://<IP máy phụ>:7790"}]}` —
   `url` phải **y hệt** URL đã ghim, nếu không hub từ chối (`pin_mismatch`). Chỉ nhận IP riêng/CGNAT (Tailscale)/ULA; không nhận tên máy.
7. **Kiểm:** `GET /api/fleet`. Mã lỗi ngắn từng máy: `no_key`, `no_pin`, `pin_mismatch`, `unauthorized` (sai khoá hoặc lệch giờ),
   `forbidden` (IP hub chưa nằm trong allowlist), `rate_limited`, `unreachable`, `timeout`, `bad_response`, `duplicate_*`.
8. **Thu hồi một máy:** đổi khoá trên máy phụ và bỏ IP hub khỏi allowlist của máy đó (xoá bản sao ở hub **không đủ** nếu khoá đã lộ;
   đổi khoá cũng ảnh hưởng Kira/phone của máy đó). Hub bị chiếm = lộ khoá mọi máy phụ — giữ hub như máy tin cậy nhất.

Giới hạn đã biết: khoá của cổng chưa có phạm vi theo route (khoá hub mở được mọi route cổng có); nhật ký của máy phụ chưa phân biệt
hub và phone; agent mức `full` cùng tài khoản đọc được thư mục khoá (rào hành vi, không phải rào máy).

## OpenMausBot (tuỳ chọn, ứng dụng bên thứ ba)

Thẻ **OpenMausBot** trong Orbit hiện trạng thái và nút mở ở tab riêng (OpenMausBot chặn nhúng khung có chủ ý).
Cài OpenMausBot vào `<OPCOS_ROOT>\plugins\openmausbot` (Node >= 24, pnpm), rồi:

```powershell
.\maus.ps1 start     # chế độ thường, chỉ 127.0.0.1:8799 (+ webhook :8800), HOME riêng + env đã lọc; -Dev chỉ để thử
.\maus.ps1 pair      # in mã ghép đôi dùng một lần để đăng nhập trình duyệt
.\maus.ps1 status    # .\maus.ps1 stop (xác minh PID trước khi tắt)
```

State ở `<OPCOS_ROOT>\workspaces\openmausbot`; cổng đổi bằng `ORBIT_MAUS_PORT`. Không có API khởi động/tắt.

## Sổ ghi nhận lượt agent

Orbit gọi CLI trực tiếp (ngoại lệ có tên của luật cầu `ask-*` — điều kiện ở `AGENTS.md`). Mỗi lượt vào
`sessions/agent-ledger.jsonl` (instance, engine, mức, nguồn lượt, kết quả, thời lượng; **không prompt**); dòng
"Hôm nay" trong Mission Control hiện số lượt và **trần mềm** 40/ngày/engine (`ORBIT_DAILY_SOFT_CAP`) — chỉ cảnh báo, không chặn.

## Cài như plugin của OpcOS

Orbit là thành phần tuỳ chọn của OpcOS (chỉ Windows, cần `OPCOS_ROOT`, mặc định `~/OpcOS`).
Cài cùng OpcOS: `install.ps1 -Siblings opcos-orbit` (của OpcOS) — clone Orbit vào `<OPCOS_ROOT>\orbit` và cài plugin `orbit`.
Cài plugin riêng:

```powershell
claude plugin marketplace add ducnguyen221/opcos-orbit
claude plugin install orbit@opcos-orbit
codex plugin marketplace add ducnguyen221/opcos-orbit
codex plugin add orbit@opcos-orbit
```

Plugin chỉ chứa skill `orbit-control` (giới thiệu / cài / bật / tắt Orbit); ứng dụng vẫn chạy từ thư mục `orbit` của OpcOS.
Nói «cài Orbit», «bật Orbit», «tắt Orbit» hoặc «mở agent console» để skill hướng dẫn.

## Cấu hình

Chỉnh sửa `config.json` (copy từ `config.example.json`):

```json
{
  "settings": { "max_rounds": 3, "cli_timeout": 120 },
  "instances": [
    { "name": "lead-1", "engine": "claude", "role": "Lead", "voice": "", "autonomy": "suggest" },
    { "name": "coder-1", "engine": "codex", "role": "Coder", "voice": "", "autonomy": "suggest" },
    { "name": "researcher-1", "engine": "agy", "role": "Researcher", "voice": "", "autonomy": "suggest" },
    { "name": "draft-1", "engine": "ollama", "role": "Drafter", "model": "qwen2.5:7b", "autonomy": "suggest" }
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
- `instances[].autonomy` — mức tự trị: `suggest` (mặc định) | `auto-safe` | `full`.
  **Dưới `full`, instance không ghi được gì**: `claude` và `codex` chạy ở chế độ chỉ-đọc
  (prompt đi qua stdin, bỏ cấu hình/MCP/hook của người dùng); `gemini` và `agy` không có
  chế độ chỉ-đọc kiểm được nên **bị từ chối** cho tới khi bạn nâng lên `full`; `ollama` không có
  công cụ nên không đổi. Muốn một instance ghi được (hoặc dùng `gemini`/`agy`): tự sửa
  `"autonomy": "full"` trong `config.json` cục bộ (không commit); API chỉ cho hạ mức, không
  cho nâng. Việc Lead giao chạy ở mức thấp nhất của Lead, instance đích và mọi người gửi tin trên bus được nạp vào prompt (mức hiệu lực của lượt gửi; tin từ API hoặc nguồn lạ tính là `suggest`). Cấu hình được đọc
  lại mỗi lượt hội thoại.
  **Lưu ý:** mức dưới `full` không ghi được nhưng vẫn ĐỌC được tệp (codex chỉ-đọc đọc được toàn đĩa và
  có công cụ web) — đừng giao instance mức thấp nội dung không tin cậy cạnh dữ liệu nhạy cảm.
- `instances[].skip_permissions` — chỉ `agy`: thêm cờ bỏ-qua-quyền khi và chỉ khi `autonomy` là `full`.
- `instances[].cwd` — tuỳ chọn: thư mục làm việc riêng của instance, **chỉ nhận đường dưới gốc workspace**
  (`<OPCOS_ROOT>\workspaces\orbit`, đổi bằng `ORBIT_WORKSPACE_ROOT`); mặc định `workspaces\orbit\<name>`. Agent không còn
  chạy trong thư mục mã của Orbit. **Giới hạn:** ghi bằng đường dẫn tuyệt đối ra ngoài thư mục này ở mức `full` vẫn được.
- Instance đang `full` không đổi `engine`/`role` qua API (409); chỉ sửa trong `config.json` cục bộ.

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
                 # config, stt, tts, system_info; approvals (duyệt + PIN), kira_gateway,
                 # ledger (sổ lượt agent), maus (trạng thái OpenMausBot), paths
maus.ps1         # khởi động/tắt/đăng nhập OpenMausBot (tuỳ chọn)
web/             # frontend tĩnh (index.html, app.js, dashboard.js, approvals.js, maus.js,
                 # ledger.js, style.css)
tests/           # pytest (unit, mock-based — không spawn CLI thật trong CI)
sessions/        # blackboard .jsonl (gitignored)
config.json      # cấu hình thật (gitignored) — copy từ config.example.json
docs/superpowers # spec + plan lịch sử (superpowers workflow)
```

## License

MIT.
