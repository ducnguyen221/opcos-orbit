from unittest.mock import patch
from server import stt

def test_transcribe_calls_model(tmp_path):
    wav = tmp_path / "a.wav"; wav.write_bytes(b"RIFF....")
    with patch("server.stt._model") as m:
        m.transcribe.return_value = ([type("S",(),{"text":"xin chào"})()], None)
        assert stt.transcribe(str(wav)) == "xin chào"
