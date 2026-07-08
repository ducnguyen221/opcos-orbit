import os, fnmatch
_PROT = ["*.env", ".env*", "*.pem", "*.key", "*.boto", ".gitconfig", ".claude.json*", "NTUSER.DAT*"]
_SECRET_HINT = ["secret","token","password","api_key","credential"]
_SKIP_DIR = {"node_modules",".git","__pycache__",".venv"}

def is_protected(path: str) -> bool:
    base = os.path.basename(path).lower()
    if any(fnmatch.fnmatch(base, p.lower()) for p in _PROT): return True
    if base in (".env",) or base.startswith(".env"): return True
    return False

def scan_folder(path: str, max_files: int = 200) -> list:
    out = []
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIR]
        for f in files:
            fp = os.path.join(root, f)
            if is_protected(fp): continue
            try: size = os.path.getsize(fp)
            except OSError: continue
            out.append({"path": fp, "size": size, "type": os.path.splitext(f)[1].lstrip(".")})
            if len(out) >= max_files: return out
    return out

def read_text_file(path: str, max_bytes: int = 100_000) -> str:
    if is_protected(path): return "[PROTECTED — không nạp]"
    with open(path, "rb") as fh: data = fh.read(max_bytes)
    return data.decode("utf-8", errors="replace")

def save_upload(name: str, data: bytes, workspace: str) -> str:
    os.makedirs(workspace, exist_ok=True)
    safe = os.path.basename(name)
    dest = os.path.join(workspace, safe)
    with open(dest, "wb") as fh: fh.write(data)
    return dest


def route_context(path: str) -> dict:
    if is_protected(path): return {"mode": "skip", "hint": "PROTECTED"}
    ext = os.path.splitext(path)[1].lower()
    try: size = os.path.getsize(path)
    except OSError: return {"mode": "skip", "hint": "không đọc được"}
    if ext == ".pdf" or size > 50_000:
        return {"mode": "rag", "hint": f"Dùng PageIndex: pi_build_index('{path}') rồi pi_get_structure/pi_get_pages để hỏi-đáp trích trang."}
    if ext in (".png",".jpg",".jpeg",".zip",".exe",".mp4",".mp3",".wav"):
        return {"mode": "skip", "hint": "binary"}
    return {"mode": "inline", "content": read_text_file(path)}
