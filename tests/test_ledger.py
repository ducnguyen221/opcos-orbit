"""6c nhịp 1: sổ ghi nhận lượt agent của Orbit + trần mềm (chỉ cảnh báo, KHÔNG chặn). Mock hết, không spawn thật."""
import importlib
import io
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server import adapters, approvals as ap, jobs, ledger
from server.blackboard import Blackboard
from server.config import Config, Instance
from server.orchestrator import run_turn


class _Stdin:
    def write(self, t):
        pass

    def flush(self):
        pass

    def close(self):
        pass


class _Proc:
    pid = 818181
    returncode = 0

    def __init__(self, out):
        self.stdout = io.StringIO(out)
        self.stdin = _Stdin()

    def wait(self, timeout=None):
        return 0


@pytest.fixture(autouse=True)
def _clean():
    jobs.JOBS.clear()
    yield
    jobs.JOBS.clear()


def lines(path):
    return [json.loads(x) for x in open(path, encoding="utf-8")] if path.exists() else []


@pytest.fixture
def led(tmp_path):
    clock = [1_700_000_000.0]
    return ledger.Ledger(str(tmp_path / "ledger.jsonl"), now=lambda: clock[0], soft_cap=5), clock, tmp_path


# --- sổ ghi nhận ------------------------------------------------------------------------------------
def test_record_writes_one_line_without_prompt_fields(led):
    L, _, tmp = led
    L.record(job_id=7, instance="c-1", engine="codex", level="suggest", trigger="human_turn",
             outcome="ok", seconds=1.234)
    [row] = lines(tmp / "ledger.jsonl")
    assert row["instance"] == "c-1" and row["engine"] == "codex" and row["trigger"] == "human_turn"
    assert row["outcome"] == "ok" and row["seconds"] == 1.23 and row["job_id"] == 7
    assert set(row) <= {"ts", "date", "job_id", "instance", "engine", "level", "trigger", "outcome", "seconds"}


def test_unknown_trigger_or_outcome_are_normalised(led):
    L, _, tmp = led
    L.record(job_id=1, instance="x", engine="claude", level="full", trigger="<script>", outcome="???", seconds=0)
    [row] = lines(tmp / "ledger.jsonl")
    assert row["trigger"] == "direct" and row["outcome"] == "error"


def test_daily_counts_and_soft_cap_states(led):
    L, _, _ = led
    for n in range(3):
        L.record(job_id=n, instance="a", engine="claude", level="suggest", trigger="direct", outcome="ok", seconds=0)
    s = L.summary()
    assert s["engines"]["claude"] == {"count": 3, "cap": 5, "state": "ok"}
    L.record(job_id=9, instance="a", engine="claude", level="suggest", trigger="direct", outcome="ok", seconds=0)
    assert L.summary()["engines"]["claude"]["state"] == "warn"          # 4/5 >= 80%
    L.record(job_id=10, instance="a", engine="claude", level="suggest", trigger="direct", outcome="ok", seconds=0)
    assert L.summary()["engines"]["claude"]["state"] == "over"          # 5/5
    L.record(job_id=11, instance="a", engine="claude", level="suggest", trigger="direct", outcome="ok", seconds=0)
    assert L.summary()["engines"]["claude"]["count"] == 6                 # trần MỀM: vẫn ghi, không chặn


def test_counts_reset_on_new_day_and_reload_from_file(led):
    L, clock, tmp = led
    L.record(job_id=1, instance="a", engine="claude", level="suggest", trigger="direct", outcome="ok", seconds=0)
    again = ledger.Ledger(str(tmp / "ledger.jsonl"), now=lambda: clock[0], soft_cap=5)
    assert again.summary()["engines"]["claude"]["count"] == 1             # đọc lại từ tệp sau restart
    clock[0] += 2 * 86400
    assert L.summary()["engines"] == {}


def test_summary_counts_triggers_and_outcomes_today(led):
    L, _, _ = led
    L.record(job_id=1, instance="a", engine="claude", level="suggest", trigger="human_turn", outcome="ok", seconds=0)
    L.record(job_id=2, instance="b", engine="codex", level="suggest", trigger="lead_delegate", outcome="error", seconds=0)
    s = L.summary()
    assert s["triggers"] == {"human_turn": 1, "lead_delegate": 1}
    assert s["outcomes"] == {"ok": 1, "error": 1}


def test_corrupt_lines_ignored_and_io_errors_never_raise(led, monkeypatch):
    L, clock, tmp = led
    (tmp / "ledger.jsonl").write_text('{bad json\n{"date":"x"}\n', encoding="utf-8")
    again = ledger.Ledger(str(tmp / "ledger.jsonl"), now=lambda: clock[0], soft_cap=5)
    assert again.summary()["engines"] == {}
    monkeypatch.setattr(ledger.os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(OSError("đầy đĩa")))
    again.record(job_id=1, instance="a", engine="claude", level="suggest", trigger="direct", outcome="ok", seconds=0)


def test_log_rotates_when_large(led, monkeypatch):
    L, _, tmp = led
    monkeypatch.setattr(ledger, "LOG_MAX_BYTES", 300)
    for n in range(8):
        L.record(job_id=n, instance="a", engine="claude", level="suggest", trigger="direct", outcome="ok", seconds=0)
    assert (tmp / "ledger.jsonl.1").exists()


