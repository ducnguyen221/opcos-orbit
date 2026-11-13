"""Bộ tổng hợp đa máy (Giai đoạn 2, TK3): hub Orbit hỏi cổng Kira của các máy phụ và trả MỘT ảnh chụp thống nhất.

Quy tắc (SPEC mục 3, 6b, 6c + review TK3):
  - song song, CÔ LẬP LỖI từng máy: mỗi máy phụ một mục {reachable, error} với MÃ NGẮN (không URL/khoá/chi tiết);
  - tổng hạn chót `snapshot_deadline`; executor SỐNG LÂU (không `with`, ≥ MAX_PEERS worker), một vòng chụp tại một thời
    điểm (yêu cầu đồng thời dùng chung kết quả), **mỗi peer tối đa MỘT lượt thăm dò đang chạy**; cache 15 s;
  - NGÂN SÁCH TẦN SUẤT: ≤ 12 GET/60 s mỗi máy (dấu thời gian đóng NGAY TRƯỚC từng request; `/kira/info` cache 10 phút);
    POST hành động có ngân sách riêng (≤ 10/60 s) — cộng lại < trần 30/60 s của cổng; hết ngân sách GET ⇒ trả kết quả
    lần trước CHỈ khi đó là lần THÀNH CÔNG và ≤ 60 s tuổi (kèm `stale`, `age`); máy đã lỗi thì báo lỗi, KHÔNG dựng lại dữ liệu cũ;
  - mọi phản hồi của máy phụ là DỮ LIỆU KHÔNG TIN CẬY: bảng trắng trường, kiểu, độ dài ≤ 64, danh sách ≤ 200, id đúng
    khuôn, chuỗi không chứa ký tự điều khiển/đảo chiều/vô hình/chữ đệm; sai một chỗ ⇒ cả máy đó `bad_response`;
  - trùng tên, trùng khoá (băm trong RAM) hoặc trùng đích (IP:cổng) ⇒ các máy liên quan bị từ chối — Ở CẢ ĐỌC LẪN `act`;
  - hành động chỉ có stop / reject / defer, kiểm hết dạng tham số TRƯỚC khi gọi, máy phụ phải trả `ok: true`, không trả
    dữ liệu của máy phụ.
Tính năng TẮT mặc định: không có peer ⇒ chỉ máy này.
"""
from __future__ import annotations

import logging
import math
import re
import threading
import time
import unicodedata
from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait

from server import kira_gateway
from server import peer_client as pc

log = logging.getLogger(__name__)

MAX_PEERS = 16
MAX_LIST = 200
MAX_STR = 64
MAX_MARKS = 3
WINDOW_S = 60.0
INFO_TTL_S = 600.0
STALE_MAX_S = 60.0
LOCAL_DEADLINE_S = 2.0
_HEX32 = re.compile(r"[0-9a-f]{32}")
_HEX16 = re.compile(r"[0-9a-f]{16}")
_JOB_STATES = ("working", "blocked", "done", "error")
_APPR_STATES = ("pending", "deferred")
_LEVELS = ("suggest", "auto-safe", "full")
_SUMMARY_KEYS = ("blocked", "working", "done_unseen", "error_unseen", "attention", "approvals")
_INVISIBLE = {0x3164, 0x115F, 0x1160, 0x2800, 0xFFA0, 0x17B4, 0x17B5, 0x00AD, 0x034F}
_INVISIBLE_RANGES = ((0xFE00, 0xFE0F), (0xE0100, 0xE01EF), (0x1160, 0x11FF), (0x180B, 0x180F), (0xD7B0, 0xD7FF))


def _bad():
    raise pc.PeerError("bad_response")


