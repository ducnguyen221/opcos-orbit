import logging
import os
import subprocess
import threading
import time
from server.config import Instance

log = logging.getLogger(__name__)
import re
_CMD_META = re.compile('[&|<>^%"!\r\n]')
DANGEROUS_FLAG = "--dangerously-skip-permissions"

def _wants_dangerous(inst: Instance) -> bool:
    return (inst.engine == "agy" and getattr(inst, "skip_permissions", False) is True
            and _level(inst) == "full")


# Chế độ CHỈ-ĐỌC dưới mức full (P9, SPR-60 ma trận security mục 2). Cờ đứng TRƯỚC mọi nội dung
# lấy từ prompt; prompt đi qua stdin (không nằm trong argv — RF2/RF7). Engine không có tên ở đây
# (gemini, agy) không có chế độ chỉ-đọc kiểm được => bị TỪ CHỐI dưới full.
_READONLY = {
    "claude": ["-p", "--restricted", "--permission-mode", "plan", "--permission-prompts", "none",
               "--tools", "Read,Grep,Glob", "--strict-mcp-config", "--disable-slash-commands"],
    # `approval_policy=never` KHÔNG ngoặc kép: shim PowerShell 5.1 làm hỏng dấu `"`.
    "codex": ["exec", "--ignore-user-config", "--ignore-rules", "--sandbox", "read-only",
              "-c", "approval_policy=never", "--skip-git-repo-check"],
}


def _norm_level(level, inst) -> str:
    return level if isinstance(level, str) and level in _LEVELS else _level(inst)


def _uses_stdin(inst: Instance, level: str) -> bool:
    return level != "full" and inst.engine in _READONLY


_STRIP = {c: None for c in [*range(32), 127, ord(chr(34))]}   # ký tự điều khiển + dấu nháy kép


def _clean_role(role) -> str:
    """Role do người dùng đặt đi vào argv: bỏ dấu `"` (shim .ps1 PS 5.1 tách đối số) và ký tự
    điều khiển/xuống dòng. Loại bỏ chứ không từ chối để không chặn người dùng."""
    return str(role).translate(_STRIP)


def _limit_note(inst) -> str:
    r = getattr(inst, "limit_reason", None)
    return f" ({r})" if r else ""


def _advice(inst) -> str:
    if getattr(inst, "limit_untrusted", False):
        return ("bỏ tin không xác thực khỏi inbox (đừng dùng `POST /api/bus` cho tin cần quyền) "
                "rồi giao lại")
    if getattr(inst, "limit_reason", None):
        return 'nâng `autonomy` của nguồn giới hạn lên "full" trong config.json cục bộ'
    return 'nâng `autonomy` của instance này lên "full" trong config.json cục bộ'


def readonly_refusal(inst: Instance, level: str) -> str | None:
    """FR2/FR10: dưới full mà engine không có chế độ chỉ-đọc kiểm được (allowlist: chỉ claude/codex
    có cờ chỉ-đọc, ollama không có công cụ) => lý do từ chối (trước Popen)."""
    if level == "full" or inst.engine in _READONLY or inst.engine == "ollama":
        return None
    return (f"instance {inst.name} đang ở mức {level}{_limit_note(inst)}; engine {inst.engine} không có "
            f"chế độ chỉ-đọc kiểm được nên không chạy ở mức này. Muốn chạy: {_advice(inst)}.")