def test_soft_cap_from_env(monkeypatch):
    monkeypatch.setenv("ORBIT_DAILY_SOFT_CAP", "12")
    assert ledger.soft_cap_from_env() == 12
    for bad in ("", "x", "0", "-3", "99999"):
        monkeypatch.setenv("ORBIT_DAILY_SOFT_CAP", bad)
        assert ledger.soft_cap_from_env() == ledger.DEFAULT_SOFT_CAP


# --- móc vào run_agent ------------------------------------------------------------------------------
def _run(inst, prompt, out="xong\n"):
    with patch.object(adapters.subprocess, "Popen", side_effect=lambda *a, **k: _Proc(out)):
        return adapters.run_agent(inst, prompt)


def test_run_agent_records_ok_error_and_refused(_isolated_ledger):
    L = _isolated_ledger
    _run(Instance(name="c-1", engine="claude", role="R", autonomy="suggest"), "việc")
    out = _run(Instance(name="g-1", engine="gemini", role="R", autonomy="suggest"), "việc")      # bị chặn + xin duyệt
    assert ap.PENDING_MESSAGE in out
    rows = lines(__import__("pathlib").Path(L.path))
    assert [r["outcome"] for r in rows] == ["ok", "pending_approval"]
    assert rows[0]["engine"] == "claude" and rows[0]["trigger"] == "direct"
    assert "việc" not in json.dumps(rows, ensure_ascii=False)             # không ghi prompt


def test_run_agent_records_error_outcome(_isolated_ledger):
    L = _isolated_ledger
    with patch.object(adapters.subprocess, "Popen", side_effect=OSError("không có CLI")):
        out = adapters.run_agent(Instance(name="c-1", engine="claude", role="R", autonomy="suggest"), "việc")
    assert out.startswith("[ERROR]")
    assert [r["outcome"] for r in lines(__import__("pathlib").Path(L.path))] == ["error"]


def test_ledger_failure_never_breaks_run_agent(_isolated_ledger, monkeypatch):
    monkeypatch.setattr(ledger.Ledger, "record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sổ hỏng")))
    out = _run(Instance(name="c-1", engine="claude", role="R", autonomy="suggest"), "việc")
    assert "xong" in out


# --- trigger theo nguồn lượt ------------------------------------------------------------------------
def test_run_turn_tags_human_turn_and_lead_delegate(_isolated_ledger, tmp_path):
    L = _isolated_ledger
    cfg = Config(instances=[Instance(name="lead-1", engine="claude", role="Lead", autonomy="suggest"),
                            Instance(name="c-1", engine="codex", role="Coder", autonomy="suggest")], settings={"max_rounds": 3})
    outs = iter(['[DELEGATE c-1:"làm đi"]', "kết quả coder", "[SAY: xong]"])

    def fake(*a, **k):
        return _Proc(next(outs) + "\n")
    with patch.object(adapters.subprocess, "Popen", side_effect=fake):
        say = run_turn(cfg, Blackboard(str(tmp_path / "bb" / "s.jsonl")), "hãy làm", None)
    assert say == "xong"
    rows = lines(__import__("pathlib").Path(L.path))
    assert [(r["instance"], r["trigger"]) for r in rows] == [
        ("lead-1", "human_turn"), ("c-1", "lead_delegate"), ("lead-1", "human_turn")]


def test_run_approved_is_tagged_approved(_isolated_ledger, _isolated_approvals):
    L, store = _isolated_ledger, _isolated_approvals
    store._pin.set_pin("48291637")
    _run(Instance(name="g-1", engine="gemini", role="R", autonomy="suggest"), "việc cần duyệt")
    [req] = store.list_pending()
    store.decide(req.id, "approve", "ui", pin="48291637")
    with patch.object(adapters.subprocess, "Popen", side_effect=lambda *a, **k: _Proc("ok\n")):
        ap.run_approved(req.id)
    rows = lines(__import__("pathlib").Path(L.path))
    assert rows[-1]["trigger"] == "approved" and rows[-1]["outcome"] == "ok"


# --- API --------------------------------------------------------------------------------------------
def test_api_summary_is_read_only_and_local(tmp_path, monkeypatch, _isolated_ledger):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"instances": [], "settings": {}}), encoding="utf-8")
    monkeypatch.setenv("AGENT_CONSOLE_CONFIG", str(cfg))
    monkeypatch.setenv("AGENT_CONSOLE_UPLOAD_DIR", str(tmp_path / "uploads"))
    import server.app as app_module
    importlib.reload(app_module)
    _isolated_ledger.record(job_id=1, instance="a", engine="claude", level="suggest", trigger="direct",
                            outcome="ok", seconds=0)
    c = TestClient(app_module.app)
    d = c.get("/api/ledger/summary").json()
    assert d["engines"]["claude"]["count"] == 1 and "instance" not in json.dumps(d)
    for method in (c.post, c.put, c.delete):
        assert method("/api/ledger/summary").status_code in (404, 405)
    assert c.get("/api/ledger/summary", headers={"Host": "evil.example"}).status_code == 403
