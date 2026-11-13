"""Phía KHÁCH của cổng Kira (Giai đoạn 2 đa máy, TK1): hub Orbit ký HMAC rồi gọi sang cổng Kira của máy phụ.

Nguyên tắc (SPEC mục 3, 6b, 6c — mọi lỗi chỉ là MÃ NGẮN, không bao giờ lộ URL, đường khoá hay khoá):
  - đích: chỉ `http://<IP literal>:<cổng>` thuộc dải riêng/CGNAT (Tailscale)/ULA; phân tích bằng `ipaddress`, kết nối
    ĐÚNG đối tượng IP đã phân tích (không dựng lại chuỗi URL) ⇒ không redirect, không proxy, không DNS, không TOCTOU;
    loopback chỉ khi bật tường minh bằng tham số (test), không đặt được từ config;
  - bảng trắng cứng sáu đường (so khớp chính xác method + toàn bộ đường); id kiểm trước khi dựng đường;
  - khoá riêng từng máy trong thư mục khoá của hub (đường suy từ TÊN, `realpath` phải nằm trong thư mục, không liên kết,
    ≤ 1 KB, khuôn hex/base64url, đọc bằng `kira_gateway.load_secret` để hai đầu cùng một chuỗi byte, tệp không đổi
    trong lúc đọc); URL của peer được GHIM cạnh khoá (`<tên>.url`), URL ở config phải bằng URL ghim;
  - hạn chót TỔNG THẬT: đồng hồ canh (Timer) đóng socket khi hết hạn + `settimeout` theo thời gian còn lại, nên một máy
    phụ nhỏ giọt từng byte (header lẫn thân) cũng không giữ luồng quá hạn; trần 256 KB; JSON chặt (từ chối
    NaN/Infinity/số tràn, khoá trùng, lồng sâu, số khổng lồ, kiểu ≠ object);
  - ngoại lệ ném ra KHÔNG mang ngữ cảnh của lỗi gốc (`__context__` rỗng) để traceback/log không lộ đường khoá, IP, thân phản hồi.
Không có hàm nào ở đây ghi khoá hay tạo secret (việc đó là CLI `peer_keys` do Đức chạy tay).
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import ipaddress
import json
import math
import os
import re
import secrets
import socket
import threading
import time
from typing import Callable

from server import kira_gateway

MAX_BYTES = 256 * 1024
MAX_KEY_FILE = 1024
MAX_PIN_FILE = 256
DEFAULT_TIMEOUT = 4.0
DEFAULT_DEADLINE = 6.0
NAME_RE = re.compile(r"[a-z0-9-]{1,32}")
_URL_RE = re.compile(r"http://(\[[0-9a-fA-F:]{2,39}\]|[0-9]{1,3}(?:\.[0-9]{1,3}){3}):([1-9][0-9]{3,4})")
_KEY_RE = re.compile(rb"[A-Za-z0-9_-]{43,1024}")      # hex >= 64 và base64url >= 43 đều nằm trong khuôn này
_APPR_RE = re.compile(r"/kira/approvals/[0-9a-f]{32}/(?:reject|defer)")
_GET_ROUTES = frozenset({"/kira/status", "/kira/info", "/kira/ledger", "/kira/approvals"})
_ALLOWED_V4 = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10")]
_ALLOWED_V6 = [ipaddress.ip_network("fd00::/8")]
_STATUS_CODES = {401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "not_pending", 422: "invalid",
                 429: "rate_limited", 502: "upstream_unavailable"}
_REPARSE_POINT = 0x400


class PeerError(Exception):
    """Chỉ mang MÃ NGẮN (bad_url, bad_name, no_key, no_pin, pin_mismatch, bad_request, unreachable, timeout,
    unauthorized, forbidden, not_found, not_pending, invalid, rate_limited, upstream_unavailable, bad_response)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"PeerError({self.code!r})"


# Mọi `raise PeerError` nằm NGOÀI khối except (đặt cờ rồi ném sau) để `__context__` luôn rỗng.

# ------------------------------------------------------------------ đích -------------------------
def parse_peer_url(url, *, allow_loopback: bool = False, own_ports=(7788,)):
    """-> (ipaddress object, cổng). Mọi sai sót đều là PeerError('bad_url')."""
    m = _URL_RE.fullmatch(url) if isinstance(url, str) else None
    if not m:
        raise PeerError("bad_url")
    host, port = m.group(1), int(m.group(2))
    try:
        ip = ipaddress.ip_address(host[1:-1] if host.startswith("[") else host)
    except ValueError:
        ip = None
    if ip is None or port < 1024 or port > 65535 or port in tuple(own_ports):
        raise PeerError("bad_url")
    if isinstance(ip, ipaddress.IPv6Address):
        nets = _ALLOWED_V6
        mapped = ip.ipv4_mapped is not None
    else:
        nets, mapped = _ALLOWED_V4, False
    ok = any(ip in n for n in nets) or (allow_loopback and ip.is_loopback)
    if mapped or not ok or ip.is_unspecified or ip.is_multicast or ip.is_link_local:
        raise PeerError("bad_url")
    return ip, port


