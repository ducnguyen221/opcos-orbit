"""Restore bundled voice profiles (assets/voices/*) vào thư mục voices của OmniVoice.

Tuỳ chọn: thả file *.wav + *.txt (kèm _default.txt nếu muốn set default) của bạn
vào assets/voices/ trước khi chạy install.ps1 — máy khác clone repo sẽ có sẵn giọng
đó mà không cần setup tay. Thư mục rỗng thì bước này không làm gì (no-op an toàn).
"""
import os
import shutil

OV_DIR = os.path.expanduser(r"~\.tts\omnivoice")
OV_VOICES_DIR = os.path.join(OV_DIR, "voices")
ASSETS_VOICES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "voices"
)


def restore_bundled_voices(assets_dir: str, omni_voices_dir: str) -> list:
    """Copy *.wav/*.txt (kể cả _default.txt) từ assets_dir -> omni_voices_dir.

    Skip file đã tồn tại ở đích (không ghi đè giọng đã có trên máy). Trả về danh
    sách tên profile (không đuôi) đã copy .wav (dùng để báo log "đã restore X").
    """
    os.makedirs(omni_voices_dir, exist_ok=True)
    restored = []
    for f in sorted(os.listdir(assets_dir)):
        if f.endswith((".wav", ".txt")):
            dst = os.path.join(omni_voices_dir, f)
            if not os.path.exists(dst):
                shutil.copy2(os.path.join(assets_dir, f), dst)
            if f.endswith(".wav"):
                restored.append(f[:-4])
    return restored


def set_bundled_default(name: str = "") -> str:
    """Gọi qua venv OmniVoice để set default = name (best-effort, không raise ra ngoài)."""
    from server import voices

    try:
        return voices.set_default(name)
    except Exception as e:  # best-effort: không fail cứng install nếu OmniVoice model chưa sẵn sàng
        return f"skip: {e}"


if __name__ == "__main__":
    import sys

    got = restore_bundled_voices(ASSETS_VOICES_DIR, OV_VOICES_DIR)
    print(f"Restored voices: {got}")
    if "--set-default" in sys.argv:
        print(set_bundled_default(""))
