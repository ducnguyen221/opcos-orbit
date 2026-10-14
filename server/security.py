"""Lớp bảo mật API cục bộ: allowlist đường dẫn, chống nâng quyền, Host/Origin chỉ localhost.
Fail-closed: thiếu/lỗi => từ chối."""
import os
import tempfile
from urllib.parse import urlsplit

AUTONOMY_RANK = {"suggest": 0, "auto-safe": 1, "full": 2}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}
EXTRA_HOSTS: set = set()      # test/triển khai đặc biệt thêm tại đây (tường minh)


def autonomy_change_allowed(current, requested) -> bool | None:
    """True = hạ/giữ; False = nâng quyền (cấm qua API); None = giá trị không hợp lệ."""
    if requested not in AUTONOMY_RANK:
        return None
    cur = AUTONOMY_RANK.get(current, 0)      # thiếu/lạ => suggest
    return AUTONOMY_RANK[requested] <= cur


def _norm(p: str) -> str:
    return os.path.normcase(os.path.realpath(p))


def allowed_roots(upload_dir: str) -> list:
    roots = [upload_dir]
    for r in os.environ.get("AGENT_CONSOLE_ALLOWED_ROOTS", "").split(os.pathsep):
        if r.strip():
            roots.append(r.strip())
    return [_norm(r) for r in roots]


def path_allowed(path, roots) -> bool:
    """resolve (xử lý .. và symlink) rồi chỉ chấp nhận nếu nằm DƯỚI một gốc cho phép."""
    if not isinstance(path, str) or not path or "\x00" in path:
        return False
    try:
        real = _norm(path)
        for root in roots:
            if os.path.commonpath([real, root]) == root:
                return True
    except (ValueError, OSError):
        return False
    return False


def tts_audio_allowed(path) -> bool:
    """/audio chỉ phục vụ file do tts.synthesize tạo: <tmp>/ac_*.wav."""
    if not isinstance(path, str) or "\x00" in path:
        return False
    try:
        real = _norm(path)
        tmp = _norm(tempfile.gettempdir())
    except OSError:
        return False
    name = os.path.basename(real)
    return (os.path.dirname(real) == tmp and name.startswith("ac_")
            and name.endswith(".wav") and os.path.isfile(real))


def _host_ok(value) -> bool:
    if not value:
        return False
    host = urlsplit("//" + value).hostname if "//" not in value else urlsplit(value).hostname
    return bool(host) and (host.lower() in LOCAL_HOSTS or host.lower() in EXTRA_HOSTS)


class LocalOnlyMiddleware:
    """ASGI thuần (phủ cả http lẫn websocket): Host phải là localhost; nếu có Origin
    thì cũng phải là localhost. Chặn DNS-rebinding và cross-site/CSWSH."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            h = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            ok = _host_ok(h.get("host")) and (("origin" not in h) or _host_ok(h["origin"]))
            if not ok:
                if scope["type"] == "websocket":
                    await receive()
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    body = b'{"detail":"forbidden host/origin"}'
                    await send({"type": "http.response.start", "status": 403,
                                "headers": [(b"content-type", b"application/json"),
                                            (b"content-length", str(len(body)).encode())]})
                    await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
