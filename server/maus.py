"""Trạng thái OpenMausBot cho thẻ trong Orbit (bước 6b, quyết định D1: thẻ + nút mở tab, KHÔNG nhúng).

OpenMausBot chặn iframe có chủ ý (`frame-ancestors 'none'`), nên Orbit chỉ cho biết nó có đang chạy không và
đưa đường dẫn để mở ở tab riêng. Module này CHỈ ĐỌC: không có hàm khởi động/tắt (khởi động bằng `maus.ps1` /
`run.ps1 -WithMaus` do người chạy — để agent không gọi được qua API). Chỉ hỏi 127.0.0.1, không proxy, không
theo redirect, và không trả bất kỳ trường nào của /api/health ngoài "đang chạy".
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_PORT = 8799


def maus_port() -> int:
    raw = os.environ.get("ORBIT_MAUS_PORT", "")
    if raw.isascii() and raw.isdecimal() and 1024 <= int(raw) <= 65535:
        return int(raw)
    return DEFAULT_PORT


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def fetch_health(port: int, timeout: float = 1.5):
    """GET http://127.0.0.1:<port>/api/health -> (mã, JSON). Lỗi mạng ném OSError cho caller xử lý."""
    req = urllib.request.Request(f"http://127.0.0.1:{int(port)}/api/health", method="GET")
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read(65536) or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}
    except ValueError:
        return 200, {}


def status(port: int | None = None, fetch=None) -> dict:
    port = port or maus_port()
    fetch = fetch or fetch_health
    running = False
    try:
        code, data = fetch(port)
        running = code == 200 and isinstance(data, dict) and data.get("app") == "openmausbot"
    except Exception:
        running = False
    out = {"running": running, "port": port}
    if running:
        out["url"] = f"http://127.0.0.1:{port}"
    return out
