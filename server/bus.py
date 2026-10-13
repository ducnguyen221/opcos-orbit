# -*- coding: utf-8 -*-
"""bus.py — Agent message bus ("socket agent-to-agent", distill herdr AGPL — CHỈ tái
hiện hành vi, không copy code).

Cho agent nói TRỰC TIẾP với agent khác, không phải mọi thứ đều vòng qua Lead tổng hợp.
Vì agent ở đây là CLI one-shot (claude -p / codex exec / agy -p) — không giữ socket
sống — nên "socket" được distill thành HỘP THƯ: agent post tin addressed tới <name>
(hoặc 'all' = broadcast); lượt sau khi agent đó chạy, inbox chưa-đọc được nạp vào
prompt rồi đánh dấu consumed (giao đúng-một-lần). UI soi feed qua BUS.recent().
"""
from __future__ import annotations

import itertools
import threading
import time
from collections import deque
from dataclasses import dataclass

_id = itertools.count(1)
_LOCK = threading.Lock()
BROADCAST = "all"


@dataclass
class Message:
    id: int
    sender: str
    recipient: str          # tên instance hoặc 'all' (broadcast)
    text: str
    ts: float
    consumed: bool = False

    def to_dict(self) -> dict:
        return {"id": self.id, "sender": self.sender, "recipient": self.recipient,
                "text": self.text, "ts": self.ts, "consumed": self.consumed}


class AgentBus:
    def __init__(self, maxlen: int = 200):
        self._msgs: "deque[Message]" = deque(maxlen=maxlen)

    def post(self, sender: str, recipient: str, text: str) -> Message | None:
        text = (text or "").strip()
        if not text:
            return None
        m = Message(id=next(_id), sender=(sender or "?").strip(),
                    recipient=(recipient or BROADCAST).strip(), text=text, ts=time.time())
        with _LOCK:
            self._msgs.append(m)
        return m

    def inbox(self, recipient: str) -> list[Message]:
        """Tin CHƯA đọc gửi tới <recipient> (hoặc broadcast 'all'). KHÔNG trả tin do
        chính recipient gửi (không tự đọc thư mình)."""
        with _LOCK:
            return [m for m in self._msgs
                    if not m.consumed and m.sender != recipient
                    and m.recipient in (recipient, BROADCAST)]

    def consume(self, ids) -> int:
        ids = set(ids)
        n = 0
        with _LOCK:
            for m in self._msgs:
                if m.id in ids and not m.consumed:
                    m.consumed = True
                    n += 1
        return n

    def recent(self, n: int = 50) -> list[dict]:
        with _LOCK:
            return [m.to_dict() for m in list(self._msgs)[-n:]]

    def clear(self) -> None:
        with _LOCK:
            self._msgs.clear()


BUS = AgentBus()
