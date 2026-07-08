import os, subprocess, json
OV_DIR = os.path.expanduser(r"~\.tts\omnivoice")
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

def delete_voice(name: str) -> str:
    voices_dir = os.path.join(OV_DIR, "voices")
    for ext in (".wav", ".txt"):
        p = os.path.join(voices_dir, name + ext)
        if os.path.exists(p): os.remove(p)
    return "deleted"
