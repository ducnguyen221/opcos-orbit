import json, re
from server.config import Instance
from server.agent_library import AgentDef

def _slug(s): return re.sub(r"[^a-z0-9\-]+","-", s.lower()).strip("-") or "agent"

class InstanceStore:
    def __init__(self, config_path: str):
        self.path = config_path
        self.raw = json.load(open(config_path, encoding="utf-8"))
        self.raw.setdefault("instances", []); self.raw.setdefault("settings", {})
    def list(self):
        return [Instance(**{k:v for k,v in i.items() if k in Instance.__dataclass_fields__}) for i in self.raw["instances"]]
    def _save(self):
        json.dump(self.raw, open(self.path,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    def create(self, agent: AgentDef, engine=None, voice="my-voice") -> Instance:
        base = _slug(agent.name)
        existing = {i["name"] for i in self.raw["instances"]}
        # Suffix = max suffix hiện có + 1 (KHÔNG tái dùng số đã xóa) + guard chống trùng.
        suffixes = []
        for i in self.raw["instances"]:
            nm = i["name"]
            if nm.rsplit("-", 1)[0] == base and nm.rsplit("-", 1)[-1].isdigit():
                suffixes.append(int(nm.rsplit("-", 1)[-1]))
        n = (max(suffixes) + 1) if suffixes else 1
        while f"{base}-{n}" in existing:
            n += 1
        inst = Instance(name=f"{base}-{n}", engine=engine or agent.engine,
                        voice=voice, role=agent.role, agent_md=agent.path)
        self.raw["instances"].append(inst.__dict__); self._save(); return inst
    def rename(self, old, new):
        for i in self.raw["instances"]:
            if i["name"]==old: i["name"]=new
        self._save()
    def update(self, name, **fields):
        """Sửa role/engine/model/autonomy/voice của 1 instance (từ UI). Chỉ nhận field
        hợp lệ của Instance, bỏ giá trị None. Nếu đặt role='Lead' → HẠ mọi Lead khác
        về 'Assistant' (orchestrator._lead cần DUY NHẤT 1 Lead, nếu không sẽ chọn
        nhầm instance[0])."""
        allowed = {k: v for k, v in fields.items()
                   if v is not None and k in Instance.__dataclass_fields__ and k != "name"}
        target = next((i for i in self.raw["instances"] if i["name"] == name), None)
        if target is None:
            return None
        if allowed.get("role") == "Lead":
            for i in self.raw["instances"]:
                if i["name"] != name and i.get("role") == "Lead":
                    i["role"] = "Assistant"
        target.update(allowed)
        self._save()
        return target
    def remove(self, name):
        self.raw["instances"]=[i for i in self.raw["instances"] if i["name"]!=name]; self._save()
