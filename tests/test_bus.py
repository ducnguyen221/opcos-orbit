# -*- coding: utf-8 -*-
"""Test AgentBus (socket agent-to-agent = hộp thư liên-agent)."""
from server.bus import AgentBus, BROADCAST


def test_post_and_inbox_addressed():
    bus = AgentBus()
    bus.post("lead-1", "coder-1", "sửa hàm X giúp")
    inbox = bus.inbox("coder-1")
    assert len(inbox) == 1 and inbox[0].text == "sửa hàm X giúp"
    assert bus.inbox("researcher-1") == []      # không phải người nhận


def test_broadcast_reaches_everyone_except_sender():
    bus = AgentBus()
    bus.post("lead-1", BROADCAST, "họp nhanh")
    assert len(bus.inbox("coder-1")) == 1
    assert len(bus.inbox("researcher-1")) == 1
    assert bus.inbox("lead-1") == []            # không tự đọc thư mình gửi


def test_consume_is_once_only():
    bus = AgentBus()
    m = bus.post("lead-1", "coder-1", "x")
    assert len(bus.inbox("coder-1")) == 1
    assert bus.consume([m.id]) == 1
    assert bus.inbox("coder-1") == []           # đã consume → không giao lại
    assert bus.consume([m.id]) == 0             # consume lần 2 = 0


def test_post_empty_ignored():
    bus = AgentBus()
    assert bus.post("a", "b", "   ") is None
    assert bus.recent() == []


def test_recent_and_clear():
    bus = AgentBus()
    for i in range(3):
        bus.post("a", "b", f"m{i}")
    r = bus.recent()
    assert len(r) == 3 and r[-1]["text"] == "m2"
    assert r[0]["consumed"] is False
    bus.clear()
    assert bus.recent() == []


def test_maxlen_ring():
    bus = AgentBus(maxlen=2)
    bus.post("a", "b", "1"); bus.post("a", "b", "2"); bus.post("a", "b", "3")
    texts = [m["text"] for m in bus.recent()]
    assert texts == ["2", "3"]                  # tin cũ nhất bị đẩy ra
