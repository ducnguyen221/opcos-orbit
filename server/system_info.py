# -*- coding: utf-8 -*-
"""system_info.py — System pane (Console v2): đọc opcos registry + MCP đã đăng ký
của 3 tool. Distill ý tưởng "workspace quản trị" từ Odysseus; dữ liệu = hệ opcos sẵn có.
Đọc RẺ (parse file config, không gọi `mcp list` chậm); KHÔNG đọc giá trị secret —
chỉ lấy TÊN server/command."""
from __future__ import annotations

import json
import os
import re

HOME = os.path.expanduser("~")
REGISTRY = os.path.join(HOME, ".opcos", "registry.json")
REGISTRY_HTML = os.path.join(HOME, ".opcos", "docs", "registry.html")
CLAUDE_JSON = os.path.join(HOME, ".claude.json")
CODEX_TOML = os.path.join(HOME, ".codex", "config.toml")
GEMINI_SETTINGS = os.path.join(HOME, ".gemini", "settings.json")


def _read_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return None


def registry_summary() -> dict:
    """Tóm tắt registry.json cho dashboard: đếm theo category/priority + danh sách gọn."""
    data = _read_json(REGISTRY)
    if not data:
        return {"ok": False, "error": f"không đọc được {REGISTRY}"}
    comps = data.get("components", [])
    by_cat, by_prio = {}, {}
    items = []
    for c in comps:
        by_cat[c.get("category", "?")] = by_cat.get(c.get("category", "?"), 0) + 1
        by_prio[c.get("priority", "?")] = by_prio.get(c.get("priority", "?"), 0) + 1
        items.append({
            "name": c.get("name", ""),
            "category": c.get("category", ""),
            "priority": c.get("priority", ""),
            "purpose": (c.get("purpose", "") or "")[:140],
            "storage": c.get("storage", ""),
        })
    return {"ok": True, "updated": data.get("updated", ""), "total": len(comps),
            "by_category": by_cat, "by_priority": by_prio, "items": items}


def mcp_servers() -> dict:
    """MCP đã ĐĂNG KÝ theo tool (đọc config file — tên + lệnh, không secret,
    không kiểm tra live vì tốn 10-60s; nút 'kiểm tra live' để sau)."""
    out = {"claude": [], "codex": [], "gemini": []}
    cj = _read_json(CLAUDE_JSON)
    if isinstance(cj, dict):
        for name, spec in (cj.get("mcpServers") or {}).items():
            out["claude"].append({"name": name, "command": str(spec.get("command", ""))[:80]})
    gj = _read_json(GEMINI_SETTINGS)
    if isinstance(gj, dict):
        for name, spec in (gj.get("mcpServers") or {}).items():
            out["gemini"].append({"name": name, "command": str(spec.get("command", ""))[:80]})
    try:  # codex config.toml: CHỈ header cấp 1 [mcp_servers.<name>] — bỏ sub-table
        # kiểu [mcp_servers.<name>.env] (regex cũ bắt trùng tên nhiều lần).
        with open(CODEX_TOML, encoding="utf-8-sig") as f:
            toml_text = f.read()
        seen = set()
        for m in re.finditer(r'^\[mcp_servers\.([^.\]"]+|"[^"]+")\]\s*$([^\[]*)',
                             toml_text, re.MULTILINE):
            name = m.group(1).strip('"')
            if name in seen:
                continue
            seen.add(name)
            cmd = re.search(r'command\s*=\s*"([^"]+)"', m.group(2))
            out["codex"].append({"name": name, "command": (cmd.group(1) if cmd else "")[:80]})
    except Exception:
        pass
    return out


_MCP_LINE = re.compile(r"^(?P<name>.+?):\s+.*\s-\s*(?P<status>.+)$")


def parse_mcp_list(text: str) -> list[dict]:
    """Parse output `claude mcp list`: mỗi dòng `<name>: <cmd/url> - ✔ Connected`.
    Bỏ dòng tiêu đề ('Checking...'). Connected = có chữ 'Connected' ở đuôi."""
    out = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line or line.lower().startswith("checking"):
            continue
        m = _MCP_LINE.match(line)
        if not m:
            continue
        status = m.group("status").strip()
        out.append({"name": m.group("name").strip(),
                    "connected": "connected" in status.lower(),
                    "status": status})
    return out


def mcp_live(timeout: int = 90) -> dict:
    """KIỂM TRA LIVE: chạy `claude mcp list` (chậm 10-60s vì thật sự nối từng server)
    → trạng thái Connected/Failed thật, khác với mcp_servers() chỉ đọc config file.
    Chỉ tool `claude` (codex/gemini list format khác + ít khi cần)."""
    import subprocess
    from server.adapters import _resolve
    try:
        r = subprocess.run(_resolve("claude") + ["mcp", "list"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        servers = parse_mcp_list(r.stdout or "")
        return {"ok": True, "servers": servers,
                "connected": sum(1 for s in servers if s["connected"]),
                "total": len(servers)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"quá {timeout}s — server MCP phản hồi chậm"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def registry_html() -> str | None:
    try:
        with open(REGISTRY_HTML, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None
