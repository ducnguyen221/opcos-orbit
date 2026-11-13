"""CLI quản lý khoá của máy phụ (Giai đoạn 2, TK6) — DO ĐỨC CHẠY TAY; agent không chạy, không đọc kết quả khoá.

  python -m server.peer_keys gen <tên> --url http://<IP>:<cổng> [--key-dir DIR]
  python -m server.peer_keys show <tên>      # dấu vân tay + URL ghim (KHÔNG in khoá)
  python -m server.peer_keys list
  python -m server.peer_keys fingerprint <đường-dẫn-tệp-khoá>   # trên máy phụ: so vân tay với hub (chỉ in vân tay)

`gen` tạo CẶP tệp trong thư mục khoá của hub (mặc định ~/.secret/orbit/peers, đổi bằng ORBIT_PEER_KEY_DIR hoặc --key-dir):
  <tên>.key  khoá HMAC 64 ký tự hex (ngẫu nhiên, 256 bit) — KHÔNG BAO GIỜ được in ra
  <tên>.url  URL ghim của máy phụ (config.json phải ghi đúng URL này, nếu không hub từ chối: pin_mismatch)
KHÔNG ghi đè (O_EXCL); thiếu một trong hai tệp vẫn từ chối để không để lại trạng thái nửa chừng; không ghi qua liên kết.
Khoá phải được chép sang máy phụ (đặt làm KIRA_SECRET_FILE của cổng Kira trên máy đó) qua kênh an toàn — KHÔNG qua chat/email;
hai đầu so dấu vân tay (hub: `show`; máy phụ: `fingerprint <tệp>`). Mỗi cổng Kira chỉ có MỘT khoá (dùng chung với Kira/phone của máy đó); KHÔNG dùng một khoá
cho hai máy. Thu hồi = đổi khoá trên máy phụ + bỏ IP hub khỏi allowlist của máy đó.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import subprocess
import sys

from server import peer_client as pc


def _restrict_acl(path: str) -> bool:
    """Windows: bỏ quyền kế thừa, chỉ chủ tài khoản hiện tại. Best-effort (POSIX dùng 0o600/0o700 khi tạo)."""
    if sys.platform != "win32":
        return True
    try:
        root = os.environ.get("SystemRoot", r"C:\Windows")
        sysdir = os.path.join(root, "System32")
        who = subprocess.run([os.path.join(sysdir, "whoami.exe"), "/user", "/fo", "csv", "/nh"],
                             capture_output=True, timeout=15, text=True)
        sid = who.stdout.strip().split(",")[-1].strip().strip('"') if who.returncode == 0 else ""
        if not sid.startswith("S-1-"):
            return False
        r = subprocess.run([os.path.join(sysdir, "icacls.exe"), path, "/inheritance:r", "/grant:r", f"*{sid}:F"],
                           capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def _is_link(path: str) -> bool:
    """Symlink, junction hoặc reparse point (Windows) — không tin os.path.islink một mình."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if os.path.islink(path) or getattr(os.path, "isjunction", lambda p: False)(path):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & 0x400)


def _dir_chain_has_link(kd: str) -> bool:
    p = os.path.abspath(kd)
    for _ in range(3):                                  # thư mục khoá + hai cấp cha (vd ~/.secret/orbit/peers)
        if _is_link(p):
            return True
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return False


def _key_dir(arg) -> str:
    return arg or pc.default_key_dir()


def _fingerprint12(key_path: str) -> str:
    with open(key_path, "rb") as f:
        return hashlib.sha256(f.read(pc.MAX_KEY_FILE + 1).strip()).hexdigest()[:12]


def _write_new(path: str, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)      # O_EXCL: không bao giờ ghi đè
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    except OSError:
        try:
            os.remove(path)                              # tệp này do CHÍNH ta vừa tạo (O_EXCL thành công)
        except OSError:
            pass
        raise
    if not _restrict_acl(path):
        print(f"CẢNH BÁO: không đặt được quyền chỉ-chủ-sở-hữu cho {os.path.basename(path)}.", file=sys.stderr)


