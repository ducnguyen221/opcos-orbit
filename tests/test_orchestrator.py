from server.orchestrator import parse_markers, run_turn
from server.config import Config, Instance
from server.blackboard import Blackboard
import tempfile, os

def test_parse_markers():
    t = '[DELEGATE researcher-1:"tìm X"; coder-1:"sửa Y"]\n[SAY: xong rồi]'
    m = parse_markers(t)
    assert ("researcher-1", "tìm X") in m["delegate"]
    assert ("coder-1", "sửa Y") in m["delegate"]
    assert m["say"] == "xong rồi"

def test_parse_attach():
    t = '[ATTACH coder-1: /x/f.py]'
    m = parse_markers(t)
    assert m["attach"] == [("coder-1", "/x/f.py")]

def test_run_turn_delegates_then_says():
    cfg = Config(instances=[Instance("lead-1","claude",role="Lead"),
                            Instance("researcher-1","gemini",role="Researcher")],
                 settings={"max_rounds":3})
    calls = []
    def fake_runner(inst, prompt, timeout=120):
        calls.append(inst.name)
        if inst.role == "Lead" and "tìm" not in prompt:
            return '[DELEGATE researcher-1:"tìm X"]'
        if inst.role == "Lead":
            return '[SAY: đã có kết quả]'
        return "kết quả nghiên cứu X"
    bb = Blackboard(os.path.join(tempfile.mkdtemp(), "s.jsonl"))
    say = run_turn(cfg, bb, "nghiên cứu X giúp", agent_runner=fake_runner)
    assert say == "đã có kết quả"
    assert "researcher-1" in calls
