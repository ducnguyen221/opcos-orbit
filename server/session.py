import os, json, time
from server.blackboard import Blackboard

class SessionManager:
    def __init__(self, sessions_dir: str):
        self.dir = sessions_dir; os.makedirs(sessions_dir, exist_ok=True)
        self.index = os.path.join(sessions_dir, "index.json")
        self.data = json.load(open(self.index, encoding="utf-8")) if os.path.exists(self.index) else {}
    def _save(self): json.dump(self.data, open(self.index,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    def new(self, name: str) -> str:
        sid = str(int(time.time()*1000))
        self.data[sid] = {"id": sid, "name": name, "ts": sid}; self._save(); return sid
    def list(self):
        out = []
        for sid, meta in self.data.items():
            p = os.path.join(self.dir, f"{sid}.jsonl")
            n = sum(1 for _ in open(p, encoding="utf-8")) if os.path.exists(p) else 0
            out.append({**meta, "turns": n})
        return sorted(out, key=lambda x: x["ts"], reverse=True)
    def rename(self, sid, name):
        if sid in self.data: self.data[sid]["name"]=name; self._save()
    def set_archived(self, sid, archived: bool):
        """Archive = tắt phiên (giữ nguyên lịch sử .jsonl, chỉ đánh dấu) — resume bằng unarchive."""
        if sid in self.data:
            self.data[sid]["archived"] = bool(archived); self._save()
    def load(self, sid) -> Blackboard:
        return Blackboard(os.path.join(self.dir, f"{sid}.jsonl"))
