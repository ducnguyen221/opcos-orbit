"""Giao thức duyệt (bước 5, SPEC 2026-11-13, phương án B+ có PIN).

Khi một việc bị chặn vì mức tự trị, Orbit tạo MỘT yêu cầu duyệt có hạn dùng. Người duyệt đọc đủ nội dung
trên UI và Approve bằng PIN; việc đó chạy ĐÚNG MỘT LẦN với đúng nội dung đã lưu, không đổi config.json,
không đổi Instance.autonomy. Kênh Kira chỉ được xem / Từ chối / Hoãn — KHÔNG có đường Approve.

Giới hạn trung thực (SPEC RK1): module này không chặn một tiến trình cục bộ cùng tài khoản gọi được HTTP tự
duyệt. Nó chống kẻ ngoài mạng, nhầm lẫn và duyệt mù; PIN thêm một lớp ngoài "cùng tài khoản gọi được HTTP".
Nhật ký chỉ ghi id/băm/kênh/thời điểm — KHÔNG ghi prompt, KHÔNG ghi PIN.
"""
from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field

TTL_S = 300
MAX_PENDING = 20
MAX_PER_INSTANCE = 3
PIN_LOCK_S = 60            # khoá lần 1; mỗi lần khoá sau gấp đôi, tối đa PIN_LOCK_MAX_S (backoff luỹ tiến)
PIN_LOCK_MAX_S = 300
PIN_MAX_FAILS = 5
PIN_MIN_LEN = 8
MAX_PROMPT = 20000
TERMINAL_PROMPT_KEEP = 200
LOG_MAX_BYTES = 1_000_000
APPROVED_GRACE_S = 60      # đã duyệt thì còn thêm thời gian ngắn để chạy, kể cả sát hạn
LEVELS = ("suggest", "auto-safe", "full")
CHANNELS = ("ui", "kira")
DECISIONS = ("approve", "reject", "defer")
OPEN_STATES = ("pending", "deferred")
KEEP_TERMINAL = 100
RESULT_MAX = 4000
PENDING_MESSAGE = "[CHỜ DUYỆT — người duyệt trên UI]"   # thứ DUY NHẤT agent/Lead được thấy (không kèm id)


class ApprovalError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


# ------------------------------------------------------------------ băm -----
def snapshot(inst) -> dict:
    """Ảnh chụp các trường của Instance ảnh hưởng hành vi lượt chạy."""
    return {
        "name": str(getattr(inst, "name", "")),
        "engine": str(getattr(inst, "engine", "")),
        "role": str(getattr(inst, "role", "")),
        "session_id": str(getattr(inst, "session_id", "") or ""),
        "model": str(getattr(inst, "model", "") or ""),
        "skip_permissions": bool(getattr(inst, "skip_permissions", False)),
        "cwd": str(getattr(inst, "cwd", "") or ""),
        "autonomy": str(getattr(inst, "autonomy", "suggest")),   # MỨC GỐC (dùng cho level của tin bus)
        "limit_reason": str(getattr(inst, "limit_reason", "") or ""),          # người duyệt PHẢI thấy
        "limit_untrusted": bool(getattr(inst, "limit_untrusted", False)),      # nguồn không xác thực
    }