def _cmd_gen(args) -> int:
    name, url = args.name, args.url
    if not (isinstance(name, str) and pc.NAME_RE.fullmatch(name)):
        print("Tên không hợp lệ: chỉ [a-z0-9-], 1–32 ký tự.", file=sys.stderr)
        return 1
    try:
        pc.parse_peer_url(url)                         # loopback KHÔNG được phép khi tạo khoá thật
    except pc.PeerError:
        print("URL không hợp lệ: cần http://<IP riêng/Tailscale>:<cổng 1024–65535>, không phải cổng 7788.", file=sys.stderr)
        return 1
    kd = _key_dir(args.key_dir)
    if _dir_chain_has_link(kd):
        print("Thư mục khoá (hoặc thư mục cha) là liên kết/junction — từ chối.", file=sys.stderr)
        return 1
    key_path, url_path = os.path.join(kd, name + ".key"), os.path.join(kd, name + ".url")
    if os.path.lexists(key_path) or os.path.lexists(url_path):
        print(f"Đã tồn tại khoá/ghim cho '{name}' — không ghi đè. Muốn đổi khoá: xoá tay hai tệp rồi chạy lại "
              f"(và đổi khoá ở máy phụ).", file=sys.stderr)
        return 1
    os.makedirs(kd, mode=0o700, exist_ok=True)
    if _dir_chain_has_link(kd):                         # kiểm lại sau makedirs
        print("Thư mục khoá (hoặc thư mục cha) là liên kết/junction — từ chối.", file=sys.stderr)
        return 1
    if not _restrict_acl(kd):
        print("CẢNH BÁO: không đặt được quyền chỉ-chủ-sở-hữu cho thư mục khoá — tự kiểm tra quyền thư mục này.", file=sys.stderr)
    key = secrets.token_hex(32).encode("ascii") + b"\n"
    created = []
    try:
        for p, data in ((key_path, key), (url_path, (url + "\n").encode("ascii"))):
            _write_new(p, data)
            created.append(p)                           # chỉ xoá tệp do CHÍNH lần chạy này tạo
    except OSError:
        print("Không ghi được tệp khoá.", file=sys.stderr)
        for p in created:
            try:
                os.remove(p)
            except OSError:
                pass
        return 1
    print(f"Đã tạo: {key_path}\n        {url_path}")
    print(f"Dấu vân tay khoá (12 ký tự đầu của SHA-256): {_fingerprint12(key_path)}")
    print("Bước tiếp: chép KHOÁ sang máy phụ qua kênh an toàn (đặt làm KIRA_SECRET_FILE của cổng Kira ở đó), chạy "
          "`show` ở hai đầu để so dấu vân tay, rồi thêm {\"name\": \"%s\", \"url\": \"%s\"} vào settings.peers." % (name, url))
    return 0


def _cmd_show(args) -> int:
    if not pc.NAME_RE.fullmatch(args.name or ""):
        print("Tên không hợp lệ.", file=sys.stderr)
        return 1
    kd = _key_dir(args.key_dir)
    try:
        pin = pc.load_peer_pin(args.name, key_dir=kd)
        pc.load_peer_key(args.name, key_dir=kd)         # kiểm hợp lệ, không in
        fp = _fingerprint12(os.path.join(kd, args.name + ".key"))
    except pc.PeerError as e:
        print(f"Không đọc được '{args.name}': {e.code}", file=sys.stderr)
        return 1
    print(f"{args.name}  vân tay {fp}  url {pin}")
    return 0


def _cmd_fingerprint(args) -> int:
    """Chỉ in vân tay của MỘT tệp khoá bất kỳ (vd KIRA_SECRET_FILE trên máy phụ) — không in khoá."""
    path = args.path
    if not isinstance(path, str) or not os.path.isfile(path) or _is_link(path):
        print("Không đọc được tệp (không tồn tại, không phải tệp thường, hoặc là liên kết).", file=sys.stderr)
        return 1
    try:
        if os.path.getsize(path) > pc.MAX_KEY_FILE:
            print("Tệp quá lớn để là khoá.", file=sys.stderr)
            return 1
        print(f"vân tay {_fingerprint12(path)}")
    except OSError:
        print("Không đọc được tệp.", file=sys.stderr)
        return 1
    return 0


def _cmd_list(args) -> int:
    kd = _key_dir(args.key_dir)
    try:
        names = sorted(f[:-4] for f in os.listdir(kd) if f.endswith(".key") and pc.NAME_RE.fullmatch(f[:-4]))
    except OSError:
        names = []
    for n in names:
        try:
            print(f"{n}  vân tay {_fingerprint12(os.path.join(kd, n + '.key'))}  url {pc.load_peer_pin(n, key_dir=kd)}")
        except (pc.PeerError, OSError):
            print(f"{n}  (khoá hoặc ghim lỗi)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m server.peer_keys", description=__doc__.split("\n")[0])
    ap.add_argument("--key-dir", default=None, help="thư mục khoá (mặc định: ORBIT_PEER_KEY_DIR hoặc ~/.secret/orbit/peers)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen")
    g.add_argument("name")
    g.add_argument("--url", required=True)
    s = sub.add_parser("show")
    s.add_argument("name")
    sub.add_parser("list")
    f = sub.add_parser("fingerprint")
    f.add_argument("path")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    return {"gen": _cmd_gen, "show": _cmd_show, "list": _cmd_list, "fingerprint": _cmd_fingerprint}[args.cmd](args)


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
