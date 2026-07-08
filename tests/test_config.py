import json, tempfile, os
from server.config import load_config

def test_load_config_parses_instances():
    data = {"settings": {"max_rounds": 3},
            "instances": [{"name": "lead-1", "engine": "claude", "voice": "my-voice", "role": "Lead"}]}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(data, f); p = f.name
    cfg = load_config(p); os.unlink(p)
    assert cfg.settings["max_rounds"] == 3
    assert cfg.instances[0].name == "lead-1"
    assert cfg.instances[0].engine == "claude"
    assert cfg.instances[0].role == "Lead"


def test_load_config_ollama_instance_with_model():
    """Engine ollama có thể khai `model` trong config mà không vỡ Instance(**i)."""
    data = {"instances": [{"name": "draft-1", "engine": "ollama",
                           "role": "Trợ lý", "model": "qwen2.5:14b"}]}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(data, f); p = f.name
    cfg = load_config(p); os.unlink(p)
    assert cfg.instances[0].engine == "ollama"
    assert cfg.instances[0].model == "qwen2.5:14b"