def compute_fp(snap: dict, prompt: str, target_level: str) -> str:
    blob = json.dumps({"i": snap, "p": prompt, "l": target_level}, sort_keys=True,
                      ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ PIN -----
class PinStore:
    """PIN của người duyệt: lưu băm scrypt có muối, không bao giờ lưu rõ. Sai quá 5 lần => khoá 300 s."""

    def __init__(self, path: str, now=time.monotonic):
        self.path, self._now = path, now
        self._lock = threading.Lock()
        self._fails = 0
        self._locked_until = 0.0
        self._lock_level = 0
        self._rec = None         # băm đã nạp: ĐÃ nạp rồi thì KHÔNG đọc lại đĩa (ghi đè tệp không có tác dụng)

    def _load(self):
        if self._rec is not None:
            return self._rec
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            self._rec = (base64.b64decode(d["salt"]), base64.b64decode(d["hash"]),
                         int(d["n"]), int(d["r"]), int(d["p"]))
            return self._rec
        except (OSError, ValueError, KeyError, TypeError):
            return None          # thiếu/hỏng => coi như chưa đặt (fail-closed); lần sau đọc lại cho tới khi có

    @staticmethod
    def _derive(pin: str, salt: bytes, n: int, r: int, p: int) -> bytes:
        return hashlib.scrypt(pin.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)

    def configured(self) -> bool:
        return self._load() is not None

    def set_pin(self, pin) -> None:
        if not isinstance(pin, str) or len(pin) < PIN_MIN_LEN or not (pin.isascii() and pin.isalnum()):
            raise ValueError(f"PIN cần >= {PIN_MIN_LEN} ký tự chữ-số ASCII")
        salt, n, r, p = secrets.token_bytes(16), 2 ** 14, 8, 1
        rec = {"v": 1, "n": n, "r": r, "p": p,
               "salt": base64.b64encode(salt).decode(),
               "hash": base64.b64encode(self._derive(pin, salt, n, r, p)).decode()}
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)     # quyền hẹp ngay lúc tạo (POSIX)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rec, f)
        os.replace(tmp, self.path)
        self._rec = (salt, base64.b64decode(rec["hash"]), n, r, p)

    def locked(self) -> bool:
        with self._lock:
            return self._now() < self._locked_until

    def verify(self, pin) -> bool:
        with self._lock:
            t = self._now()
            if self._locked_until and t >= self._locked_until:
                self._locked_until, self._fails = 0.0, 0
            if t < self._locked_until:
                return False
            rec = self._load()
            if rec is None or not isinstance(pin, str) or not pin or len(pin) > 64:
                ok = False
            else:
                salt, want, n, r, p = rec
                ok = hmac.compare_digest(self._derive(pin, salt, n, r, p), want)
            if ok:
                self._fails, self._lock_level = 0, 0
                return True
            self._fails += 1
            if self._fails >= PIN_MAX_FAILS:
                self._locked_until = t + min(PIN_LOCK_S * (2 ** self._lock_level), PIN_LOCK_MAX_S)
                self._lock_level += 1
            return False


# ------------------------------------------------------------------ store ---
@dataclass
class ApprovalRequest:
    id: str
    created_at: float
    expires_at: float
    requester: str
    kind: str
    target_level: str
    job_fp: str
    prompt_final: str
    instance: dict
    summary: str
    state: str = "pending"
    decided_by: str | None = None
    decided_at: float | None = None
    result: str | None = field(default=None, repr=False)