# ------------------------------------------------------------------ khoá / ghim -------------------
def default_key_dir() -> str:
    """Chỉ lấy từ biến môi trường của tiến trình (KHÔNG từ config.json)."""
    return os.environ.get("ORBIT_PEER_KEY_DIR") or os.path.join(os.path.expanduser("~"), ".secret", "orbit", "peers")


def _sig(st) -> tuple:
    return (st.st_ino, st.st_size, st.st_mtime_ns, getattr(st, "st_file_attributes", 0))


def _safe_file(name, suffix: str, key_dir, max_size: int, missing: str):
    """-> (đường thật, chữ ký lstat). Không theo liên kết/junction; đường thật phải là con trực tiếp của thư mục khoá."""
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise PeerError("bad_name")
    key_dir = key_dir or default_key_dir()
    path = os.path.join(key_dir, name + suffix)
    bad = True
    real = sig = None
    try:
        root = os.path.realpath(key_dir)
        real = os.path.realpath(path)
        st = os.lstat(path)
        bad = (os.path.dirname(real) != root or os.path.islink(path)
               or bool(getattr(st, "st_file_attributes", 0) & _REPARSE_POINT)
               or st.st_size > max_size or not os.path.isfile(real))
        sig = _sig(st)
    except (OSError, ValueError):
        bad = True
    if bad:
        raise PeerError(missing)
    return real, sig


def load_peer_key(name, key_dir=None) -> bytes:
    real, before = _safe_file(name, ".key", key_dir, MAX_KEY_FILE, "no_key")
    key = None
    try:
        key = kira_gateway.load_secret(real)               # cùng hàm với cổng ⇒ cùng chuỗi byte ở hai đầu
        changed = _sig(os.lstat(real)) != before           # tệp bị đổi giữa lúc kiểm và lúc đọc ⇒ bỏ
    except (OSError, ValueError):
        changed = True
    if changed or key is None or not _KEY_RE.fullmatch(key):
        raise PeerError("no_key")
    return key


def load_peer_pin(name, key_dir=None) -> str:
    real, _ = _safe_file(name, ".url", key_dir, MAX_PIN_FILE, "no_pin")
    text = ""
    try:
        with open(real, "rb") as f:
            text = f.read(MAX_PIN_FILE + 1).decode("ascii").strip()
    except (OSError, UnicodeDecodeError):
        text = ""
    if not text:
        raise PeerError("no_pin")
    return text


def key_fingerprint(key: bytes) -> str:
    """Băm để so trùng khoá giữa các peer trong RAM (TK3); không bao giờ ghi ra."""
    return hashlib.sha256(bytes(key)).hexdigest()


def make_client(name, url, *, key_dir=None, allow_loopback: bool = False, own_ports=(7788,), **kw) -> "PeerClient":
    key = load_peer_key(name, key_dir)
    pin = load_peer_pin(name, key_dir)
    if pin != url:
        raise PeerError("pin_mismatch")
    return PeerClient(name, url, key, allow_loopback=allow_loopback, own_ports=own_ports, **kw)


# ------------------------------------------------------------------ bảng trắng -------------------
def _check_route(method, path, body) -> bytes:
    if not isinstance(method, str) or not isinstance(path, str):
        raise PeerError("bad_request")
    if method == "GET" and path in _GET_ROUTES and body is None:
        return b""
    if method == "POST" and path == "/kira/stop":
        jid = body.get("job_id") if isinstance(body, dict) else None
        if (not isinstance(body, dict) or set(body) != {"job_id"} or not isinstance(jid, int)
                or isinstance(jid, bool) or not (1 <= jid <= 2 ** 31 - 1)):
            raise PeerError("bad_request")
        return json.dumps({"job_id": jid}, separators=(",", ":")).encode()
    if method == "POST" and _APPR_RE.fullmatch(path) and body is None:
        return b""
    raise PeerError("bad_request")


def _finite(v):
    raise ValueError("non-finite")


def _parse_float(s):
    v = float(s)
    if not math.isfinite(v):
        raise ValueError("non-finite")                     # 1e400 -> inf
    return v


