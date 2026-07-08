import subprocess, os, tempfile

# Xác minh Phase 1: KHÔNG có script CLI text->wav trong .tts/omnivoice (chỉ có
# narrate_cli.py, yêu cầu --video, dùng để lồng tiếng video). Hàm text->wav thật là
# synthesize_speech() trong mcp_server.py (cũng lộ qua MCP tool
# mcp__omnivoice-tts__synthesize_speech). narrate_cli.py tự dùng pattern
# `import mcp_server as ov` rồi gọi hàm trực tiếp (mcp.run() có guard __main__ nên
# import an toàn) — ta tái dùng đúng pattern đó, spawn venv riêng của OmniVoice
# (torch/model không có trong venv của agent-console) và gọi synthesize_speech qua
# một snippet -c ngắn, cwd = thư mục omnivoice để `import mcp_server` chạy được.
OV_DIR = os.path.expanduser(r"~\.tts\omnivoice")
OV_PY = os.path.join(OV_DIR, ".venv", "Scripts", "python.exe")

_SYNTH_SNIPPET = (
    "import sys\n"
    "import mcp_server as ov\n"
    "text, out, profile = sys.argv[1], sys.argv[2], sys.argv[3]\n"
    "print(ov.synthesize_speech(text, out, voice_profile=profile, language='Vietnamese'))\n"
)

def synthesize(text: str, profile: str = "") -> str:
    out = os.path.join(tempfile.gettempdir(), f"ac_{abs(hash(text))}.wav")
    subprocess.run(
        [OV_PY, "-c", _SYNTH_SNIPPET, text, out, profile],
        check=True, timeout=120, cwd=OV_DIR,
    )
    return out
