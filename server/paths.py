# -*- coding: utf-8 -*-
"""paths.py — nguồn duy nhất cho các đường ngoài repo (OpcOS, OmniVoice).

Đổi vị trí chỉ cần đặt biến môi trường, không sửa code:
  OPCOS_ROOT     gốc OpcOS (mặc định ~/OpcOS)
  OMNIVOICE_DIR  thư mục OmniVoice (mặc định ~/.tts/omnivoice)
"""
import os
import re

OPCOS_ROOT = os.environ.get("OPCOS_ROOT") or os.path.expanduser("~/OpcOS")
REGISTRY = os.path.join(OPCOS_ROOT, "system", "registry.json")
REGISTRY_HTML = os.path.join(OPCOS_ROOT, "system", "docs", "registry.html")


def upload_dir() -> str:
    """Thư mục upload (env đọc mỗi lần gọi — test/triển khai đổi được)."""
    return os.environ.get("AGENT_CONSOLE_UPLOAD_DIR") or os.path.join(
        os.path.dirname(__file__), "..", "workspace", "uploads")


OMNIVOICE_DIR = os.environ.get("OMNIVOICE_DIR") or os.path.expanduser("~/.tts/omnivoice")

_NAME_BAD = re.compile(r"[^A-Za-z0-9_\-]+")


def workspace_root() -> str:
    """Gốc cwd của các instance (RF8). Ngoài gốc repo Orbit để agent không chạy trong cây mã/config.json."""
    return os.environ.get("ORBIT_WORKSPACE_ROOT") or os.path.join(OPCOS_ROOT, "workspaces", "orbit")


def instance_cwd(inst) -> str:
    """Thư mục làm việc riêng của instance, luôn nằm DƯỚI workspace_root(). Tên bị làm sạch; `cwd` tuỳ chọn
    chỉ được dùng nếu nằm trong gốc (sau realpath) và không đi qua `.secret`; ngược lại về mặc định."""
    root = os.path.realpath(workspace_root())
    name = _NAME_BAD.sub("_", str(getattr(inst, "name", "") or "")).strip("._") or "agent"
    path = os.path.join(root, name)
    custom = getattr(inst, "cwd", "") or ""
    if isinstance(custom, str) and custom and "\x00" not in custom:
        real = os.path.realpath(custom)
        try:
            inside = os.path.commonpath([real, root]) == root and real != root
        except ValueError:
            inside = False
        if inside and ".secret" not in os.path.normcase(real).replace("\\", "/").split("/"):
            path = real
    os.makedirs(path, exist_ok=True)
    return path
