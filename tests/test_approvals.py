"""Giao thức duyệt (bước 5, SPEC 2026-11-13): store yêu cầu duyệt + PIN. KHÔNG spawn tiến trình,
không đụng config.json, không đọc ~/.secret. Đồng hồ được tiêm vào (monotonic giả)."""
import json
import threading

import pytest

from server import approvals as ap
from server.config import Instance

PIN = "48291637"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def env(tmp_path):
    clock = Clock()
    pin = ap.PinStore(str(tmp_path / "pin.json"), now=clock)
    pin.set_pin(PIN)
    store = ap.ApprovalStore(now=clock, log_path=str(tmp_path / "approvals.jsonl"), pin=pin)
    return store, clock, pin, tmp_path


def inst(name="g-1", engine="gemini", **kw):
    return Instance(name=name, engine=engine, role=kw.pop("role", "Coder"), **kw)


def lines(tmp_path):
    p = tmp_path / "approvals.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


# ---------------------------------------------------------------- PIN -------
def test_pin_never_stored_in_plaintext(env):
    _, _, _, tmp = env
    assert PIN not in (tmp / "pin.json").read_text(encoding="utf-8")


def test_pin_verify_and_unset(tmp_path):
    clock = Clock()
    p = ap.PinStore(str(tmp_path / "p.json"), now=clock)
    assert p.configured() is False and p.verify("123456") is False
    p.set_pin(PIN)
    assert p.configured() is True
    assert p.verify(PIN) is True and p.verify("000000") is False


@pytest.mark.parametrize("bad", ["", "123", "12345", "1234567", None, 123456, "ab cdefgh"])
def test_set_pin_rejects_weak_or_invalid(tmp_path, bad):
    p = ap.PinStore(str(tmp_path / "p.json"), now=Clock())
    with pytest.raises(ValueError):
        p.set_pin(bad)


def test_pin_lockout_after_five_failures_then_expires(env):
    _, clock, pin, _ = env
    for _ in range(5):
        assert pin.verify("000000") is False
    assert pin.verify(PIN) is False                 # đang khoá: kể cả đúng cũng không qua
    clock.t += ap.PIN_LOCK_S + 1
    assert pin.verify(PIN) is True


def test_pin_file_corrupt_is_fail_closed(tmp_path):
    f = tmp_path / "p.json"
    f.write_text("{not json", encoding="utf-8")
    p = ap.PinStore(str(f), now=Clock())
    assert p.configured() is False and p.verify(PIN) is False


# ---------------------------------------------------------------- create ----
def test_create_snapshot_summary_and_fp(env):
    store, _, _, _ = env
    i = inst(session_id="s1", model="m", skip_permissions=False)
    r = store.create(i, "làm việc X", "full")
    assert r.state == "pending" and r.target_level == "full" and r.requester == "g-1"
    assert r.prompt_final == "làm việc X"
    assert r.summary == f"g-1 · gemini · mức full · #{r.job_fp[:8]}"
    assert "làm việc X" not in r.summary
    assert len(r.id) >= 32


def test_fp_covers_every_behavioral_field():
    base = inst(session_id="s", model="m")
    fp0 = ap.compute_fp(ap.snapshot(base), "p", "full")
    variants = [
        ap.compute_fp(ap.snapshot(base), "p2", "full"),
        ap.compute_fp(ap.snapshot(base), "p", "auto-safe"),
        ap.compute_fp(ap.snapshot(inst(role="Other", session_id="s", model="m")), "p", "full"),
        ap.compute_fp(ap.snapshot(inst(session_id="s2", model="m")), "p", "full"),
        ap.compute_fp(ap.snapshot(inst(session_id="s", model="m2")), "p", "full"),
        ap.compute_fp(ap.snapshot(inst(session_id="s", model="m", skip_permissions=True)), "p", "full"),
        ap.compute_fp(ap.snapshot(inst(name="x", session_id="s", model="m")), "p", "full"),
        ap.compute_fp(ap.snapshot(inst(engine="agy", session_id="s", model="m")), "p", "full"),
    ]
    assert len({fp0, *variants}) == len(variants) + 1


def test_snapshot_is_immutable_copy_of_instance(env):
    store, _, _, _ = env
    i = inst(role="Coder")
    r = store.create(i, "p", "full")
    i.role = "Hacker"                                # đổi nguồn sau khi tạo
    assert r.instance["role"] == "Coder"


