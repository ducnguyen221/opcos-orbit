"""TK3 (Giai đoạn 2): bộ tổng hợp `fleet` — song song, cô lập lỗi từng máy, ngân sách tần suất, lọc phản hồi không tin cậy,
một vòng chụp mỗi lúc. Client là giả; KHÔNG mở kết nối, KHÔNG đọc kho secret thật."""
import json
import threading
import time

import pytest

from server import fleet as fl
from server import peer_client as pc

APPR = "0123456789abcdef" * 2
GOOD_STATUS = {"jobs": [{"id": 3, "instance": "c-1", "engine": "codex", "state": "working", "elapsed": 1.5}],
               "summary": {"working": 1, "attention": 0, "approvals": 0}}
GOOD_APPR = {"approvals": [{"id": APPR, "n": 1, "instance": "g-1", "engine": "gemini", "level": "full",
                            "expires_in": 120, "fp16": "a" * 16, "state": "pending"}]}
GOOD_LEDGER = {"date": "2026-11-13", "engines": {"claude": {"count": 3, "cap": 40, "state": "ok"}},
               "triggers": {"human_turn": 3}, "outcomes": {"ok": 3}}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeClient:
    """Giả PeerClient: bảng đường -> phản hồi (hoặc ngoại lệ/hàm)."""
    log: list = []
    stamps: list = []                   # (tên, method, thời điểm theo đồng hồ giả)
    clock = None
    active: dict = {}
    max_active: dict = {}

    def __init__(self, name, routes, key=b"k", delay=0.0):
        self.name, self.routes, self.key, self.delay = name, routes, key, delay

    def fingerprint(self):
        return pc.key_fingerprint(self.key)

    def request(self, method, path, body=None):
        FakeClient.log.append((self.name, method, path))
        FakeClient.stamps.append((self.name, method, FakeClient.clock() if FakeClient.clock else 0.0))
        n = FakeClient.active.get(self.name, 0) + 1
        FakeClient.active[self.name] = n
        FakeClient.max_active[self.name] = max(FakeClient.max_active.get(self.name, 0), n)
        try:
            if self.delay:
                time.sleep(self.delay)
            r = self.routes.get((method, path))
            if callable(r):
                r = r()
            if isinstance(r, Exception):
                raise r
            if r is None:
                raise pc.PeerError("not_found")
            return 200, r
        finally:
            FakeClient.active[self.name] -= 1


def routes(info="may-2", status=GOOD_STATUS, appr=GOOD_APPR, ledger=GOOD_LEDGER):
    return {("GET", "/kira/info"): {"name": info}, ("GET", "/kira/status"): status,
            ("GET", "/kira/approvals"): appr, ("GET", "/kira/ledger"): ledger,
            ("POST", "/kira/stop"): {"ok": True, "id": 3},
            ("POST", f"/kira/approvals/{APPR}/reject"): {"ok": True, "state": "rejected"},
            ("POST", f"/kira/approvals/{APPR}/defer"): {"ok": True, "state": "deferred"}}


def make_fleet(peer_table, clock=None, **kw):
    """peer_table: {tên: dict(routes, key, delay) hoặc PeerError}."""
    FakeClient.log, FakeClient.stamps, FakeClient.active, FakeClient.max_active = [], [], {}, {}
    peers = [{"name": n, "url": f"http://100.64.0.{i + 5}:7790"} for i, n in enumerate(peer_table)]

    def make_client(name, url, **_):
        spec = peer_table[name]
        if isinstance(spec, Exception):
            raise spec
        return FakeClient(name, spec.get("routes", routes()), spec.get("key", name.encode() * 20), spec.get("delay", 0.0))
    clock = clock or Clock()
    FakeClient.clock = clock
    f = fl.Fleet(peers_provider=lambda: peers, make_client=make_client, mono=clock, **kw)
    return f, clock, peers


def by_name(snap, name):
    return next(m for m in snap["machines"] if m["name"] == name)


