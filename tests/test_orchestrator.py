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


def test_parse_msg_marker():
    m = parse_markers('[MSG coder-1:"dùng pattern 2"] [MSG all:"họp nhanh"]')
    assert ("coder-1", "dùng pattern 2") in m["msg"]
    assert ("all", "họp nhanh") in m["msg"]


def test_run_turn_a2a_delivers_inbox_to_delegate():
    """Lead nhắn coder-1 qua bus rồi delegate → tin nạp vào prompt coder-1."""
    from server.bus import BUS
    BUS.clear()
    cfg = Config(instances=[Instance("lead-1", "claude", role="Lead"),
                            Instance("coder-1", "codex", role="Coder")],
                 settings={"max_rounds": 3})
    seen = {}

    def fake_runner(inst, prompt, timeout=120):
        if inst.role == "Lead":
            if "Kết quả delegate" in prompt:      # vòng 2: đã có kết quả → chốt
                return '[SAY: done]'
            return '[MSG coder-1:"dùng ring-buffer"] [DELEGATE coder-1:"viết jobs"]'
        seen["coder_prompt"] = prompt
        return "đã viết xong"

    bb = Blackboard(os.path.join(tempfile.mkdtemp(), "s.jsonl"))
    run_turn(cfg, bb, "làm jobs", agent_runner=fake_runner)
    assert "ring-buffer" in seen["coder_prompt"]         # tin bus nạp vào prompt
    assert "Tin từ đồng đội" in seen["coder_prompt"]


def test_run_turn_agent_msg_output_posted_to_bus():
    """Agent phụ phát [MSG ...] trong output → post lên bus cho agent khác."""
    from server.bus import BUS
    BUS.clear()
    cfg = Config(instances=[Instance("lead-1", "claude", role="Lead"),
                            Instance("researcher-1", "gemini", role="Researcher")],
                 settings={"max_rounds": 2})

    def fake_runner(inst, prompt, timeout=120):
        if inst.role == "Lead":
            if "Kết quả delegate" in prompt:      # vòng 2: chốt
                return '[SAY: done]'
            return '[DELEGATE researcher-1:"tìm"]'
        return 'kết quả nghiên cứu [MSG coder-1:"note cho coder"]'

    bb = Blackboard(os.path.join(tempfile.mkdtemp(), "s.jsonl"))
    run_turn(cfg, bb, "x", agent_runner=fake_runner)
    inbox = BUS.inbox("coder-1")
    assert len(inbox) == 1 and "note cho coder" in inbox[0].text
    assert inbox[0].sender == "researcher-1"
