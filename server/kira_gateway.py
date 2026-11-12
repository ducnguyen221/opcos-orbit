"""Cổng Kira — bước 1 (mức XEM + DỪNG). Tiến trình RIÊNG, không nằm trong app 7788.

Kira (ESP32-S3) và phone chỉ nói chuyện với cổng này; cổng chuyển đúng hai việc sang Orbit
qua loopback: xem trạng thái việc (GET /kira/status) và dừng một việc (POST /kira/stop).
Không có Approve/ra lệnh mới (đó là bước 5, cần giao thức duyệt riêng).

Lớp bảo vệ (fail-closed):
  - tầng ASGI, áp cho MỌI đường dẫn: allowlist IP nguồn (rỗng = từ chối hết) rồi giới hạn tần suất
    theo IP (tính cả tin xác thực hỏng và đường dẫn lạ);
  - trong route: đọc body có trần + timeout, HMAC-SHA256 từng tin ràng buộc
    method + path + ts + nonce + body, cửa sổ ±30 s, nonce dùng một lần, và từ chối tin có ts
    trước lúc tiến trình khởi động (chống phát lại sau restart).
Khóa HMAC do CHÍNH tiến trình này đọc từ file (mặc định ~/.secret/kira/hmac.key); agent không đọc.
KHÔNG bind 0.0.0.0: validate_bind() từ chối địa chỉ đại diện và tên máy. HTTP không mã hóa và
phản hồi không được ký — nên bind vào IP của mạng riêng mã hóa (Tailscale/WireGuard).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

WINDOW_S = 30                    # lệch đồng hồ tối đa giữa Kira và cổng
NONCE_TTL_S = 2 * WINDOW_S + 5   # > cửa sổ x2 để tin ở ranh giới cũng không phát lại được
MAX_NONCES = 10_000
MAX_BODY = 4096
BODY_TIMEOUT_S = 5.0
MIN_SECRET_LEN = 32
DEFAULT_RATE = (30, 60)          # (số tin, giây) mỗi IP
_NONCE_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_TS_RE = re.compile(r"[0-9]{1,12}")
_JOB_FIELDS = ("id", "instance", "engine", "state", "elapsed")
_SUMMARY_FIELDS = ("blocked", "working", "done_unseen", "error_unseen", "attention", "approvals")
_APPR_FIELDS = ("id", "n", "instance", "engine", "level", "expires_in", "fp16", "state")
_APPR_ID_RE = re.compile(r"[0-9a-f]{32}")
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}

Fetch = Callable[..., "tuple[int, dict]"]


# ------------------------------------------------------------------ cấu hình --
def _norm_ip(value: str) -> str:
    try:
        return ipaddress.ip_address(value).compressed
    except ValueError:
        return value


def validate_bind(host) -> str:
    """Chỉ nhận một IP cụ thể. Từ chối rỗng, 0.0.0.0, ::, tên máy. Bỏ dấu [] của IPv6."""
    if not isinstance(host, str):
        raise ValueError("KIRA_BIND phải là một địa chỉ IP cụ thể")
    h = host.strip()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        raise ValueError("KIRA_BIND phải là địa chỉ IP, không phải tên máy hay chuỗi rỗng") from None
    if ip.is_unspecified:
        raise ValueError("KIRA_BIND không được là địa chỉ đại diện (0.0.0.0 / ::)")
    return h


def load_secret(path: str) -> bytes:
    try:
        with open(path, "rb") as f:
            key = f.read().strip()
    except OSError:
        raise ValueError("không đọc được file khóa HMAC của Kira") from None
    if len(key) < MIN_SECRET_LEN:
        raise ValueError(f"khóa HMAC quá ngắn (cần >= {MIN_SECRET_LEN} byte)")
    return key


def parse_allowed_ips(value) -> set:
    """Chuẩn hóa từng IP; mục không phải IP => ValueError (sai thì dừng, không bỏ qua im lặng)."""
    if not value:
        return set()
    out = set()
    for part in str(value).split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.add(ipaddress.ip_address(p).compressed)
        except ValueError:
            raise ValueError(f"KIRA_ALLOWED_IPS có mục không phải IP: {p!r}") from None
    return out


# ------------------------------------------------------------------ upstream --
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None                          # không theo redirect: lỗi 3xx trả nguyên cho caller


def _make_fetch(upstream: str, timeout: float = 5.0) -> Fetch:
    parts = urllib.parse.urlsplit(upstream)
    if parts.scheme != "http" or (parts.hostname or "").lower() not in _LOOPBACK:
        raise ValueError("upstream của cổng Kira chỉ được là http://<loopback>")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def fetch(method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(upstream.rstrip("/") + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
        try:
            with opener.open(req, timeout=timeout) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except ValueError:
                return e.code, {}
    return fetch


# ------------------------------------------------------------------ guard -----
class _Guard:
    """ASGI thuần, chạy TRƯỚC routing: allowlist IP rồi rate limit cho mọi đường dẫn."""

    def __init__(self, app, *, allowed, rate_ok, now):
        self.app, self.allowed, self.rate_ok, self.now = app, allowed, rate_ok, now

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        ip = _norm_ip(client[0]) if client else ""
        status = None
        if not self.allowed or ip not in self.allowed:
            status, detail = 403, "forbidden"
        elif not self.rate_ok(ip, self.now()):
            status, detail = 429, "too many requests"
        if status is None:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await receive()
            await send({"type": "websocket.close", "code": 1008})
            return
        body = json.dumps({"detail": detail}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


# ------------------------------------------------------------------ app -------
def create_app(*, secret: bytes, allowed_ips, upstream: str = "http://127.0.0.1:7788",
               fetch: Fetch | None = None, now: Callable[[], float] = time.time,
               rate_limit: tuple = DEFAULT_RATE) -> FastAPI:
    if not isinstance(secret, (bytes, bytearray)) or len(secret) < MIN_SECRET_LEN:
        raise ValueError("khóa HMAC thiếu hoặc quá ngắn")
    allowed = frozenset(_norm_ip(i) for i in (allowed_ips or ()))
    call = fetch or _make_fetch(upstream)
    max_hits, per_s = rate_limit
    started = int(now())
    hits: dict[str, deque] = {}
    nonces: dict[str, float] = {}

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def _deny(status: int, detail: str):
        raise HTTPException(status_code=status, detail=detail)

    def _rate_ok(ip: str, t: float) -> bool:
        q = hits.setdefault(ip, deque())
        while q and q[0] <= t - per_s:
            q.popleft()
        if len(q) >= max_hits:
            return False
        q.append(t)
        return True

    def _prune(t: float) -> None:
        for n in [n for n, exp in nonces.items() if exp <= t]:
            del nonces[n]

    async def _read_body(request: Request) -> bytes:
        clen = request.headers.get("content-length")
        if clen and clen.isascii() and clen.isdecimal() and int(clen) > MAX_BODY:
            _deny(413, "body too large")

        async def collect() -> bytes:
            buf = bytearray()
            async for chunk in request.stream():
                buf += chunk
                if len(buf) > MAX_BODY:
                    _deny(413, "body too large")
            return bytes(buf)
        try:
            return await asyncio.wait_for(collect(), BODY_TIMEOUT_S)
        except asyncio.TimeoutError:
            _deny(408, "request timeout")

    async def _authenticate(request: Request) -> bytes:
        t = now()
        body = await _read_body(request)
        ts_h = request.headers.get("x-kira-ts", "")
        nonce = request.headers.get("x-kira-nonce", "")
        sig = request.headers.get("x-kira-sig", "")
        if not (_TS_RE.fullmatch(ts_h) and _NONCE_RE.fullmatch(nonce) and sig):
            _deny(401, "unauthorized")
        ts = int(ts_h)
        if abs(t - ts) > WINDOW_S or ts < started:
            _deny(401, "unauthorized")
        msg = f"{request.method}\n{request.url.path}\n{ts_h}\n{nonce}\n".encode() + body
        expected = hmac.new(bytes(secret), msg, hashlib.sha256).hexdigest().encode()
        if not hmac.compare_digest(expected, sig.lower().encode("ascii", "ignore")):
            _deny(401, "unauthorized")
        _prune(t)
        if nonce in nonces:
            _deny(401, "unauthorized")
        if len(nonces) >= MAX_NONCES:
            _deny(429, "too many requests")
        nonces[nonce] = t + NONCE_TTL_S
        return body

    async def _upstream(method: str, path: str, body=None):
        try:
            return await run_in_threadpool(call, method, path, body)
        except Exception:                      # không lộ chi tiết kết nối ra ngoài
            _deny(502, "upstream unavailable")

    @app.get("/kira/status")
    async def kira_status(request: Request):
        await _authenticate(request)
        code, data = await _upstream("GET", "/api/jobs")
        if code != 200 or not isinstance(data, dict):
            _deny(502, "upstream unavailable")
        jobs = [{k: j[k] for k in _JOB_FIELDS if k in j}
                for j in data.get("jobs", []) if isinstance(j, dict)]
        raw = data.get("summary") or {}
        summary = {k: raw[k] for k in _SUMMARY_FIELDS
                   if isinstance(raw.get(k), int) and not isinstance(raw.get(k), bool)}
        return {"jobs": jobs, "summary": summary}

    @app.post("/kira/stop")
    async def kira_stop(request: Request):
        raw = await _authenticate(request)
        try:
            payload = json.loads(raw or b"{}")
        except (ValueError, RecursionError):
            _deny(422, "invalid body")
        jid = payload.get("job_id") if isinstance(payload, dict) else None
        if (not isinstance(payload, dict) or set(payload) != {"job_id"}
                or not isinstance(jid, int) or isinstance(jid, bool) or not (1 <= jid <= 2**31 - 1)):
            _deny(422, "job_id must be a positive integer, nothing else")
        code, data = await _upstream("POST", f"/api/jobs/{jid}/kill", None)
        if code == 404:
            _deny(404, "job not found")
        if code != 200 or not isinstance(data, dict):
            _deny(502, "upstream unavailable")
        return {"ok": True, "id": jid}

    @app.get("/kira/approvals")
    async def kira_approvals(request: Request):
        await _authenticate(request)
        code, data = await _upstream("GET", "/api/approvals/kira")
        if code != 200 or not isinstance(data, dict):
            _deny(502, "upstream unavailable")
        items = [{k: a[k] for k in _APPR_FIELDS if k in a}
                 for a in data.get("approvals", []) if isinstance(a, dict)]
        return {"approvals": items}

    async def _kira_decide(request: Request, rid: str, action: str):
        await _authenticate(request)
        if not _APPR_ID_RE.fullmatch(rid):
            _deny(422, "invalid id")
        code, data = await _upstream("POST", f"/api/approvals/{rid}/kira/{action}", None)
        if code in (404, 409):
            _deny(code, "not found" if code == 404 else "not pending")
        if code != 200 or not isinstance(data, dict):
            _deny(502, "upstream unavailable")
        return {"ok": True, "state": data.get("state") if isinstance(data.get("state"), str) else action}

    @app.post("/kira/approvals/{rid}/reject")
    async def kira_reject(request: Request, rid: str):
        return await _kira_decide(request, rid, "reject")

    @app.post("/kira/approvals/{rid}/defer")
    async def kira_defer(request: Request, rid: str):
        return await _kira_decide(request, rid, "defer")

    @app.exception_handler(HTTPException)
    async def _http_exc(_request, exc: HTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    app.add_middleware(_Guard, allowed=allowed, rate_ok=_rate_ok, now=now)
    return app


# ------------------------------------------------------------------ chạy -------
def main() -> None:                            # pragma: no cover (khởi động tiến trình thật)
    import sys
    import uvicorn
    try:
        host = validate_bind(os.environ.get("KIRA_BIND"))
        key_file = os.environ.get("KIRA_SECRET_FILE") or os.path.join(
            os.path.expanduser("~"), ".secret", "kira", "hmac.key")
        secret = load_secret(key_file)
        ips = parse_allowed_ips(os.environ.get("KIRA_ALLOWED_IPS"))
        if not ips:
            raise ValueError("KIRA_ALLOWED_IPS rỗng — cổng sẽ từ chối mọi tin; đặt IP của Kira/phone")
        port = int(os.environ.get("KIRA_PORT", "7790"))
    except ValueError as e:
        print(f"[kira-gateway] KHÔNG khởi động: {e}", file=sys.stderr)
        raise SystemExit(2) from None
    app = create_app(secret=secret, allowed_ips=ips,
                     upstream=os.environ.get("KIRA_UPSTREAM", "http://127.0.0.1:7788"))
    uvicorn.run(app, host=host, port=port, proxy_headers=False, server_header=False)


if __name__ == "__main__":                     # pragma: no cover
    main()