# ------------------------------------------------------------------ cơ bản -----------------------
def test_snapshot_shape_and_local_machine_first():
    f, _, _ = make_fleet({"may-2": {}}, local_provider=lambda: {"jobs": [], "summary": {}, "approvals": [], "ledger": {}})
    s = f.snapshot()
    assert [m["name"] for m in s["machines"]] == ["this", "may-2"] and s["machines"][0]["local"] is True
    m = by_name(s, "may-2")
    assert m["reachable"] is True and m["machine"] == "may-2" and m["jobs"][0]["id"] == 3
    assert m["approvals"][0]["id"] == APPR and m["ledger"]["engines"]["claude"]["count"] == 3


def test_no_peers_means_only_this_machine():
    f, _, _ = make_fleet({}, local_provider=lambda: {"jobs": [], "summary": {}, "approvals": [], "ledger": {}})
    assert [m["name"] for m in f.snapshot()["machines"]] == ["this"]


def test_local_provider_failure_is_isolated():
    def boom():
        raise RuntimeError("secret detail")
    f, _, _ = make_fleet({"may-2": {}}, local_provider=boom)
    s = f.snapshot()
    assert s["machines"][0]["reachable"] is False and "secret" not in json.dumps(s)
    assert by_name(s, "may-2")["reachable"] is True


# ------------------------------------------------------------------ cô lập lỗi (SC4) -------------
def test_failures_are_isolated_and_only_short_codes_leak():
    table = {"a": {}, "b": pc.PeerError("no_key"), "c": {"routes": {**routes(), ("GET", "/kira/status"): pc.PeerError("unauthorized")}},
             "d": {"routes": {**routes(), ("GET", "/kira/ledger"): pc.PeerError("timeout")}}}
    f, _, peers = make_fleet(table)
    s = f.snapshot()
    assert by_name(s, "a")["reachable"] is True
    assert (by_name(s, "b")["reachable"], by_name(s, "b")["error"]) == (False, "no_key")
    assert by_name(s, "c")["error"] == "unauthorized" and by_name(s, "d")["error"] == "timeout"
    blob = json.dumps(s)
    assert "100.64" not in blob and "7790" not in blob


def test_one_hanging_peer_does_not_stretch_snapshot_beyond_deadline():
    table = {"fast": {}, "slow": {"delay": 3.0}}
    f, _, _ = make_fleet(table, snapshot_deadline=0.6)
    t0 = time.monotonic()
    s = f.snapshot()
    assert time.monotonic() - t0 < 2.0
    assert by_name(s, "fast")["reachable"] is True
    assert (by_name(s, "slow")["reachable"], by_name(s, "slow")["error"]) == (False, "timeout")


def test_a_slow_peer_never_has_two_overlapping_polls():
    f, clock, _ = make_fleet({"slow": {"delay": 0.6}, "fast": {}}, cache_ttl=0.0, snapshot_deadline=0.15, get_budget=10 ** 6)
    for _ in range(6):                                    # nhiều vòng liền trong lúc lượt cũ của "slow" còn chạy
        f.snapshot()
        clock.t += 1
    time.sleep(1.5)                                       # chờ lượt chậm xong
    assert FakeClient.max_active.get("slow") == 1         # không bao giờ hai request đồng thời tới cùng một máy
    assert f._executor._max_workers >= fl.MAX_PEERS