def _safe_str(v, maxlen: int = MAX_STR) -> str:
    """Chuỗi hiển thị an toàn: 1…maxlen ký tự, không điều khiển/đảo chiều/vô hình/chữ đệm (nhóm Unicode C*, Zl, Zp,
    Zs ≠ ' ', bộ chọn biến thể, chữ đệm Hangul/Braille trống) và không quá MAX_MARKS dấu kết hợp liên tiếp."""
    if not isinstance(v, str) or not (1 <= len(v) <= maxlen):
        _bad()
    marks = 0
    for ch in v:
        cp = ord(ch)
        cat = unicodedata.category(ch)
        if (cat[0] == "C" or cat in ("Zl", "Zp") or (cat == "Zs" and ch != " ") or cp in _INVISIBLE
                or any(lo <= cp <= hi for lo, hi in _INVISIBLE_RANGES)):
            _bad()
        marks = marks + 1 if cat[0] == "M" else 0
        if marks > MAX_MARKS:
            _bad()
    return v


def _int(v, lo: int = 0, hi: int = 10 ** 9) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or not (lo <= v <= hi):
        _bad()
    return v


def _num(v, hi: float = 1e9) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not (0 <= v <= hi):
        _bad()
    return v


def _list(v) -> list:
    if not isinstance(v, list) or len(v) > MAX_LIST:
        _bad()
    return v


def filter_info(data) -> str:
    if not isinstance(data, dict) or not isinstance(data.get("name"), str):
        _bad()
    name = data["name"]
    if not kira_gateway._MACHINE_RE.fullmatch(name):
        _bad()
    return name


def filter_status(data) -> tuple:
    if not isinstance(data, dict):
        _bad()
    jobs = []
    for j in _list(data.get("jobs", [])):
        if not isinstance(j, dict) or j.get("state") not in _JOB_STATES:
            _bad()
        item = {"id": _int(j.get("id"), 1, 2 ** 31 - 1), "instance": _safe_str(j.get("instance")),
                "engine": _safe_str(j.get("engine"), 32), "state": j["state"]}
        if "elapsed" in j:
            item["elapsed"] = _num(j["elapsed"])
        jobs.append(item)
    raw = data.get("summary", {})
    if not isinstance(raw, dict):
        _bad()
    return jobs, {k: _int(raw[k]) for k in _SUMMARY_KEYS if k in raw}     # khoá lạ bị bỏ, không sửa


def filter_approvals(data) -> list:
    if not isinstance(data, dict):
        _bad()
    out = []
    for a in _list(data.get("approvals")):
        if not isinstance(a, dict):
            _bad()
        aid, fp = a.get("id"), a.get("fp16")
        if not (isinstance(aid, str) and _HEX32.fullmatch(aid) and isinstance(fp, str) and _HEX16.fullmatch(fp)):
            _bad()
        if a.get("level") not in _LEVELS or a.get("state") not in _APPR_STATES:
            _bad()
        out.append({"id": aid, "n": _int(a.get("n"), 0, 10 ** 6), "instance": _safe_str(a.get("instance")),
                    "engine": _safe_str(a.get("engine"), 32), "level": a["level"],
                    "expires_in": _int(a.get("expires_in"), 0, 86400), "fp16": fp, "state": a["state"]})
    return out


def filter_ledger(data) -> dict:
    if not isinstance(data, dict):
        _bad()
    return kira_gateway._filter_ledger(data)          # cùng bộ lọc bảng trắng với cổng, áp lại ở phía hub


class _Round:
    def __init__(self):
        self.done = threading.Event()
        self.result = None