def test_duplicate_fp_merges_into_one(env):
    store, _, _, tmp = env
    a = store.create(inst(), "p", "full")
    b = store.create(inst(), "p", "full")
    assert a.id == b.id
    assert len(store.list_pending()) == 1
    assert [x["event"] for x in lines(tmp)].count("created") == 1


def test_caps_per_instance_and_global(env):
    store, _, _, _ = env
    for n in range(ap.MAX_PER_INSTANCE):
        store.create(inst(), f"p{n}", "full")
    with pytest.raises(ap.ApprovalError) as e:
        store.create(inst(), "extra", "full")
    assert e.value.code == "too_many_for_instance"
    for k in range(ap.MAX_PENDING // ap.MAX_PER_INSTANCE + 1):
        for n in range(ap.MAX_PER_INSTANCE):
            try:
                store.create(inst(name=f"i{k}"), f"p{n}", "full")
            except ap.ApprovalError as err:
                assert err.code in ("too_many_pending", "too_many_for_instance")
    assert len(store.list_pending()) <= ap.MAX_PENDING
    with pytest.raises(ap.ApprovalError) as e2:
        store.create(inst(name="brand-new"), "q", "full")
    assert e2.value.code == "too_many_pending"


def test_expired_requests_are_purged_and_free_capacity(env):
    store, clock, _, _ = env
    for n in range(ap.MAX_PER_INSTANCE):
        store.create(inst(), f"p{n}", "full")
    clock.t += ap.TTL_S + 1
    assert store.list_pending() == []
    store.create(inst(), "again", "full")           # chỗ đã được giải phóng


def test_target_level_must_be_known(env):
    store, _, _, _ = env
    with pytest.raises(ap.ApprovalError):
        store.create(inst(), "p", "root")


# ---------------------------------------------------------------- decide ----
def test_ui_approve_requires_correct_pin(env):
    store, _, _, _ = env
    r = store.create(inst(), "p", "full")
    with pytest.raises(ap.ApprovalError) as e:
        store.decide(r.id, "approve", "ui", pin="000000")
    assert e.value.code == "bad_pin" and r.state == "pending"
    with pytest.raises(ap.ApprovalError) as e:
        store.decide(r.id, "approve", "ui", pin=None)
    assert e.value.code == "bad_pin"
    out = store.decide(r.id, "approve", "ui", pin=PIN)
    assert out.state == "approved" and out.decided_by == "ui"


def test_approve_disabled_when_pin_not_configured(tmp_path):
    clock = Clock()
    store = ap.ApprovalStore(now=clock, log_path=str(tmp_path / "l.jsonl"),
                             pin=ap.PinStore(str(tmp_path / "none.json"), now=clock))
    r = store.create(inst(), "p", "full")
    with pytest.raises(ap.ApprovalError) as e:
        store.decide(r.id, "approve", "ui", pin=PIN)
    assert e.value.code == "pin_not_set"
    store.decide(r.id, "reject", "ui")               # từ chối không cần PIN


def test_kira_can_never_approve_even_with_pin(env):
    store, _, _, _ = env
    r = store.create(inst(), "p", "full")
    with pytest.raises(ap.ApprovalError) as e:
        store.decide(r.id, "approve", "kira", pin=PIN)
    assert e.value.code == "channel_cannot_approve" and r.state == "pending"


def test_kira_can_reject_and_defer(env):
    store, _, _, _ = env
    a = store.create(inst(), "a", "full")
    b = store.create(inst(), "b", "full")
    assert store.decide(a.id, "reject", "kira").state == "rejected"
    d = store.decide(b.id, "defer", "kira")
    assert d.state == "deferred" and d.decided_by == "kira"
    assert store.decide(b.id, "approve", "ui", pin=PIN).state == "approved"   # hoãn vẫn duyệt được trên UI


def test_unknown_channel_or_decision_refused(env):
    store, _, _, _ = env
    r = store.create(inst(), "p", "full")
    for ch, dec in [("telepathy", "reject"), ("ui", "maybe"), (None, "reject"), ("ui", None)]:
        with pytest.raises(ap.ApprovalError):
            store.decide(r.id, dec, ch)
    assert r.state == "pending"


def test_unknown_id_and_expired_and_double_decide(env):
    store, clock, _, _ = env
    with pytest.raises(ap.ApprovalError) as e:
        store.decide("nope", "reject", "ui")
    assert e.value.code == "not_found"
    r = store.create(inst(), "p", "full")
    store.decide(r.id, "reject", "ui")
    with pytest.raises(ap.ApprovalError) as e:
        store.decide(r.id, "reject", "ui")
    assert e.value.code == "not_pending"
    r2 = store.create(inst(), "q", "full")
    clock.t += ap.TTL_S + 1
    with pytest.raises(ap.ApprovalError) as e:
        store.decide(r2.id, "approve", "ui", pin=PIN)
    assert e.value.code in ("expired", "not_found")


def test_concurrent_approvals_exactly_one_wins(env):
    store, _, _, _ = env
    r = store.create(inst(), "p", "full")
    results, barrier = [], threading.Barrier(8)

    def worker():
        barrier.wait()
        try:
            store.decide(r.id, "approve", "ui", pin=PIN)
            results.append("ok")
        except ap.ApprovalError as e:
            results.append(e.code)
    ts = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert results.count("ok") == 1


# ---------------------------------------------------------------- run once --
def test_take_for_run_single_use_and_returns_stored_prompt(env):
    store, _, _, _ = env
    r = store.create(inst(), "nội dung đã duyệt", "full")
    with pytest.raises(ap.ApprovalError) as e:
        store.take_for_run(r.id)                      # chưa duyệt
    assert e.value.code == "not_approved"
    store.decide(r.id, "approve", "ui", pin=PIN)
    got = store.take_for_run(r.id)
    assert got.prompt_final == "nội dung đã duyệt" and got.state == "consumed"
    with pytest.raises(ap.ApprovalError):
        store.take_for_run(r.id)


def test_take_for_run_refuses_when_hash_no_longer_matches(env):
    store, _, _, _ = env
    r = store.create(inst(), "p", "full")
    store.decide(r.id, "approve", "ui", pin=PIN)
    r.prompt_final = "bị thay"                        # giả lập sửa trong RAM
    with pytest.raises(ap.ApprovalError) as e:
        store.take_for_run(r.id)
    assert e.value.code == "tampered"


def test_take_for_run_refuses_after_expiry(env):
    store, clock, _, _ = env
    r = store.create(inst(), "p", "full")
    store.decide(r.id, "approve", "ui", pin=PIN)
    clock.t += ap.TTL_S + 1
    with pytest.raises(ap.ApprovalError):
        store.take_for_run(r.id)


# ---------------------------------------------------------------- views -----
def test_kira_view_has_no_prompt_and_ui_view_has(env):
    store, _, _, _ = env
    r = store.create(inst(), "TUYỆT MẬT prompt", "full")
    kv = store.kira_list()
    assert kv and "TUYỆT MẬT" not in json.dumps(kv, ensure_ascii=False)
    assert set(kv[0]) <= {"id", "n", "instance", "engine", "level", "expires_in", "fp16", "state"}
    assert kv[0]["fp16"] == r.job_fp[:16]
    assert "TUYỆT MẬT prompt" in json.dumps(store.ui_view(r.id), ensure_ascii=False)


def test_pending_count_excludes_deferred(env):
    store, _, _, _ = env
    a = store.create(inst(), "a", "full")
    store.create(inst(), "b", "full")
    assert store.pending_count() == 2
    store.decide(a.id, "defer", "ui")
    assert store.pending_count() == 1


# ---------------------------------------------------------------- log -------
def test_log_one_line_per_transition_without_prompt_or_pin(env):
    store, clock, _, tmp = env
    r = store.create(inst(), "SECRET-PROMPT-TEXT", "full")
    store.decide(r.id, "approve", "ui", pin=PIN)
    store.take_for_run(r.id)
    ev = lines(tmp)
    assert [e["event"] for e in ev] == ["created", "approved", "consumed"]
    raw = (tmp / "approvals.jsonl").read_text(encoding="utf-8")
    assert "SECRET-PROMPT-TEXT" not in raw and PIN not in raw
    assert set(ev[0]) >= {"id", "job_fp", "requester", "target_level", "event", "ts"}
    assert ev[1]["decided_by"] == "ui"


def test_log_expired_and_rejected(env):
    store, clock, _, tmp = env
    a = store.create(inst(), "a", "full")
    store.decide(a.id, "reject", "kira")
    store.create(inst(), "b", "full")
    clock.t += ap.TTL_S + 1
    store.list_pending()
    names = [e["event"] for e in lines(tmp)]
    assert names == ["created", "rejected", "created", "expired"]
