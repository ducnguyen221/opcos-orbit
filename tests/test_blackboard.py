import tempfile, os, json
from server.blackboard import Blackboard

def test_blackboard_add_and_persist():
    d = tempfile.mkdtemp(); p = os.path.join(d, "s.jsonl")
    bb = Blackboard(p)
    bb.add("user", "User", "xin chào")
    bb.add("lead-1", "Lead", "chào bạn")
    assert len(bb.turns()) == 2
    assert "chào bạn" in bb.transcript_text()
    lines = open(p, encoding="utf-8").read().strip().splitlines()
    assert json.loads(lines[0])["speaker"] == "user"