class Fleet:
    def __init__(self, *, peers_provider, local_provider=None, make_client=pc.make_client, mono=time.monotonic,
                 cache_ttl: float = 15.0, snapshot_deadline: float = 8.0, get_budget: int = 12, post_budget: int = 10,
                 info_ttl: float = INFO_TTL_S, max_workers: int = MAX_PEERS, own_ports=(7788,),
                 allow_loopback: bool = False, key_dir=None):
        self._peers_provider, self._local_provider, self._make_client = peers_provider, local_provider, make_client
        self._mono, self._cache_ttl, self._deadline = mono, cache_ttl, snapshot_deadline
        self._get_budget, self._post_budget, self._info_ttl = get_budget, post_budget, info_ttl
        self._client_kw = {"own_ports": tuple(own_ports), "allow_loopback": allow_loopback, "key_dir": key_dir}
        self._allow_loopback, self._own_ports = allow_loopback, tuple(own_ports)
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max(max_workers, MAX_PEERS), thread_name_prefix="fleet")
        self._local_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fleet-local")  # không tranh worker với peer
        self._local_busy = False
        self._cache = None                              # (thời điểm, ảnh chụp)
        self._inflight = None
        self._state: dict = {}

    # ---------------------------------------------------------- trạng thái từng peer / ngân sách
    def _st(self, name: str) -> dict:
        with self._lock:
            return self._state.setdefault(name, {"gets": deque(), "posts": deque(), "info": None, "last": None,
                                                 "busy": False})

    def _prune(self, dq: deque, now: float) -> None:
        while dq and dq[0] <= now - WINDOW_S:
            dq.popleft()

    def _can_get(self, st: dict, n: int, now: float) -> bool:
        with self._lock:
            self._prune(st["gets"], now)
            return len(st["gets"]) + n <= self._get_budget

    def _stamp(self, dq: deque, budget: int) -> bool:
        """Đóng dấu NGAY TRƯỚC khi gửi một request; False nếu cửa sổ đã đầy."""
        with self._lock:
            now = self._mono()
            self._prune(dq, now)
            if len(dq) + 1 > budget:
                return False
            dq.append(now)
            return True

    # ---------------------------------------------------------- đọc cấu hình peer, trùng tên/khoá/đích
    def _read_peers(self) -> list:
        try:
            peers = self._peers_provider()
        except Exception as e:
            log.warning("fleet: peers_provider %s", type(e).__name__)
            return []
        return peers[:MAX_PEERS] if isinstance(peers, list) else []

    @staticmethod
    def _entry_ok(cfg) -> bool:
        return (isinstance(cfg, dict) and isinstance(cfg.get("name"), str) and bool(pc.NAME_RE.fullmatch(cfg["name"]))
                and isinstance(cfg.get("url"), str))

    def _prepare(self) -> list:
        """-> danh sách theo thứ tự cấu hình: dict (đã xong/lỗi) hoặc ('pending', tên, client). Dùng chung cho đọc và act."""
        peers = self._read_peers()
        names = [c["name"] for c in peers if self._entry_ok(c)]
        slots, shown_dup = [], set()
        for cfg in peers:
            if not self._entry_ok(cfg):
                slots.append({"name": "?", "reachable": False, "error": "bad_config"})
                continue
            name = cfg["name"]
            if names.count(name) > 1:                   # trùng tên: từ chối TẤT CẢ, hiện một mục báo lỗi
                if name not in shown_dup:
                    shown_dup.add(name)
                    slots.append({"name": name, "reachable": False, "error": "duplicate_name"})
                continue
            try:
                client = self._make_client(name, cfg["url"], **self._client_kw)
            except pc.PeerError as e:
                slots.append({"name": name, "reachable": False, "error": e.code})
                continue
            except Exception as e:
                log.warning("fleet: make_client %s", type(e).__name__)
                slots.append({"name": name, "reachable": False, "error": "bad_config"})
                continue
            slots.append(("pending", name, client, cfg["url"]))
        groups_key: dict = {}
        groups_url: dict = {}
        for s in slots:
            if isinstance(s, tuple):
                groups_key.setdefault(s[2].fingerprint(), []).append(s)
                try:
                    dest = pc.parse_peer_url(s[3], allow_loopback=self._allow_loopback, own_ports=self._own_ports)
                except pc.PeerError:
                    dest = s[3]
                groups_url.setdefault(dest, []).append(s)
        bad: dict = {}
        for groups, code in ((groups_key, "duplicate_key"), (groups_url, "duplicate_url")):
            for group in groups.values():
                if len(group) > 1:
                    for s in group:
                        bad.setdefault(id(s), code)
        return [({"name": s[1], "reachable": False, "error": bad[id(s)]} if isinstance(s, tuple) and id(s) in bad else s)
                for s in slots]

    # ---------------------------------------------------------- một vòng chụp
    def snapshot(self) -> dict:
        with self._lock:
            c = self._cache
            if c is not None and self._mono() - c[0] < self._cache_ttl:
                return c[1]
            rnd = self._inflight
            leader = rnd is None
            if leader:
                rnd = self._inflight = _Round()
        if not leader:
            rnd.done.wait(self._deadline + 2.0)
            if rnd.result is not None:
                return rnd.result
            with self._lock:
                return self._cache[1] if self._cache else {"machines": [], "generated": time.time(), "error": "busy"}
        snap = None
        try:
            try:
                snap = self._run_round()
            except Exception as e:                  # không bao giờ trả null: báo vòng chụp hỏng, giữ máy này
                log.warning("fleet: round %s", type(e).__name__)
                snap = {"machines": [self._local()], "generated": time.time(), "error": "round_failed"}
        finally:
            with self._lock:
                self._inflight = None
                if snap is not None:
                    self._cache = (self._mono(), snap)
            rnd.result = snap
            rnd.done.set()
        return snap

    def _local(self) -> dict:
        base = {"name": "this", "local": True}
        if self._local_provider is None:
            return {**base, "reachable": True, "jobs": [], "summary": {}, "approvals": [], "ledger": {}}
        with self._lock:
            busy = self._local_busy
            if not busy:
                self._local_busy = True
        if busy:                                                          # provider trước còn treo: không xếp hàng thêm
            return {**base, "reachable": False, "error": "local_error"}

        def call():
            try:
                return self._local_provider()
            finally:
                with self._lock:
                    self._local_busy = False
        try:
            fut = self._local_executor.submit(call)
            data = fut.result(timeout=LOCAL_DEADLINE_S)                  # provider treo không giữ vòng chụp
            return {**base, "reachable": True, **{k: data[k] for k in ("jobs", "summary", "approvals", "ledger")}}
        except Exception as e:
            log.warning("fleet: local %s", type(e).__name__)
            return {**base, "reachable": False, "error": "local_error"}

    def _run_round(self) -> dict:
        slots = self._prepare()
        futures = {}
        for i, s in enumerate(slots):
            if isinstance(s, tuple):
                futures[i] = self._executor.submit(self._poll, s[1], s[2], (s[1], s[2].fingerprint(), s[3]))
        wait(list(futures.values()), timeout=self._deadline)
        machines = [self._local()]
        for i, s in enumerate(slots):
            if isinstance(s, tuple):
                f = futures[i]
                try:
                    machines.append(f.result(timeout=0) if f.done() else {"name": s[1], "reachable": False, "error": "timeout"})
                except Exception as e:
                    log.warning("fleet: poll %s", type(e).__name__)
                    machines.append({"name": s[1], "reachable": False, "error": "bad_response"})
            else:
                machines.append(s)
        return {"machines": machines, "generated": time.time()}

    def _remember(self, st: dict, entry: dict, ok: bool) -> None:
        with self._lock:
            st["last"] = {"t": self._mono(), "entry": entry, "ok": ok}

    def _from_last(self, st: dict, name: str, fallback: str) -> dict:
        """Dữ liệu thay thế khi không thể thăm dò: chỉ lần THÀNH CÔNG ≤ STALE_MAX_S; lần lỗi thì báo lại lỗi đó."""
        with self._lock:
            last = st["last"]
        if last is not None:
            age = self._mono() - last["t"]
            if last["ok"] and age <= STALE_MAX_S:
                return {**last["entry"], "stale": True, "age": int(age)}
            if not last["ok"]:
                return last["entry"]
        return {"name": name, "reachable": False, "error": fallback}

    def _poll(self, name: str, client, ident=None) -> dict:
        st = self._st(ident or name)      # trạng thái khoá theo (tên, băm khoá, đích): ghim lại sang máy khác ⇒ trạng thái mới
        with self._lock:
            busy = st["busy"]                           # mỗi peer tối đa MỘT lượt thăm dò
            if not busy:
                st["busy"] = True
        if busy:
            return self._from_last(st, name, "timeout")
        try:
            return self._poll_locked(name, client, st)
        finally:
            with self._lock:
                st["busy"] = False

    def _poll_locked(self, name: str, client, st: dict) -> dict:
        now = self._mono()
        info = st["info"]
        info_fresh = info is not None and info[1] > now
        if not self._can_get(st, 3 + (0 if info_fresh else 1), now):
            return self._from_last(st, name, "rate_limited")

        def get(path: str):
            if not self._stamp(st["gets"], self._get_budget):
                raise pc.PeerError("rate_limited")
            return client.request("GET", path)[1]
        try:
            if info_fresh:
                machine = info[0]
            else:
                machine = filter_info(get("/kira/info"))
                with self._lock:
                    st["info"] = (machine, now + self._info_ttl)
            jobs, summary = filter_status(get("/kira/status"))
            approvals = filter_approvals(get("/kira/approvals"))
            ledger = filter_ledger(get("/kira/ledger"))
        except pc.PeerError as e:
            entry = {"name": name, "reachable": False, "error": e.code}
            self._remember(st, entry, False)
            return entry
        except Exception as e:
            log.warning("fleet: poll %s", type(e).__name__)
            entry = {"name": name, "reachable": False, "error": "bad_response"}
            self._remember(st, entry, False)
            return entry
        entry = {"name": name, "machine": machine, "reachable": True, "stale": False, "age": 0, "jobs": jobs,
                 "summary": summary, "approvals": approvals, "ledger": ledger}
        self._remember(st, entry, True)
        return entry

    # ---------------------------------------------------------- hành động: stop / reject / defer
    def act(self, peer, action, target) -> dict:
        if not (isinstance(peer, str) and pc.NAME_RE.fullmatch(peer) and action in ("stop", "reject", "defer")):
            return {"ok": False, "error": "bad_request"}
        if action == "stop":
            if not isinstance(target, int) or isinstance(target, bool) or not (1 <= target <= 2 ** 31 - 1):
                return {"ok": False, "error": "bad_request"}
            method, path, body = "POST", "/kira/stop", {"job_id": target}
        else:
            if not (isinstance(target, str) and _HEX32.fullmatch(target)):
                return {"ok": False, "error": "bad_request"}
            method, path, body = "POST", f"/kira/approvals/{target}/{action}", None
        slot = next((s for s in self._prepare() if (s[1] if isinstance(s, tuple) else s.get("name")) == peer), None)
        if slot is None:
            return {"ok": False, "error": "not_found"}
        if not isinstance(slot, tuple):                  # trùng tên/khoá/đích, thiếu khoá/ghim...: từ chối như đường đọc
            return {"ok": False, "error": slot.get("error", "bad_config")}
        if not self._stamp(self._st(peer)["posts"], self._post_budget):
            return {"ok": False, "error": "rate_limited"}
        try:
            _status, data = slot[2].request(method, path, body)
        except pc.PeerError as e:
            return {"ok": False, "error": e.code}
        except Exception as e:
            log.warning("fleet: act %s", type(e).__name__)
            return {"ok": False, "error": "bad_response"}
        if not isinstance(data, dict) or data.get("ok") is not True:
            return {"ok": False, "error": "bad_response"}    # máy phụ báo không thành công thì không báo thành công
        with self._lock:
            self._cache = None                          # lần chụp sau lấy dữ liệu mới
        return {"ok": True}
