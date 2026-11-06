# -*- coding: utf-8 -*-
"""paths.py — nguồn duy nhất cho các đường ngoài repo (OpcOS, OmniVoice).

Đổi vị trí chỉ cần đặt biến môi trường, không sửa code:
  OPCOS_ROOT     gốc OpcOS (mặc định ~/OpcOS)
  OMNIVOICE_DIR  thư mục OmniVoice (mặc định ~/.tts/omnivoice)
"""
import os

OPCOS_ROOT = os.environ.get("OPCOS_ROOT") or os.path.expanduser("~/OpcOS")
REGISTRY = os.path.join(OPCOS_ROOT, "system", "registry.json")
REGISTRY_HTML = os.path.join(OPCOS_ROOT, "system", "docs", "registry.html")


def upload_dir() -> str:
    """Thư mục upload (env đọc mỗi lần gọi — test/triển khai đổi được)."""
    return os.environ.get("AGENT_CONSOLE_UPLOAD_DIR") or os.path.join(
        os.path.dirname(__file__), "..", "workspace", "uploads")


OMNIVOICE_DIR = os.environ.get("OMNIVOICE_DIR") or os.path.expanduser("~/.tts/omnivoice")
