import os, sys
from faster_whisper import WhisperModel

# Windows: wheel nvidia-cublas-cu12 / nvidia-cudnn-cu12 đặt DLL trong
# site-packages/nvidia/*/bin — thêm vào DLL search path để ctranslate2 (backend
# faster-whisper) thấy cublas64_12.dll / cudnn khi chạy GPU. Không có thì bỏ qua.
if hasattr(os, "add_dll_directory"):
    for base in sys.path:
        for pkg in ("cublas", "cudnn"):
            d = os.path.join(base, "nvidia", pkg, "bin")
            if os.path.isdir(d):
                try: os.add_dll_directory(d)
                except Exception: pass

_MODEL_NAME = os.environ.get("AC_WHISPER_MODEL", "large-v3")
_model = None

def _try(device, ct):
    try: return WhisperModel(_MODEL_NAME, device=device, compute_type=ct)
    except Exception: return None

def transcribe(audio_path: str) -> str:
    global _model
    if _model is None:
        _model = _try("cuda", "float16") or _try("cpu", "int8")
    try:
        segs, _ = _model.transcribe(audio_path, language="vi")
        return "".join(s.text for s in segs).strip()
    except Exception:
        # Lỗi GPU lúc inference (thiếu cublas/cudnn) → dựng lại CPU + retry (mọi máy chạy được).
        _model = WhisperModel(_MODEL_NAME, device="cpu", compute_type="int8")
        segs, _ = _model.transcribe(audio_path, language="vi")
        return "".join(s.text for s in segs).strip()
