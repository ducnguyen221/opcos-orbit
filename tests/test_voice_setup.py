from server.voice_setup import restore_bundled_voices


def test_restore_copies(tmp_path):
    a = tmp_path / "assets"
    a.mkdir()
    (a / "my-voice.wav").write_bytes(b"RIFF")
    (a / "my-voice.txt").write_text("x")
    (a / "_default.txt").write_text("my-voice")
    dst = tmp_path / "voices"
    dst.mkdir()
    got = restore_bundled_voices(str(a), str(dst))
    assert "my-voice" in got and (dst / "my-voice.wav").exists() and (dst / "_default.txt").read_text() == "my-voice"


def test_restore_skips_existing(tmp_path):
    a = tmp_path / "assets"
    a.mkdir()
    (a / "my-voice.wav").write_bytes(b"RIFF-NEW")
    (a / "my-voice.txt").write_text("new-text")
    dst = tmp_path / "voices"
    dst.mkdir()
    (dst / "my-voice.wav").write_bytes(b"OLD")
    got = restore_bundled_voices(str(a), str(dst))
    assert (dst / "my-voice.wav").read_bytes() == b"OLD"
