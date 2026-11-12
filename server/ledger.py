"""Sổ ghi nhận lượt agent của Orbit (bước 6c, nhịp 1 của D3) + trần mềm.

Orbit gọi CLI agent trực tiếp (không qua cầu `ask-*`), nên các lượt này KHÔNG vào sổ cái/trần 40 lượt của cầu.
Sổ này là bù đắp tối thiểu và trung thực: mỗi lượt một dòng JSONL — thời điểm, instance, engine, mức, NGUỒN lượt
(`trigger`), kết quả, thời lượng. Không ghi prompt, không ghi output. Trần mềm CHỈ cảnh báo (ok/warn/over),
KHÔNG chặn. `trigger` chỉ ghi dòng dõi, không phán quyết chính sách autocall:
  human_turn    lượt Lead mở ra từ tin người gõ trong Orbit (và các vòng Lead nhận kết quả của lượt đó)
  lead_delegate việc do output của Lead giao đi — dữ liệu do model quyết, không phải chỉ thị của người (S2/S7)
  approved      việc đã được người duyệt trên UI và chạy một lần (giao thức duyệt, bước 5)
  direct        gọi trực tiếp khác (không qua điều phối)
Ghi sổ không bao giờ làm hỏng lượt chạy: lỗi IO bị nuốt (đếm trong RAM vẫn đúng).
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar

DEFAULT_SOFT_CAP = 40          # theo trần mềm của cầu ask-* (40 lượt/ngày/chiều)
LOG_MAX_BYTES = 1_000_000
TRIGGERS = ("direct", "human_turn", "lead_delegate", "approved")
OUTCOMES = ("ok", "error", "pending_approval")

_TRIGGER: ContextVar[str] = ContextVar("orbit_trigger", default="direct")


@contextmanager
def trigger(name: str):
    token = _TRIGGER.set(name if name in TRIGGERS else "direct")
    try:
        yield
    finally:
        _TRIGGER.reset(token)


def current_trigger() -> str:
    return _TRIGGER.get()


def soft_cap_from_env() -> int:
    raw = os.environ.get("ORBIT_DAILY_SOFT_CAP", "")
    if raw.isascii() and raw.isdecimal() and 1 <= int(raw) <= 10_000:
        return int(raw)
    return DEFAULT_SOFT_CAP


class Ledger:
    def __init__(self, path: str, now=time.time, soft_cap: int | None = None):
        self.path, self._now, self._cap = path, now, soft_cap
        self._lock = threading.Lock()
        self._day = None
        self._engines: dict = {}
        self._triggers: dict = {}
        self._outcomes: dict = {}

    def _today(self) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(self._now()))

    def _roll(self) -> None:
        """Đổi ngày => đếm lại; lần đầu => nạp các dòng của hôm nay từ tệp (sau restart không mất số đếm)."""
        today = self._today()
        if self._day == today:
            return
        self._day, self._engines, self._triggers, self._outcomes = today, {}, {}, {}
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict) and row.get("date") == today:
                        self._bump(row.get("engine"), row.get("trigger"), row.get("outcome"))
        except OSError:
            pass

    def _bump(self, engine, trig, outcome) -> None:
        if isinstance(engine, str) and engine:
            self._engines[engine] = self._engines.get(engine, 0) + 1
        if trig in TRIGGERS:
            self._triggers[trig] = self._triggers.get(trig, 0) + 1
        if outcome in OUTCOMES:
            self._outcomes[outcome] = self._outcomes.get(outcome, 0) + 1

    def record(self, *, job_id=None, instance: str, engine: str, level: str, trigger: str, outcome: str,
               seconds: float) -> None:
        trig = trigger if trigger in TRIGGERS else "direct"
        out = outcome if outcome in OUTCOMES else "error"
        with self._lock:
            self._roll()
            self._bump(engine, trig, out)
            row = {"ts": round(self._now(), 3), "date": self._day, "job_id": job_id, "instance": str(instance),
                   "engine": str(engine), "level": str(level), "trigger": trig, "outcome": out,
                   "seconds": round(float(seconds), 2)}
            try:
                os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
                if os.path.exists(self.path) and os.path.getsize(self.path) >= LOG_MAX_BYTES:
                    os.replace(self.path, self.path + ".1")
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            except OSError:
                pass                                  # sổ hỏng không được làm hỏng lượt chạy

    def summary(self) -> dict:
        with self._lock:
            self._roll()
            cap = self._cap or soft_cap_from_env()
            warn_at = math.ceil(0.8 * cap)
            engines = {}
            for eng, n in sorted(self._engines.items()):
                state = "over" if n >= cap else "warn" if n >= warn_at else "ok"
                engines[eng] = {"count": n, "cap": cap, "state": state}
            return {"date": self._day, "engines": engines, "triggers": dict(self._triggers),
                    "outcomes": dict(self._outcomes)}


_LEDGER: Ledger | None = None
_LEDGER_LOCK = threading.Lock()


def get_ledger() -> Ledger:
    global _LEDGER
    with _LEDGER_LOCK:
        if _LEDGER is None:
            path = os.environ.get("ORBIT_LEDGER_FILE") or os.path.normpath(
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sessions", "agent-ledger.jsonl"))
            _LEDGER = Ledger(path)
        return _LEDGER
