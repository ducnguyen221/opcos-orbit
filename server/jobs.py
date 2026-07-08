# -*- coding: utf-8 -*-
"""jobs.py — Job registry + máy trạng thái agent (Console v2 "Mission Control").

Distill hành vi từ herdr (AGPL — CHỈ tái hiện hành vi/pattern, không copy code):
- Trạng thái: working / blocked / done / error (+ cờ `seen`: done-chưa-xem hiển thị
  nổi bật kiểu herdr "Done", xem rồi thành lịch sử thường).
- BLOCKED không phải hẹn-giờ-im-lặng đơn thuần: cần (im lặng >= BLOCKED_SILENCE)
  VÀ đuôi output khớp chữ ký permission-prompt của CLI (bảng pattern distill từ
  manifest herdr cho claude/codex/gemini + chữ ký phổ quát confirm+cancel).
- Ưu tiên tổng hợp (aggregate): blocked > working > done(unseen) > idle.

Console chạy CLI HEADLESS (claude -p / codex exec / agy -p) nên không có TUI
chrome/OSC title — reader thread stream stdout theo dòng, giữ ring buffer đuôi
output làm "màn hình" để soi pattern.
"""
from __future__ import annotations

import itertools
import re
import subprocess
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field

# ---------------------------------------------------------------- patterns --
# Chữ ký BLOCKED theo engine (case-insensitive, soi trên ~8 dòng đuôi output).
# Nguồn hành vi: bảng manifest herdr §2 (claude.toml / codex.toml / gemini.toml).
_UNIVERSAL_BLOCKED = [
    r"do you want to proceed\?",
    r"would you like to",
    r"waiting for (user )?(permission|confirmation|approval)",
    r"\[y/n\]",
    r"\byes \(y\)",
    r"press enter to confirm",
    r"enter to (select|confirm|submit)",
    r"esc to cancel",
    r"do you trust the authors",
    r"allow (command|execution|this connection)\??",
    r"permission required",
]
_ENGINE_BLOCKED = {
    "claude": [r"bash command", r"tab to amend", r"ctrl\+e to explain",
               r"^\s*❯?\s*1\.\s*yes\b", r"^\s*2\.\s*no\b"],
    "codex": [r"allow command\?", r"enter to submit (answer|all)"],
    "gemini": [r"│ apply this change", r"│ allow execution", r"^\s*❯.*(yes|allow)"],
    "agy": [r"approve", r"skip[- ]permissions"],
    "ollama": [],
}
_BLOCKED_SILENCE = 8.0     # giây im lặng tối thiểu trước khi xét blocked
_COMPILED = {
    eng: [re.compile(p, re.IGNORECASE | re.MULTILINE)
          for p in _UNIVERSAL_BLOCKED + extra]
    for eng, extra in _ENGINE_BLOCKED.items()
}
_DEFAULT_COMPILED = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in _UNIVERSAL_BLOCKED]

_id_counter = itertools.count(1)
_LOCK = threading.Lock()
MAX_HISTORY = 60           # giữ tối đa N job trong sổ (job sống không bị cắt)


