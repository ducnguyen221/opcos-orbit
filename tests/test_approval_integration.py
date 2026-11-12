"""Móc giao thức duyệt vào run_agent (SPEC FR1/FR3, SC2/SC4/SC7). Mock Popen — không spawn tiến trình thật."""
import io
import json
from unittest.mock import patch

import pytest

from server import adapters, approvals as ap, jobs
from server.bus import BUS
from server.config import Instance

PIN = "48291637"


class _Stdin:
    def write(self, t):
        pass

    def flush(self):
        pass

    def close(self):
        pass


class _Proc:
    pid = 515151
    returncode = 0

    def __init__(self):
        self.stdout = io.StringIO("xong\n")
        self.stdin = _Stdin()

    def wait(self, timeout=None):
        return 0


@pytest.fixture(autouse=True)
def _clean():
    jobs.JOBS.clear()
    BUS.clear()
    yield
    jobs.JOBS.clear()
    BUS.clear()


@pytest.fixture
def popen():
    calls = []

    def fake(argv, **kw):
        calls.append(argv)
        return _Proc()
    with patch.object(adapters.subprocess, "Popen", side_effect=fake):
        yield calls


def gem(**kw):
    return Instance(name="g-1", engine="gemini", role="Coder", autonomy=kw.pop("autonomy", "suggest"), **kw)


def test_refusal_creates_pending_request_and_message_has_no_id(popen, _isolated_approvals):
    store = _isolated_approvals
    out = adapters.run_agent(gem(), "việc cần duyệt")
    assert out.startswith("[ERROR]") and ap.PENDING_MESSAGE in out
    assert popen == []                                        # chưa chạy gì
    [req] = store.list_pending()
    assert req.prompt_final == "việc cần duyệt" and req.target_level == "full" and req.requester == "g-1"
    blob = out + json.dumps(jobs.list_jobs(), ensure_ascii=False)
    assert req.id not in blob and req.job_fp not in blob       # SC4: id/băm không lọt vào output hay job feed


def test_no_pending_marker_when_store_refuses(popen, _isolated_approvals):
    for n in range(ap.MAX_PER_INSTANCE):
        adapters.run_agent(gem(), f"p{n}")
    out = adapters.run_agent(gem(), "quá hạn mức")
    assert out.startswith("[ERROR]") and ap.PENDING_MESSAGE not in out and popen == []


def test_claude_codex_below_full_do_not_create_requests(popen, _isolated_approvals):
    adapters.run_agent(Instance(name="c-1", engine="claude", role="R", autonomy="suggest"), "đọc thôi")
    assert _isolated_approvals.list_pending() == []


def test_override_level_runs_once_without_touching_instance(popen):
    i = gem()
    out = adapters.run_agent(i, "đã duyệt", override_level="full")
    assert "xong" in out and len(popen) == 1 and "gemini" in " ".join(popen[0]).lower()
    assert i.autonomy == "suggest"                            # SC2: bản gốc không đổi


def test_override_level_is_a_parameter_not_an_instance_attribute(popen):
    i = gem()
    i.override_level = "full"                                 # thuộc tính lạ trên Instance: không có tác dụng
    out = adapters.run_agent(i, "x")
    assert out.startswith("[ERROR]") and popen == []


@pytest.mark.parametrize("bad", ["root", "", 5])
def test_invalid_override_level_rejected(popen, bad):
    out = adapters.run_agent(gem(), "x", override_level=bad)
    assert out.startswith("[ERROR]") and popen == []


def _approved(store, prompt="việc đã đọc kỹ"):
    store._pin.set_pin(PIN)
    adapters.run_agent(gem(), prompt)
    [req] = store.list_pending()
    store.decide(req.id, "approve", "ui", pin=PIN)
    return req


def test_run_approved_runs_stored_prompt_once(popen, _isolated_approvals):
    store = _isolated_approvals
    req = _approved(store)
    seen = []

    def runner(inst, prompt, timeout=None, override_level=None):
        seen.append((inst, prompt, override_level))
        return "kết quả"
    assert ap.run_approved(req.id, runner=runner) == "kết quả"
    [(inst, prompt, lvl)] = seen
    assert prompt == "việc đã đọc kỹ" and lvl == "full"
    assert inst.name == "g-1" and inst.autonomy == "suggest"   # Instance dựng lại mang MỨC GỐC
    assert store.ui_view(req.id)["result"] == "kết quả"
    with pytest.raises(ap.ApprovalError):
        ap.run_approved(req.id, runner=runner)                  # dùng một lần
    assert len(seen) == 1


def test_run_approved_bus_message_carries_original_level_not_elevated(popen, _isolated_approvals):
    req = _approved(_isolated_approvals)
    ap.run_approved(req.id, runner=lambda i, p, timeout=None, override_level=None: 'xong [MSG coder-2:"chào"]')
    msgs = [m for m in BUS._msgs if m.sender == "g-1"]
    assert len(msgs) == 1 and msgs[0].internal is True and msgs[0].level == "suggest"   # SC7


def test_run_approved_refused_when_not_approved(popen, _isolated_approvals):
    store = _isolated_approvals
    adapters.run_agent(gem(), "chưa duyệt")
    [req] = store.list_pending()
    with pytest.raises(ap.ApprovalError):
        ap.run_approved(req.id, runner=lambda *a, **k: "không được chạy")


def test_run_approved_real_runner_uses_override(popen, _isolated_approvals):
    req = _approved(_isolated_approvals)
    out = ap.run_approved(req.id)                               # runner thật = adapters.run_agent
    assert "xong" in out and len(popen) == 1
