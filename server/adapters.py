import subprocess
from server.config import Instance

def build_command(inst: Instance, prompt: str) -> list[str]:
    role_sys = f"Bạn đóng vai {inst.role} trong một nhóm agent do Lead điều phối. Trả lời ngắn gọn, đúng vai."
    if inst.engine == "claude":
        cmd = ["claude", "-p", prompt, "--append-system-prompt", role_sys]
        session_id = getattr(inst, "session_id", "")
        if session_id:
            cmd += ["--resume", session_id]
        return cmd
    if inst.engine == "codex":
        return ["codex", "exec", f"[{inst.role}] {prompt}"]
    if inst.engine == "gemini":
        return ["gemini", "-p", f"[{inst.role}] {prompt}"]
    if inst.engine == "agy":
        # Antigravity CLI (Google login free, không cần API key). Headless cần
        # --dangerously-skip-permissions (không sẽ treo chờ duyệt tool). Session = --conversation.
        cmd = ["agy", "-p", f"[{inst.role}] {prompt}", "--dangerously-skip-permissions"]
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
    if inst.engine == "ollama":
        return _run_ollama(inst, prompt, timeout, job)
    cmd = build_command(inst, prompt)
    real = _resolve(cmd[0]) + cmd[1:]
    p = None
    try:
        # stderr GỘP vào stdout để reader thread thấy cả permission-prompt in ra stderr
        # (máy trạng thái blocked của jobs.py soi đuôi output sống — kiểu herdr).
        p = subprocess.Popen(real, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace")
        RUNNING[p.pid] = p
        jobs.attach_process(job, p)
        try:
            p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(p.pid)
            job.finish(None, f"timeout {timeout}s")
            return f"[ERROR] {inst.name}: timeout {timeout}s"
        jobs.wait_output_flushed(job)          # chờ reader xả nốt dòng cuối (chống race)
        full = job.full_output()
        job.finish(p.returncode)
        result = full.strip()
        return result if result else f"[ERROR] {inst.name}: rỗng (exit {p.returncode})"
    except Exception as e:
        job.finish(1, str(e))
        return f"[ERROR] {inst.name}: {e}"
    finally:
        if p: RUNNING.pop(p.pid, None)

def check_autonomy(inst: Instance, action: str) -> bool:
    level = getattr(inst, "autonomy", "suggest")
    if level == "full":
        return True
    if level == "auto-safe":
        return action in ("read", "draft", "query")
    return action in ("read", "query")