def build_command(inst: Instance, prompt: str, level: str | None = None) -> list[str]:
    """Chỉ gọi qua run_agent; không tự áp cổng (check_autonomy/readonly_refusal nằm ở run_agent)."""
    level = _norm_level(level, inst)
    role = _clean_role(inst.role)
    role_sys = f"Bạn đóng vai {role} trong một nhóm agent do Lead điều phối. Trả lời ngắn gọn, đúng vai."
    if _uses_stdin(inst, level):
        if inst.engine == "claude":
            cmd = ["claude"] + _READONLY["claude"] + ["--append-system-prompt", role_sys]
            session_id = getattr(inst, "session_id", "")
            if session_id:
                cmd += ["--resume", session_id]
            return cmd
        # KHÔNG thêm "-": `powershell -File` (PS 5.1) coi "-" trần là tên tham số rỗng và vỡ shim.
        # codex exec không có prompt đối số thì tự đọc stdin.
        return ["codex"] + _READONLY["codex"]
    if inst.engine == "claude":
        cmd = ["claude", "-p", prompt, "--append-system-prompt", role_sys]
        session_id = getattr(inst, "session_id", "")
        if session_id:
            cmd += ["--resume", session_id]
        return cmd
    if inst.engine == "codex":
        return ["codex", "exec", f"[{role}] {prompt}"]
    if inst.engine == "gemini":
        return ["gemini", "-p", f"[{role}] {prompt}"]
    if inst.engine == "agy":
        # Antigravity CLI (Google login free, không cần API key). Headless thiếu
        # --dangerously-skip-permissions thì có thể treo chờ duyệt tool (timeout sẽ kill).
        # AN TOÀN LÀ MẶC ĐỊNH: cờ chỉ thêm khi opt-in rõ (skip_permissions) VÀ autonomy=full.
        cmd = ["agy", "-p", f"[{role}] {prompt}"]
        if _wants_dangerous(inst):
            log.warning("agy %s chạy với %s (autonomy=full + skip_permissions)", inst.name, DANGEROUS_FLAG)
            cmd.append(DANGEROUS_FLAG)
        conv = getattr(inst, "session_id", "")
        if conv:
            cmd += ["--conversation", conv]
        return cmd
    raise ValueError(f"engine không hỗ trợ: {inst.engine}")

import shutil

def _resolve(name: str) -> list:
    """Windows: npm CLI là shim .cmd/.ps1 → subprocess không chạy tên trần (WinError 2).
    Resolve đường dẫn thật + launcher phù hợp. POSIX / .exe → chạy trực tiếp."""
    p = shutil.which(name)
    if not p:
        return [name]
    low = p.lower()
    if low.endswith((".cmd", ".bat")):
        # Ưu tiên .ps1 cùng tên (npm tạo sẵn): powershell -File nhận argv nguyên vẹn,
        # còn cmd /c diễn giải & | ^ % " trong prompt => chèn lệnh.
        ps1 = p[:-4] + ".ps1"
        if os.path.isfile(ps1):
            return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1]
        return ["cmd", "/c", p]
    if low.endswith(".ps1"):
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", p]
    return [p]

# Registry tiến trình agent đang chạy (để "tắt session" kill được hết task nền).
RUNNING: dict = {}   # pid -> subprocess.Popen

def _kill_tree(pid: int):
    """Kill cả CÂY tiến trình (shim .cmd đẻ node con — kill mình cha là không đủ)."""
    import os as _os
    if _os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=15)
    else:
        try:
            import signal
            _os.kill(pid, signal.SIGKILL)
        except Exception:
            pass

def stop_all_jobs() -> int:
    """Dừng MỌI tiến trình agent đang chạy. Trả về số job đã kill."""
    n = 0
    for pid in list(RUNNING.keys()):
        try:
            _kill_tree(pid); n += 1
        except Exception:
            pass
        RUNNING.pop(pid, None)
    return n

def _feed_stdin(p, text: str) -> None:
    """Ghi prompt vào stdin rồi đóng. Engine thoát sớm/đóng pipe => bỏ qua lỗi, không treo."""
    try:
        p.stdin.write(text)
        p.stdin.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        try:
            p.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            pass