def _no_dup_pairs(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError("duplicate key")
        d[k] = v
    return d


def _parse_json(raw: bytes) -> dict:
    obj = None
    ok = False
    try:
        obj = json.loads(raw.decode("utf-8"), parse_constant=_finite, parse_float=_parse_float,
                         object_pairs_hook=_no_dup_pairs)
        ok = True
    except (UnicodeDecodeError, ValueError, RecursionError):
        ok = False
    if not ok or not isinstance(obj, dict):
        raise PeerError("bad_response")
    return obj


def _default_connect(ip, port, timeout):
    return http.client.HTTPConnection(str(ip), port, timeout=timeout)


# ------------------------------------------------------------------ client ------------------------
class PeerClient:
    def __init__(self, name, url, key, *, allow_loopback: bool = False, own_ports=(7788,), timeout: float = DEFAULT_TIMEOUT,
                 deadline: float = DEFAULT_DEADLINE, now: Callable[[], float] = time.time,
                 mono: Callable[[], float] = time.monotonic, connect=None):
        if not isinstance(key, (bytes, bytearray)) or len(key) < kira_gateway.MIN_SECRET_LEN:
            raise PeerError("no_key")
        self.name, self._url, self._key = name, url, bytes(key)
        self._allow_loopback, self._own_ports = allow_loopback, tuple(own_ports)
        self._timeout, self._deadline, self._now, self._mono = timeout, deadline, now, mono
        self._connect = connect or _default_connect
        parse_peer_url(url, allow_loopback=allow_loopback, own_ports=self._own_ports)      # sai thì dừng ngay

    def __repr__(self) -> str:
        return f"PeerClient({self.name!r})"

    def fingerprint(self) -> str:
        """Băm của khoá (để hub phát hiện hai peer dùng chung khoá); không lộ khoá."""
        return key_fingerprint(self._key)

    @staticmethod
    def _abort(conn, expired: threading.Event) -> None:
        """Đồng hồ canh: hết hạn chót thì đóng socket để mọi recv đang chặn bung ra ngay."""
        expired.set()
        sock = getattr(conn, "sock", None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def request(self, method, path, body=None):
        raw = _check_route(method, path, body)
        ip, port = parse_peer_url(self._url, allow_loopback=self._allow_loopback, own_ports=self._own_ports)  # mỗi lần gọi
        ts = str(int(self._now()))
        nonce = secrets.token_urlsafe(16)
        sig = hmac.new(self._key, f"{method}\n{path}\n{ts}\n{nonce}\n".encode() + raw, hashlib.sha256).hexdigest()
        headers = {"X-Kira-Ts": ts, "X-Kira-Nonce": nonce, "X-Kira-Sig": sig, "Accept": "application/json",
                   "Connection": "close"}
        if method == "POST":
            headers["Content-Type"] = "application/json"
        end = self._mono() + self._deadline
        expired = threading.Event()
        timer = None
        conn = None
        code = None
        data = b""
        try:
            conn = self._connect(ip, port, min(self._timeout, self._deadline))
            if hasattr(conn, "connect"):
                conn.connect()                                  # kết nối bị chặn bởi timeout socket (<= 4 s)
            timer = threading.Timer(max(0.05, end - self._mono()), self._abort, args=(conn, expired))
            timer.daemon = True
            timer.start()
            sock = getattr(conn, "sock", None)
            if sock is not None:
                sock.settimeout(max(0.05, end - self._mono()))  # mỗi recv không vượt thời gian còn lại
            conn.request(method, path, body=raw or None, headers=headers)      # ký đúng chuỗi byte đã gửi
            resp = conn.getresponse()
            status = resp.status
            if status != 200:
                code = _STATUS_CODES.get(status, "bad_response")
            else:
                data = self._read(resp, end)
        except PeerError as e:
            code = e.code
        except TimeoutError:
            code = "timeout"
        except (OSError, http.client.HTTPException, ValueError):
            code = "timeout" if expired.is_set() else "unreachable"
        finally:
            if timer is not None:
                timer.cancel()
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
        if code is None and expired.is_set():
            code = "timeout"
        if code is not None:
            raise PeerError(code)                               # ném NGOÀI except: __context__ rỗng
        return 200, _parse_json(data)

    def _read(self, resp, end: float) -> bytes:
        chunks, total = [], 0
        while True:
            if self._mono() > end:
                raise PeerError("timeout")
            chunk = resp.read1(4096) if hasattr(resp, "read1") else resp.read(4096)
            if not chunk:
                return b"".join(chunks)
            total += len(chunk)
            if total > MAX_BYTES:
                raise PeerError("bad_response")
            chunks.append(chunk)