@dataclass
class Job:
    id: int
    instance: str
    engine: str
    prompt_preview: str
    started_at: float
    pid: int | None = None
    ended_at: float | None = None
    exit_code: int | None = None
    error: str = ""
    seen: bool = False                     # done-chưa-xem = nổi bật (herdr "Done")
    session_id: str | None = None
    _tail: deque = field(default_factory=lambda: deque(maxlen=8), repr=False)
    _full: deque = field(default_factory=lambda: deque(maxlen=4000), repr=False)  # trọn output cho Lead
    _last_output_at: float = 0.0
    _proc: subprocess.Popen | None = field(default=None, repr=False)
    _reader_thread: threading.Thread | None = field(default=None, repr=False)

    # ---- state machine ----
    def state(self, now: float | None = None) -> str:
        now = now or time.time()
        if self.ended_at is not None:
            if self.exit_code == 0 and not self.error:
                return "done"
            return "error"
        # đang sống
        silence = now - (self._last_output_at or self.started_at)
        if silence >= _BLOCKED_SILENCE and self._tail_matches_blocked():
            return "blocked"
        return "working"

    def _tail_matches_blocked(self) -> bool:
        text = "\n".join(self._tail)
        if not text.strip():
            return False
        pats = _COMPILED.get(self.engine, _DEFAULT_COMPILED)
        return any(p.search(text) for p in pats)

    def feed_line(self, line: str) -> None:
        line = line.rstrip("\r\n")
        self._full.append(line)
        if line.strip():
            self._tail.append(line[-300:])
        self._last_output_at = time.time()

    def full_output(self) -> str:
        return "\n".join(self._full)

    def finish(self, exit_code: int | None, error: str = "") -> None:
        self.ended_at = time.time()
        self.exit_code = exit_code
        self.error = error

    def to_dict(self) -> dict:
        now = time.time()
        st = self.state(now)
        return {
            "id": self.id,
            "instance": self.instance,
            "engine": self.engine,
            "prompt": self.prompt_preview,
            "state": st,
            "seen": self.seen,
            "pid": self.pid,
            "started_at": self.started_at,
            "elapsed": round((self.ended_at or now) - self.started_at, 1),
            "last_line": (self._tail[-1] if self._tail else ""),
            "silence": round(now - (self._last_output_at or self.started_at), 1),
            "exit_code": self.exit_code,
            "error": self.error,
        }


JOBS: "OrderedDict[int, Job]" = OrderedDict()


def create(instance: str, engine: str, prompt: str, session_id: str | None = None) -> Job:
    job = Job(id=next(_id_counter), instance=instance, engine=engine,
              prompt_preview=(prompt or "").strip().replace("\n", " ")[:120],
              started_at=time.time(), session_id=session_id)
    with _LOCK:
        JOBS[job.id] = job
        # cắt lịch sử: chỉ bỏ job ĐÃ KẾT THÚC cũ nhất
        while len(JOBS) > MAX_HISTORY:
            for jid, j in JOBS.items():
                if j.ended_at is not None:
                    JOBS.pop(jid, None)
                    break
            else:
                break
    return job


def attach_process(job: Job, proc: subprocess.Popen) -> None:
    job.pid = proc.pid
    job._proc = proc
    t = threading.Thread(target=_reader, args=(job, proc), daemon=True)
    job._reader_thread = t
    t.start()


def wait_output_flushed(job: Job, timeout: float = 5.0) -> None:
    """Sau proc.wait(): chờ reader thread xả nốt dòng cuối (tránh race mất đuôi output)."""
    t = job._reader_thread
    if t and t.is_alive():
        t.join(timeout=timeout)


def _reader(job: Job, proc: subprocess.Popen) -> None:
    """Stream stdout theo dòng → cập nhật tail/last_output (thay communicate blocking
    để máy trạng thái nhìn thấy output SỐNG). stderr gộp chung ở caller."""
    try:
        for line in iter(proc.stdout.readline, ""):
            job.feed_line(line)
    except Exception:
        pass


def mark_seen(job_id: int) -> bool:
    with _LOCK:
        j = JOBS.get(job_id)
        if j:
            j.seen = True
            return True
    return False


def mark_all_seen() -> int:
    n = 0
    with _LOCK:
        for j in JOBS.values():
            if not j.seen and j.ended_at is not None:
                j.seen = True
                n += 1
    return n


def list_jobs() -> list[dict]:
    with _LOCK:
        items = [j.to_dict() for j in JOBS.values()]
    order = {"blocked": 0, "working": 1, "error": 2, "done": 3}
    items.sort(key=lambda d: (order.get(d["state"], 9), -d["started_at"]))
    return items


def summary() -> dict:
    """Đếm nhanh cho glance/tab badge: '2 blocked · 1 working' (aggregation herdr)."""
    counts = {"blocked": 0, "working": 0, "done_unseen": 0, "error_unseen": 0}
    with _LOCK:
        for j in JOBS.values():
            st = j.state()
            if st == "blocked":
                counts["blocked"] += 1
            elif st == "working":
                counts["working"] += 1
            elif st == "done" and not j.seen:
                counts["done_unseen"] += 1
            elif st == "error" and not j.seen:
                counts["error_unseen"] += 1
    counts["attention"] = counts["blocked"] + counts["error_unseen"]
    return counts


def get(job_id: int) -> Job | None:
    with _LOCK:
        return JOBS.get(job_id)