def _run_ollama(inst: Instance, prompt: str, timeout: int, job) -> str:
    """Engine `ollama`: gọi HTTP server local (đang chạy sẵn cổng 11434) — agent phụ
    0 đồng/offline cho vai draft/tóm tắt/dịch. Model đặt ở inst.model, mặc định qwen2.5:7b.
    Dùng urllib (stdlib) — không thêm dependency `requests` (ladder stdlib-first)."""
    import json as _json
    import urllib.request
    import urllib.error
    model = getattr(inst, "model", "") or "qwen2.5:7b"
    role_sys = f"Bạn đóng vai {inst.role} trong một nhóm agent do Lead điều phối. Trả lời ngắn gọn, đúng vai, tiếng Việt."
    try:
        body = _json.dumps({
            "model": model, "stream": False,
            "messages": [{"role": "system", "content": role_sys},
                         {"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(
            "http://localhost:11434/api/chat", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        out = (data.get("message") or {}).get("content", "").strip()
        if job:
            job.feed_line(out.splitlines()[-1] if out else "")
            job.finish(0 if out else 1)
        return out if out else f"[ERROR] {inst.name}: ollama trả rỗng"
    except Exception as e:
        if job:
            job.finish(1, str(e))
        return f"[ERROR] {inst.name}: ollama — {e}"


def run_agent(inst: Instance, prompt: str, timeout: int = 120) -> str:
    from server import jobs
    job = jobs.create(inst.name, inst.engine, prompt,
                      session_id=getattr(inst, "session_id", None))
    # CỔNG TỰ TRỊ ở biên side-effect, TRƯỚC khi spawn/gọi engine. Fail-closed.
    action = "write" if _wants_dangerous(inst) else "query"
    try:
        allowed = check_autonomy(inst, action) is True
    except Exception:
        allowed = False
    if not allowed:
        msg = (f"instance {inst.name}: autonomy '{_level(inst)}' không cho phép action '{action}'. "
               f"Nâng `autonomy` lên \"full\" trong config.json cục bộ nếu thật sự cần.{_limit_note(inst)}")
        job.finish(1, msg)
        return f"[ERROR] {inst.name}: {msg}"
    if inst.engine == "ollama":
        return _run_ollama(inst, prompt, timeout, job)
    try:
        level = _level(inst)
        refusal = readonly_refusal(inst, level)
        if refusal:
            raise PermissionError(refusal)
        cmd = build_command(inst, prompt, level)
    except Exception as e:
        job.finish(1, str(e))
        return f"[ERROR] {inst.name}: {e}"
    real = _resolve(cmd[0]) + cmd[1:]
    if real[:2] == ["cmd", "/c"] and any(_CMD_META.search(a) for a in real[3:]):
        msg = "prompt chứa ký tự đặc biệt của cmd.exe (& | < > ^ % \" !) — từ chối chạy qua shim .cmd"
        job.finish(1, msg)
        return f"[ERROR] {inst.name}: {msg}"
    via_stdin = _uses_stdin(inst, level)
    stdin_text = (f"[{inst.role}] {prompt}" if inst.engine == "codex" else prompt) if via_stdin else None
    p = None
    try:
        # stderr GỘP vào stdout để reader thread thấy cả permission-prompt in ra stderr
        # (máy trạng thái blocked của jobs.py soi đuôi output sống — kiểu herdr).
        extra = {"stdin": subprocess.PIPE} if via_stdin else {}
        p = subprocess.Popen(real, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace", **extra)
        RUNNING[p.pid] = p
        jobs.attach_process(job, p)           # reader chạy trước khi ghi stdin (tránh bí pipe)
        deadline = time.monotonic() + timeout
        if via_stdin:
            feeder = threading.Thread(target=_feed_stdin, args=(p, stdin_text), daemon=True)
            feeder.start()
            feeder.join(timeout)
        try:
            p.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            _kill_tree(p.pid)
            job.finish(None, f"timeout {timeout}s")
            return f"[ERROR] {inst.name}: timeout {timeout}s"
        jobs.wait_output_flushed(job)          # chờ reader xả nốt dòng cuối (chống race)
        full = job.full_output()
        job.finish(p.returncode)
        result = full.strip()
        if not result:
            return f"[ERROR] {inst.name}: rỗng (exit {p.returncode})"
        if via_stdin:       # FR10: báo rõ đang chỉ-đọc (dòng riêng, tách khỏi output engine)
            result += (f"\n\n[chỉ-đọc] instance {inst.name} chạy ở mức {level}{_limit_note(inst)} — "
                       f"không ghi được tệp; muốn cho ghi: {_advice(inst)}")
        return result
    except Exception as e:
        job.finish(1, str(e))
        return f"[ERROR] {inst.name}: {e}"
    finally:
        if p: RUNNING.pop(p.pid, None)

_LEVELS = ("suggest", "auto-safe", "full")


def _level(inst) -> str:
    """Mức tự trị hợp lệ; thiếu/None/giá trị lạ => 'suggest' (fail-closed)."""
    level = getattr(inst, "autonomy", None)
    return level if isinstance(level, str) and level in _LEVELS else "suggest"


def check_autonomy(inst: Instance, action: str) -> bool:
    if not isinstance(action, str):
        return False
    level = _level(inst)
    if level == "full":
        return True
    if level == "auto-safe":
        return action in ("read", "draft", "query")
    return action in ("read", "query")