class ApprovalStore:
    def __init__(self, *, now=time.monotonic, log_path: str | None = None, pin: PinStore | None = None,
                 ttl: float = TTL_S):
        self._now, self._log_path, self._pin, self._ttl = now, log_path, pin, ttl
        self._reqs: "dict[str, ApprovalRequest]" = {}
        self._lock = threading.RLock()

    # ---- nhật ký ----
    def _log(self, event: str, r: ApprovalRequest, strict: bool = False) -> None:
        if not self._log_path:
            return
        line = json.dumps({"ts": time.time(), "event": event, "id": r.id, "job_fp": r.job_fp,
                           "requester": r.requester, "target_level": r.target_level,
                           "decided_by": r.decided_by}, ensure_ascii=False)
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self._log_path)), exist_ok=True)
            if os.path.exists(self._log_path) and os.path.getsize(self._log_path) >= LOG_MAX_BYTES:
                os.replace(self._log_path, self._log_path + ".1")        # xoay vòng: giữ một bản cũ
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            if strict:
                raise ApprovalError("log_failed", "không ghi được nhật ký duyệt") from None

    # ---- hạn dùng / dọn ----
    def _purge(self) -> None:
        t = self._now()
        for r in list(self._reqs.values()):
            if r.state in OPEN_STATES + ("approved",) and r.expires_at <= t:
                r.state = "expired"
                self._log("expired", r)
                del self._reqs[r.id]
        done = [r for r in self._reqs.values() if r.state not in OPEN_STATES + ("approved",)]
        for r in sorted(done, key=lambda x: x.created_at)[:max(0, len(done) - KEEP_TERMINAL)]:
            del self._reqs[r.id]

    def _get(self, rid) -> ApprovalRequest:
        r = self._reqs.get(rid) if isinstance(rid, str) else None
        if r is None:
            raise ApprovalError("not_found")
        return r

    # ---- tạo ----
    def create(self, inst, prompt_final: str, target_level: str, kind: str = "run_once",
               timeout: int = 120) -> ApprovalRequest:
        if target_level not in LEVELS or not isinstance(prompt_final, str):
            raise ApprovalError("invalid")
        if len(prompt_final) > MAX_PROMPT:
            raise ApprovalError("prompt_too_long")
        snap = snapshot(inst)
        snap["timeout"] = int(timeout)                  # lượt chạy lại phải dùng đúng timeout gốc
        fp = compute_fp(snap, prompt_final, target_level)
        with self._lock:
            self._purge()
            for r in self._reqs.values():
                if r.state in OPEN_STATES and r.job_fp == fp:
                    return r                                 # gộp yêu cầu trùng
            open_ = [r for r in self._reqs.values() if r.state in OPEN_STATES]
            if len(open_) >= MAX_PENDING:
                raise ApprovalError("too_many_pending")
            if sum(1 for r in open_ if r.requester == snap["name"]) >= MAX_PER_INSTANCE:
                raise ApprovalError("too_many_for_instance")
            t = self._now()
            r = ApprovalRequest(id=secrets.token_hex(16), created_at=t, expires_at=t + self._ttl,
                                requester=snap["name"], kind=kind, target_level=target_level, job_fp=fp,
                                prompt_final=prompt_final, instance=snap,
                                summary=f"{snap['name']} · {snap['engine']} · mức {target_level} · #{fp[:8]}")
            self._reqs[r.id] = r
            self._log("created", r)
            return r

    # ---- quyết định ----
    def decide(self, rid, decision, channel, pin=None, confirm_untrusted: bool = False) -> ApprovalRequest:
        if channel not in CHANNELS or decision not in DECISIONS:
            raise ApprovalError("invalid")
        with self._lock:
            self._purge()
            r = self._get(rid)
            if r.state not in OPEN_STATES:
                raise ApprovalError("not_pending")
            if decision == "approve":
                if channel != "ui":
                    raise ApprovalError("channel_cannot_approve")
                if self._pin is None or not self._pin.configured():
                    raise ApprovalError("pin_not_set")
                if r.instance.get("limit_untrusted") and not confirm_untrusted:
                    raise ApprovalError("confirm_untrusted")      # nguồn không xác thực: cần xác nhận rõ
                if self._pin.locked():
                    raise ApprovalError("pin_locked")
                if not self._pin.verify(pin):
                    raise ApprovalError("bad_pin")
                r.decided_by, r.decided_at = channel, self._now()
                self._log("approved", r, strict=True)         # ghi TRƯỚC khi đổi trạng thái
                r.state = "approved"
                r.expires_at = max(r.expires_at, self._now() + APPROVED_GRACE_S)
                return r
            new = "rejected" if decision == "reject" else "deferred"
            r.state, r.decided_by, r.decided_at = new, channel, self._now()
            if new == "rejected":
                r.prompt_final = r.prompt_final[:TERMINAL_PROMPT_KEEP]       # trạng thái cuối: bỏ nội dung đầy đủ
            self._log(new, r)
            return r

    def take_for_run(self, rid) -> ApprovalRequest:
        """Chuyển approved -> consumed (dùng một lần) và trả đúng nội dung đã duyệt."""
        with self._lock:
            self._purge()
            r = self._get(rid)
            if r.state != "approved":
                raise ApprovalError("not_approved")
            if compute_fp(r.instance, r.prompt_final, r.target_level) != r.job_fp:
                raise ApprovalError("tampered")
            self._log("consumed", r, strict=True)
            r.state = "consumed"
            out = dataclasses.replace(r)                         # bản đầy đủ cho lượt chạy
            r.prompt_final = r.prompt_final[:TERMINAL_PROMPT_KEEP]  # bản lưu giữ chỉ còn phần đầu
            return out

    def pin_configured(self) -> bool:
        return self._pin is not None and self._pin.configured()

    def set_result(self, rid, text) -> None:
        with self._lock:
            r = self._reqs.get(rid)
            if r is not None:
                r.result = (text or "")[:RESULT_MAX]

    def mark_failed(self, rid, text) -> None:
        """Lượt chạy đã `consumed` nhưng hỏng giữa chừng: lưu lỗi để người duyệt thấy + ghi nhật ký."""
        with self._lock:
            r = self._reqs.get(rid)
            if r is not None:
                r.result = (text or "")[:RESULT_MAX]
                self._log("failed", r)

    # ---- truy vấn ----
    def list_pending(self) -> list:
        with self._lock:
            self._purge()
            return [r for r in self._reqs.values() if r.state == "pending"]

    def pending_count(self) -> int:
        return len(self.list_pending())

    def _expires_in(self, r) -> int:
        return max(0, int(r.expires_at - self._now()))

    def kira_list(self) -> list:
        """Cho kênh Kira: KHÔNG prompt, KHÔNG instance đầy đủ."""
        with self._lock:
            self._purge()
            open_ = sorted((r for r in self._reqs.values() if r.state in OPEN_STATES), key=lambda x: x.created_at)
            return [{"id": r.id, "n": i + 1, "instance": r.requester, "engine": r.instance["engine"],
                     "level": r.target_level, "expires_in": self._expires_in(r),
                     "fp16": r.job_fp[:16], "state": r.state} for i, r in enumerate(open_)]

    def _ui(self, r) -> dict:
        return {"id": r.id, "state": r.state, "summary": r.summary, "requester": r.requester,
                "engine": r.instance["engine"], "role": r.instance["role"], "target_level": r.target_level,
                "prompt": r.prompt_final, "fp16": r.job_fp[:16], "expires_in": self._expires_in(r),
                "decided_by": r.decided_by, "result": r.result,
                "limit_reason": r.instance.get("limit_reason", ""),
                "limit_untrusted": bool(r.instance.get("limit_untrusted")),
                "skip_permissions": bool(r.instance.get("skip_permissions")),
                # agy + skip_permissions + mức full => chạy với cờ bỏ-qua-quyền của CLI: người duyệt phải thấy
                "runs_with_bypass": r.instance.get("engine") == "agy" and bool(r.instance.get("skip_permissions"))}

    def ui_view(self, rid) -> dict:
        with self._lock:
            self._purge()
            return self._ui(self._get(rid))

    def ui_list(self) -> list:
        with self._lock:
            self._purge()
            return [self._ui(r) for r in sorted(self._reqs.values(), key=lambda x: -x.created_at)]


