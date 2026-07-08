import json, os

class Blackboard:
    def __init__(self, session_path: str):
        self.path = session_path
        os.makedirs(os.path.dirname(session_path), exist_ok=True)
        self._turns = []
        if os.path.exists(session_path):
            for line in open(session_path, encoding="utf-8"):
                line = line.strip()
                if line: self._turns.append(json.loads(line))

    def add(self, speaker: str, role: str, content: str) -> None:
        turn = {"speaker": speaker, "role": role, "content": content, "ts_index": len(self._turns)}
        self._turns.append(turn)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(turn, ensure_ascii=False) + "\n")

    def turns(self): return list(self._turns)
    def transcript_text(self) -> str:
        return "\n".join(f"{t['speaker']} ({t['role']}): {t['content']}" for t in self._turns)
