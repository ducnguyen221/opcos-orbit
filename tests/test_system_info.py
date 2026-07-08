# -*- coding: utf-8 -*-
"""Test system_info: parse `claude mcp list` + kiểm tra live (mock subprocess)."""
from unittest.mock import patch

from server import system_info


SAMPLE = """Checking MCP server health…

claude.ai Supabase: https://mcp.supabase.com/mcp - ✔ Connected
playwright: npx -y @playwright/mcp@latest - ✔ Connected
omnivoice-tts: C:\\path\\python.exe server.py - ✔ Connected
broken-one: npx some-thing - ✘ Failed to connect
"""


def test_parse_mcp_list_connected_and_failed():
    rows = system_info.parse_mcp_list(SAMPLE)
    assert len(rows) == 4                      # dòng 'Checking…' + rỗng bị bỏ
    names = {r["name"]: r for r in rows}
    assert names["playwright"]["connected"] is True
    assert names["claude.ai Supabase"]["connected"] is True   # tên có dấu ':' trong https vẫn tách đúng
    assert names["broken-one"]["connected"] is False
    assert "Failed" in names["broken-one"]["status"]


def test_parse_mcp_list_ignores_noise():
    assert system_info.parse_mcp_list("Checking MCP server health…\n\n") == []
    assert system_info.parse_mcp_list("") == []


def test_mcp_live_success():
    class FakeRun:
        stdout = SAMPLE
    with patch("subprocess.run", return_value=FakeRun()):
        out = system_info.mcp_live(timeout=5)
    assert out["ok"] is True
    assert out["total"] == 4 and out["connected"] == 3


def test_mcp_live_timeout():
    import subprocess
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 5)):
        out = system_info.mcp_live(timeout=5)
    assert out["ok"] is False and "chậm" in out["error"]
