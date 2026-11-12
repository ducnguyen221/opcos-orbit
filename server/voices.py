import os, subprocess, json
from server.paths import OMNIVOICE_DIR as OV_DIR
OV_PY = os.path.join(OV_DIR, ".venv", "Scripts", "python.exe")

def _ov_call(snippet: str, *args) -> str:
    r = subprocess.run([OV_PY, "-c", snippet, *[str(a) for a in args]],
                       capture_output=True, text=True, encoding="utf-8",
                       cwd=OV_DIR, timeout=300)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "OmniVoice call failed")[-400:])
    return (r.stdout or "").strip()

def list_voices() -> list:
    out = _ov_call("import voice_profiles as vp, json, sys; sys.stdout.reconfigure(encoding='utf-8'); print(json.dumps(vp.list_profiles(), ensure_ascii=False))")
    try: return json.loads(out.splitlines()[-1])
    except Exception: return []

def set_default(name: str) -> str:
    return _ov_call("import voice_profiles as vp, sys; vp.set_default(sys.argv[1]); print('ok')", name)

def clone_from_wav(wav_path: str, ref_text: str, name: str) -> str:
    return _ov_call(
        "import voice_profiles as vp, sys; sys.stdout.reconfigure(encoding='utf-8');"
        "print(vp.save_profile_from_wav(sys.argv[1], sys.argv[2], sys.argv[3], set_as_default=False))",
        wav_path, ref_text, name)

def create_from_instruct(instruct: str, name: str) -> str:
    # model=None → save_profile_from_instruct tự load model mặc định trong hàm
    return _ov_call(
        "import voice_profiles as vp, mcp_server as ov, sys; sys.stdout.reconfigure(encoding='utf-8');"
        "m=ov._load_model() if hasattr(ov,'_load_model') else None;"
        "print(vp.save_profile_from_instruct(m, sys.argv[1], sys.argv[2], set_as_default=False))",
        instruct, name)

import re
_VOICE_NAME = re.compile(r"[\w][\w\-. ]{0,63}")     # tên giọng: không dấu phân cách đường dẫn, không bắt đầu bằng "."


def valid_voice_name(name) -> bool:
    return isinstance(name, str) and bool(_VOICE_NAME.fullmatch(name)) and ".." not in name


def delete_voice(name: str) -> str:
    if not valid_voice_name(name):                    # RF11: không để `..\` thoát khỏi thư mục voices
        raise ValueError("tên giọng không hợp lệ")
    voices_dir = os.path.realpath(os.path.join(OV_DIR, "voices"))
    for ext in (".wav", ".txt"):
        p = os.path.realpath(os.path.join(voices_dir, name + ext))
        if os.path.dirname(p) != voices_dir:          # chốt thêm sau khi chuẩn hoá đường dẫn
            raise ValueError("tên giọng không hợp lệ")
        if os.path.exists(p): os.remove(p)
    return "deleted"
