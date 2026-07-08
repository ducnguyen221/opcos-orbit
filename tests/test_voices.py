from unittest.mock import patch
from server import voices

def test_list_voices_parses(tmp_path):
    with patch("server.voices._ov_call") as m:
        m.return_value = '["my-voice","giong-b"]'
        assert voices.list_voices() == ["my-voice", "giong-b"]

def test_clone_builds_call():
    with patch("server.voices.subprocess.run") as m:
        m.return_value.stdout = "OK"; m.return_value.returncode = 0
        voices.clone_from_wav("C:/a.wav", "xin chào", "test")
        args = m.call_args[0][0]
        assert any("save_profile_from_wav" in str(a) for a in args)
        assert "test" in args