# ------------------------------------------------------------------ chạy một lần
def run_approved(rid: str, store: "ApprovalStore | None" = None, runner=None) -> str:
    """Chạy ĐÚNG MỘT LẦN việc đã được duyệt: nội dung `prompt_final` đã lưu (không dựng lại từ inbox/attach),
    Instance dựng từ ảnh chụp với MỨC GỐC; mức chạy nâng lên chỉ qua tham số `override_level` của lượt này.
    Tin [MSG] do lượt này phát lên bus mang `level` = mức GỐC, không phải mức đã nâng (chống rửa quyền)."""
    from server.bus import BUS
    from server.config import Instance
    from server.orchestrator import parse_markers
    store = store or get_store()
    if runner is None:
        from server.adapters import run_agent as runner
    req = store.take_for_run(rid)
    snap = req.instance
    inst = Instance(name=snap["name"], engine=snap["engine"], role=snap["role"], session_id=snap["session_id"],
                    model=snap["model"], skip_permissions=snap["skip_permissions"], autonomy=snap["autonomy"])
    try:
        result = runner(inst, req.prompt_final, timeout=snap.get("timeout", 120), override_level=req.target_level)
    except Exception as e:                       # đã `consumed`: phải để lại dấu vết, không nuốt im lặng
        result = f"[ERROR] {inst.name}: {e}"
        store.mark_failed(rid, result)
        return result
    store.set_result(rid, result)
    for to, txt in parse_markers(result)["msg"]:
        BUS.post(inst.name, to, txt, internal=True, level=snap["autonomy"])
    return result


# ------------------------------------------------------------------ mặc định -
_STORE: ApprovalStore | None = None
_STORE_LOCK = threading.Lock()


def default_pin_path() -> str:
    return os.environ.get("ORBIT_PIN_FILE") or os.path.join(
        os.path.expanduser("~"), ".secret", "orbit", "approval-pin.json")


def get_store() -> ApprovalStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sessions", "approvals.jsonl")
            _STORE = ApprovalStore(log_path=os.path.normpath(log), pin=PinStore(default_pin_path()))
        return _STORE


def _cli() -> None:                                     # pragma: no cover (tương tác thật)
    import getpass
    import sys
    if len(sys.argv) != 2 or sys.argv[1] != "set-pin":
        print("dùng: python -m server.approvals set-pin", file=sys.stderr)
        raise SystemExit(2)
    a, b = getpass.getpass("PIN mới: "), getpass.getpass("Nhập lại: ")
    if a != b:
        print("Hai lần nhập không khớp.", file=sys.stderr)
        raise SystemExit(1)
    try:
        PinStore(default_pin_path()).set_pin(a)
    except ValueError as e:
        print(f"PIN không hợp lệ: {e}", file=sys.stderr)
        raise SystemExit(1) from None
    print("Đã đặt PIN.")


if __name__ == "__main__":                              # pragma: no cover
    _cli()
