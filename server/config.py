import json
from dataclasses import dataclass, field

@dataclass
class Instance:
    name: str
    engine: str            # claude | codex | gemini | agy | ollama
    voice: str = "my-voice"
    role: str = "Assistant"
    agent_md: str | None = None
    session_id: str = ""
    autonomy: str = "suggest"
    model: str = ""        # chỉ dùng cho engine ollama (mặc định qwen2.5:7b nếu rỗng)

@dataclass
class Config:
    instances: list[Instance] = field(default_factory=list)
    settings: dict = field(default_factory=dict)

def load_config(path: str) -> Config:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    inst = [Instance(**i) for i in raw.get("instances", [])]
    return Config(instances=inst, settings=raw.get("settings", {}))