def test_concurrent_snapshots_share_one_round():
    f, _, _ = make_fleet({"a": {"delay": 0.3}})
    results = []
    ts = [threading.Thread(target=lambda: results.append(f.snapshot())) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(results) == 6
    assert sum(1 for x in FakeClient.log if x[2] == "/kira/status") == 1      # một vòng chụp duy nhất


def test_cache_serves_within_ttl_and_refreshes_after():
    f, clock, _ = make_fleet({"a": {}}, cache_ttl=15.0, get_budget=100)
    f.snapshot()
    n1 = len(FakeClient.log)
    clock.t += 14
    f.snapshot()
    assert len(FakeClient.log) == n1
    clock.t += 2
    f.snapshot()
    assert len(FakeClient.log) > n1


# ------------------------------------------------------------------ ngân sách tần suất (điều kiện 5) --
def test_get_budget_never_exceeds_12_per_minute_per_peer_over_simulated_hour():
    f, clock, _ = make_fleet({"a": {}}, cache_ttl=15.0)
    stamps = []
    for _ in range(4 * 60):                               # 1 giờ, mỗi 15 s một lần gọi
        before = len(FakeClient.log)
        f.snapshot()
        stamps += [clock.t] * (len(FakeClient.log) - before)
        clock.t += 15.0
    for i, t0 in enumerate(stamps):
        window = [t for t in stamps if t0 <= t < t0 + 60.0]
        assert len(window) <= 12, f"{len(window)} GET trong 60 s"
    assert len(stamps) >= 40 * 3                          # vẫn thăm dò đều đặn, không tự bỏ đói


def test_info_is_cached_long():
    f, clock, _ = make_fleet({"a": {}}, cache_ttl=15.0, get_budget=100)
    for _ in range(10):
        f.snapshot()
        clock.t += 16
    assert sum(1 for x in FakeClient.log if x[2] == "/kira/info") == 1
    clock.t += 700
    f.snapshot()
    assert sum(1 for x in FakeClient.log if x[2] == "/kira/info") == 2


def test_over_budget_returns_stale_data_not_an_error():
    f, clock, _ = make_fleet({"a": {}}, cache_ttl=0.0, get_budget=4)
    s1 = f.snapshot()
    assert by_name(s1, "a")["reachable"] is True
    s2 = f.snapshot()                                     # hết ngân sách: dùng dữ liệu cũ
    m = by_name(s2, "a")
    assert m["reachable"] is True and m["stale"] is True and m["jobs"][0]["id"] == 3


def test_post_budget_is_separate_and_enforced_locally():
    f, clock, _ = make_fleet({"a": {}}, post_budget=3)
    for _ in range(3):
        assert f.act("a", "reject", APPR) == {"ok": True}
    before = len(FakeClient.log)
    assert f.act("a", "reject", APPR) == {"ok": False, "error": "rate_limited"}
    assert len(FakeClient.log) == before                  # không gửi gì
    clock.t += 61
    assert f.act("a", "reject", APPR) == {"ok": True}


# ------------------------------------------------------------------ lọc phản hồi độc hại (điều kiện 7) ------
HOSTILE = {
    "status not dict": {"status": ["x"]},
    "job id bool": {"status": {"jobs": [{"id": True, "instance": "c", "engine": "e", "state": "working"}]}},
    "job id huge": {"status": {"jobs": [{"id": 2 ** 40, "instance": "c", "engine": "e", "state": "working"}]}},
    "job state evil": {"status": {"jobs": [{"id": 1, "instance": "c", "engine": "e", "state": "<img onerror=1>"}]}},
    "instance too long": {"status": {"jobs": [{"id": 1, "instance": "x" * 65, "engine": "e", "state": "done"}]}},
    "instance bidi": {"status": {"jobs": [{"id": 1, "instance": "evil‮txt.exe", "engine": "e", "state": "done"}]}},
    "instance control": {"status": {"jobs": [{"id": 1, "instance": "a\x00b", "engine": "e", "state": "done"}]}},
    "instance zero width": {"status": {"jobs": [{"id": 1, "instance": "ad​min", "engine": "e", "state": "done"}]}},
    "instance newline": {"status": {"jobs": [{"id": 1, "instance": "a\nb", "engine": "e", "state": "done"}]}},
    "jobs too many": {"status": {"jobs": [{"id": i + 1, "instance": "c", "engine": "e", "state": "done"} for i in range(201)]}},
    "elapsed nan-like": {"status": {"jobs": [{"id": 1, "instance": "c", "engine": "e", "state": "done", "elapsed": float("inf")}]}},
    "elapsed str": {"status": {"jobs": [{"id": 1, "instance": "c", "engine": "e", "state": "done", "elapsed": "9"}]}},
    "summary bad": {"status": {"jobs": [], "summary": {"working": "1"}}},
    "approval id bad": {"appr": {"approvals": [{**GOOD_APPR["approvals"][0], "id": "../../x"}]}},
    "approval id upper": {"appr": {"approvals": [{**GOOD_APPR["approvals"][0], "id": APPR.upper()}]}},
    "approval level evil": {"appr": {"approvals": [{**GOOD_APPR["approvals"][0], "level": "root"}]}},
    "approval fp bad": {"appr": {"approvals": [{**GOOD_APPR["approvals"][0], "fp16": "z" * 16}]}},
    "approval state evil": {"appr": {"approvals": [{**GOOD_APPR["approvals"][0], "state": "approved"}]}},
    "approvals too many": {"appr": {"approvals": [GOOD_APPR["approvals"][0]] * 201}},
    "approvals not list": {"appr": {"approvals": {"a": 1}}},
    "ledger not dict": {"ledger": ["x"]},
    "info bad": {"info": "../x"},
    "info not str": {"info": 5},
}


@pytest.mark.parametrize("label", list(HOSTILE))
def test_hostile_peer_responses_become_bad_response(label):
    h = HOSTILE[label]
    rt = routes(info=h.get("info", "may-2"), status=h.get("status", GOOD_STATUS), appr=h.get("appr", GOOD_APPR),
                ledger=h.get("ledger", GOOD_LEDGER))
    if "info" in h and not isinstance(h["info"], str) or h.get("info") == "../x":
        rt[("GET", "/kira/info")] = {"name": h["info"]}
    f, _, _ = make_fleet({"a": {"routes": rt}})
    m = by_name(f.snapshot(), "a")
    assert m["reachable"] is False and m["error"] == "bad_response"
    assert "jobs" not in m and "approvals" not in m            # không lọt dữ liệu nào của máy phụ


def test_ledger_values_are_refiltered_by_hub():
    led = {**GOOD_LEDGER, "secret": "leak", "engines": {"claude": {"count": 3, "cap": 40, "state": "ok", "x": 1},
                                                       "evil" * 20: {"count": 1, "cap": 1, "state": "ok"}}}
    f, _, _ = make_fleet({"a": {"routes": routes(ledger=led)}})
    m = by_name(f.snapshot(), "a")
    assert list(m["ledger"]["engines"]) == ["claude"] and "leak" not in json.dumps(m)


# ------------------------------------------------------------------ trùng khoá / trùng tên (NS3) ---------
def test_two_peers_sharing_a_key_are_both_refused():
    f, _, _ = make_fleet({"a": {"key": b"same-key" * 8}, "b": {"key": b"same-key" * 8}, "c": {"key": b"other" * 20}})
    s = f.snapshot()
    assert by_name(s, "a")["error"] == "duplicate_key" and by_name(s, "b")["error"] == "duplicate_key"
    assert by_name(s, "c")["reachable"] is True
    assert not any(x[0] in ("a", "b") for x in FakeClient.log)          # không gọi máy nào trong cặp trùng


def test_duplicate_peer_names_and_bad_entries_are_refused():
    FakeClient.log = []
    peers = [{"name": "a", "url": "http://100.64.0.5:7790"}, {"name": "a", "url": "http://100.64.0.6:7790"},
             {"name": "BAD NAME", "url": "http://100.64.0.7:7790"}, {"url": "x"}, "string", None,
             {"name": "ok-1", "url": 5}]
    f = fl.Fleet(peers_provider=lambda: peers, make_client=lambda n, u, **k: FakeClient(n, routes(), n.encode() * 20),
                 mono=Clock())
    s = f.snapshot()
    names = [m["name"] for m in s["machines"]]
    assert names.count("a") == 1 and "BAD NAME" not in json.dumps(s)
    assert all(m.get("name") in ("this", "a", "ok-1", "?") for m in s["machines"])
    assert by_name(s, "a") == {"name": "a", "reachable": False, "error": "duplicate_name"}   # TẤT CẢ mục trùng bị từ chối
    assert sorted(m["error"] for m in s["machines"] if m.get("error")) == ["bad_config"] * 5 + ["duplicate_name"]
    assert not any(x[0] == "a" for x in FakeClient.log)       # không gọi máy nào trong nhóm trùng tên


def test_peers_provider_failure_or_too_many_peers_is_safe():
    def boom():
        raise RuntimeError("config hỏng")
    f = fl.Fleet(peers_provider=boom, make_client=lambda *a, **k: None, mono=Clock())
    assert [m["name"] for m in f.snapshot()["machines"]] == ["this"]
    many = [{"name": f"m{i}", "url": f"http://100.64.0.{i + 1}:7790"} for i in range(40)]
    g = fl.Fleet(peers_provider=lambda: many, make_client=lambda n, u, **k: FakeClient(n, routes(), n.encode() * 20), mono=Clock())
    assert len(g.snapshot()["machines"]) <= 1 + fl.MAX_PEERS


# ------------------------------------------------------------------ hành động (stop / reject / defer) ----
def test_act_validates_everything_before_any_call():
    f, _, _ = make_fleet({"a": {}})
    bad = [("nope", "stop", 3), ("a", "approve", APPR), ("a", "stop", 0), ("a", "stop", True), ("a", "stop", "3"),
           ("a", "reject", "../x"), ("a", "reject", APPR.upper()), ("a", "stop", APPR), ("a", "reject", 3),
           ("A B", "stop", 3), ("", "stop", 3), (None, "stop", 3), ("a", None, 3)]
    for peer, action, target in bad:
        r = f.act(peer, action, target)
        assert r["ok"] is False and r["error"] in ("not_found", "bad_request")
    assert FakeClient.log == []


def test_act_routes_to_the_right_peer_and_maps_errors():
    f, _, _ = make_fleet({"a": {}, "b": {"routes": {**routes(), ("POST", "/kira/stop"): pc.PeerError("not_found")}}})
    assert f.act("a", "stop", 3) == {"ok": True}
    assert f.act("b", "stop", 3) == {"ok": False, "error": "not_found"}
    assert [x for x in FakeClient.log if x[1] == "POST"] == [("a", "POST", "/kira/stop"), ("b", "POST", "/kira/stop")]


def test_act_invalidates_cache_so_next_snapshot_is_fresh():
    f, clock, _ = make_fleet({"a": {}}, cache_ttl=100.0, get_budget=100)
    f.snapshot()
    n = len(FakeClient.log)
    f.act("a", "defer", APPR)
    f.snapshot()
    assert len(FakeClient.log) > n + 1


def test_act_never_returns_peer_data():
    f, _, _ = make_fleet({"a": {"routes": {**routes(), ("POST", "/kira/stop"): {"ok": True, "leak": "x"}}}})
    assert f.act("a", "stop", 3) == {"ok": True}


# ------------------------------------------------------------------ sau review TK3 (Opus) ------------------
def test_dead_peer_never_shows_old_data_as_reachable():
    """RF1: máy sống một lần rồi chết — không được dựng lại việc/thẻ duyệt cũ như thể còn kết nối."""
    dead = {"on": False}

    def flaky():
        if dead["on"]:
            raise pc.PeerError("unreachable")
        return GOOD_STATUS
    f, clock, _ = make_fleet({"a": {"routes": routes(status=flaky)}})
    first = by_name(f.snapshot(), "a")
    assert first["reachable"] is True and first["jobs"]
    dead["on"] = True
    seen_stale = 0
    for _ in range(4 * 60):                                # 1 giờ, mỗi 15 s
        clock.t += 15.0
        m = by_name(f.snapshot(), "a")
        if m["reachable"]:
            assert m["stale"] is True and m["age"] <= fl.STALE_MAX_S      # chỉ dữ liệu cũ vừa mới, có tuổi
            seen_stale += 1
        else:
            assert m["error"] in ("unreachable", "rate_limited") and "jobs" not in m and "approvals" not in m
    assert seen_stale <= 1
    assert by_name(f.snapshot(), "a")["reachable"] is False


def test_stale_data_is_dropped_after_max_age_even_without_errors():
    f, clock, _ = make_fleet({"a": {}}, cache_ttl=0.0, get_budget=4)
    assert by_name(f.snapshot(), "a")["reachable"] is True
    clock.t += 10
    assert by_name(f.snapshot(), "a")["stale"] is True            # ngân sách hết, dữ liệu mới 10 s
    clock.t += fl.STALE_MAX_S + 5
    m = by_name(f.snapshot(), "a")
    assert m["reachable"] is True or m["error"] == "rate_limited"
    if m["reachable"]:
        assert m["stale"] is False                                 # đã thăm dò lại thật, không phải dữ liệu cũ


def test_act_refuses_duplicate_keys_names_and_urls_like_the_read_path():
    f, _, _ = make_fleet({"a": {"key": b"same-key" * 8}, "b": {"key": b"same-key" * 8}, "c": {}})
    assert f.act("a", "stop", 3) == {"ok": False, "error": "duplicate_key"}
    assert f.act("c", "stop", 3) == {"ok": True}
    FakeClient.log = []
    peers = [{"name": "a", "url": "http://100.64.0.5:7790"}, {"name": "a", "url": "http://100.64.0.6:7790"}]
    g = fl.Fleet(peers_provider=lambda: peers, make_client=lambda n, u, **k: FakeClient(n, routes(), n.encode() * 20),
                 mono=Clock())
    assert g.act("a", "stop", 3) == {"ok": False, "error": "duplicate_name"} and FakeClient.log == []
    same = [{"name": "p", "url": "http://100.64.0.5:7790"}, {"name": "q", "url": "http://100.64.0.5:7790"}]
    h = fl.Fleet(peers_provider=lambda: same, make_client=lambda n, u, **k: FakeClient(n, routes(), n.encode() * 20),
                 mono=Clock())
    assert h.act("p", "stop", 3) == {"ok": False, "error": "duplicate_url"}
    assert [m.get("error") for m in h.snapshot()["machines"][1:]] == ["duplicate_url", "duplicate_url"]


def test_act_requires_ok_true_from_the_peer():
    for resp in ({"ok": False}, {}, {"ok": "true"}, {"ok": 1}):
        f, _, _ = make_fleet({"a": {"routes": {**routes(), ("POST", "/kira/stop"): resp}}})
        assert f.act("a", "stop", 3) == {"ok": False, "error": "bad_response"}


def test_total_gets_plus_posts_stay_under_gateway_ceiling_with_interleaved_actions():
    """Mọi cửa sổ 60 s (GET + POST) ≤ 22 < trần 30/60 s của cổng, kể cả khi act xen giữa các vòng chụp."""
    f, clock, _ = make_fleet({"a": {}}, cache_ttl=15.0)
    for i in range(4 * 60):
        f.snapshot()
        if i % 2 == 0:
            f.act("a", "reject", APPR)
        clock.t += 7.0
    stamps = sorted(t for (_n, _m, t) in FakeClient.stamps)
    for t0 in stamps:
        assert len([t for t in stamps if t0 <= t < t0 + 60.0]) <= 22
    gets = sorted(t for (_n, m, t) in FakeClient.stamps if m == "GET")
    for t0 in gets:
        assert len([t for t in gets if t0 <= t < t0 + 60.0]) <= 12


@pytest.mark.parametrize("name", ["adㅤmin", "aᅟb", "x⠀y", "ok️", "v᠋w", "q­r",
                                  "a" + "́" * 5, "a\U000e0101b", "a​b", "a‮b", "tab\tbed"])
def test_invisible_and_filler_characters_are_rejected(name):
    st = {"jobs": [{"id": 1, "instance": name, "engine": "e", "state": "done"}], "summary": {}}
    f, _, _ = make_fleet({"a": {"routes": routes(status=st)}})
    assert by_name(f.snapshot(), "a")["error"] == "bad_response"


def test_normal_unicode_names_are_accepted():
    st = {"jobs": [{"id": 1, "instance": "máy-trạm-1 (Việt)", "engine": "claude", "state": "done"}], "summary": {}}
    f, _, _ = make_fleet({"a": {"routes": routes(status=st)}})
    assert by_name(f.snapshot(), "a")["jobs"][0]["instance"] == "máy-trạm-1 (Việt)"


def test_hanging_local_provider_does_not_hold_the_round(monkeypatch):
    monkeypatch.setattr(fl, "LOCAL_DEADLINE_S", 0.3)
    f, _, _ = make_fleet({"a": {}}, local_provider=lambda: time.sleep(5))
    t0 = time.monotonic()
    s = f.snapshot()
    assert time.monotonic() - t0 < 2.0
    assert s["machines"][0] == {"name": "this", "local": True, "reachable": False, "error": "local_error"}
    assert by_name(s, "a")["reachable"] is True


# ------------------------------------------------------------------ sau review TK3+TK4 (Opus) -------------
def test_local_provider_has_its_own_worker_and_does_not_queue_behind_a_hung_one(monkeypatch):
    monkeypatch.setattr(fl, "LOCAL_DEADLINE_S", 0.2)
    hang = threading.Event()
    f, clock, _ = make_fleet({"a": {}}, local_provider=lambda: hang.wait(3), cache_ttl=0.0, get_budget=10 ** 6)
    for _ in range(4):
        s = f.snapshot()
        clock.t += 1
        assert s["machines"][0]["error"] == "local_error"
        assert by_name(s, "a")["reachable"] is True
    hang.set()


def test_peer_state_is_reset_when_the_same_name_is_repinned_to_another_machine():
    holder = {"info": "may-cu", "url": "http://100.64.0.5:7790", "key": b"khoa-cu" * 10}
    FakeClient.log = []

    def peers():
        return [{"name": "may-2", "url": holder["url"]}]

    def make_client(name, url, **_):
        return FakeClient(name, routes(info=holder["info"]), holder["key"])
    clock = Clock()
    FakeClient.clock = clock
    f = fl.Fleet(peers_provider=peers, make_client=make_client, mono=clock, cache_ttl=0.0, get_budget=10 ** 6)
    assert by_name(f.snapshot(), "may-2")["machine"] == "may-cu"
    holder.update(info="may-moi", url="http://100.64.0.9:7790", key=b"khoa-moi" * 10)    # ghim lại sang máy khác
    clock.t += 1
    assert by_name(f.snapshot(), "may-2")["machine"] == "may-moi"        # không còn dùng info/last của máy cũ


def test_a_failing_round_never_returns_null():
    f, _, _ = make_fleet({"a": {}})
    f._prepare = lambda: (_ for _ in ()).throw(RuntimeError("hỏng"))
    s = f.snapshot()
    assert s["error"] == "round_failed" and s["machines"][0]["name"] == "this"


@pytest.mark.parametrize("name", ["a\u034fb", "x\ud7b0y"])
def test_extra_invisible_characters_rejected(name):
    st = {"jobs": [{"id": 1, "instance": name, "engine": "e", "state": "done"}], "summary": {}}
    f, _, _ = make_fleet({"a": {"routes": routes(status=st)}})
    assert by_name(f.snapshot(), "a")["error"] == "bad_response"
