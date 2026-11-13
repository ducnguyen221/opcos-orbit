"""TK6 (Giai đoạn 2): CLI `peer_keys` — DO ĐỨC CHẠY TAY. Test chỉ dùng thư mục tmp; không bao giờ chạm kho secret thật."""
import os
import re
import stat
import sys

import pytest

from server import kira_gateway as kg
from server import peer_client as pc
from server import peer_keys as pk

URL = "http://100.64.0.5:7790"


@pytest.fixture(autouse=True)
def _no_real_acl(monkeypatch):
    monkeypatch.setattr(pk, "_restrict_acl", lambda path: True)       # không chạy icacls thật trong test


def run(args, tmp_path, capsys, **env):
    code = pk.main(["--key-dir", str(tmp_path / "keys"), *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_gen_writes_key_and_pin_without_printing_the_key(tmp_path, capsys):
    code, out, err = run(["gen", "may-2", "--url", URL], tmp_path, capsys)
    assert code == 0
    key = (tmp_path / "keys" / "may-2.key").read_text(encoding="ascii").strip()
    assert re.fullmatch(r"[0-9a-f]{64}", key)
    assert (tmp_path / "keys" / "may-2.url").read_text(encoding="ascii").strip() == URL
    assert key not in out and key not in err                          # KHÔNG in khoá
    assert pc.key_fingerprint(key.encode())[:12] in out               # in dấu vân tay để so hai đầu
    assert "may-2.key" in out


def test_generated_files_work_with_the_client_and_the_gateway(tmp_path, capsys):
    run(["gen", "may-2", "--url", URL], tmp_path, capsys)
    kd = str(tmp_path / "keys")
    key = pc.load_peer_key("may-2", key_dir=kd)
    assert key == kg.load_secret(str(tmp_path / "keys" / "may-2.key"))    # hai đầu cùng một chuỗi byte
    assert pc.load_peer_pin("may-2", key_dir=kd) == URL
    pc.make_client("may-2", URL, key_dir=kd)


def test_gen_never_overwrites(tmp_path, capsys):
    run(["gen", "may-2", "--url", URL], tmp_path, capsys)
    before = (tmp_path / "keys" / "may-2.key").read_bytes()
    code, out, err = run(["gen", "may-2", "--url", "http://100.64.0.6:7790"], tmp_path, capsys)
    assert code == 1 and "Đã tồn tại" in err
    assert (tmp_path / "keys" / "may-2.key").read_bytes() == before
    assert (tmp_path / "keys" / "may-2.url").read_text(encoding="ascii").strip() == URL


def test_partial_state_is_not_left_when_pin_exists(tmp_path, capsys):
    (tmp_path / "keys").mkdir()
    (tmp_path / "keys" / "may-2.url").write_text(URL, encoding="ascii")
    code, _, err = run(["gen", "may-2", "--url", URL], tmp_path, capsys)
    assert code == 1
    assert not (tmp_path / "keys" / "may-2.key").exists()             # không tạo nửa chừng


@pytest.mark.parametrize("name", ["", "A", "../x", "a/b", "a b", "x" * 33, "a.b"])
def test_bad_names_refused_and_nothing_written(tmp_path, capsys, name):
    code, _, err = run(["gen", name, "--url", URL], tmp_path, capsys)
    assert code in (1, 2)
    assert not (tmp_path / "keys").exists() or list((tmp_path / "keys").iterdir()) == []


@pytest.mark.parametrize("url", ["http://8.8.8.8:7790", "https://100.64.0.5:7790", "http://localhost:7790",
                                 "http://127.0.0.1:7790", "http://100.64.0.5:7788", "http://100.64.0.5:80", "x", ""])
def test_bad_urls_refused_and_nothing_written(tmp_path, capsys, url):
    code, _, err = run(["gen", "may-2", "--url", url], tmp_path, capsys)
    assert code == 1 and "url" in err.lower()
    assert not (tmp_path / "keys").exists() or list((tmp_path / "keys").iterdir()) == []


def test_url_is_required_for_gen(tmp_path, capsys):
    code, _, _ = run(["gen", "may-2"], tmp_path, capsys)
    assert code == 2


@pytest.mark.skipif(sys.platform == "win32", reason="quyền POSIX")
def test_posix_permissions_are_owner_only(tmp_path, capsys):
    run(["gen", "may-2", "--url", URL], tmp_path, capsys)
    for f in ("may-2.key", "may-2.url"):
        assert stat.S_IMODE(os.stat(tmp_path / "keys" / f).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(tmp_path / "keys").st_mode) == 0o700


def test_show_prints_fingerprint_and_pin_but_never_the_key(tmp_path, capsys):
    run(["gen", "may-2", "--url", URL], tmp_path, capsys)
    capsys.readouterr()
    key = (tmp_path / "keys" / "may-2.key").read_text(encoding="ascii").strip()
    code, out, err = run(["show", "may-2"], tmp_path, capsys)
    assert code == 0 and URL in out and pc.key_fingerprint(key.encode())[:12] in out
    assert key not in out and key not in err
    code, _, err = run(["show", "nope"], tmp_path, capsys)
    assert code == 1


def test_list_shows_names_fingerprints_and_urls_only(tmp_path, capsys):
    run(["gen", "may-2", "--url", URL], tmp_path, capsys)
    run(["gen", "may-3", "--url", "http://100.64.0.6:7790"], tmp_path, capsys)
    capsys.readouterr()
    key = (tmp_path / "keys" / "may-2.key").read_text(encoding="ascii").strip()
    code, out, _ = run(["list"], tmp_path, capsys)
    assert code == 0 and "may-2" in out and "may-3" in out and URL in out and key not in out


def test_default_key_dir_comes_from_env_only(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ORBIT_PEER_KEY_DIR", str(tmp_path / "envkeys"))
    assert pk.main(["gen", "may-2", "--url", URL]) == 0
    assert (tmp_path / "envkeys" / "may-2.key").exists()


def test_fingerprint_command_prints_only_fingerprint(tmp_path, capsys):
    run(["gen", "may-2", "--url", URL], tmp_path, capsys)
    capsys.readouterr()
    keyf = tmp_path / "keys" / "may-2.key"
    key = keyf.read_text(encoding="ascii").strip()
    code, out, err = run(["fingerprint", str(keyf)], tmp_path, capsys)
    assert code == 0 and pc.key_fingerprint(key.encode())[:12] in out and key not in out + err
    assert run(["fingerprint", str(tmp_path / "nope")], tmp_path, capsys)[0] == 1
    big = tmp_path / "big.key"
    big.write_bytes(b"a" * (pc.MAX_KEY_FILE + 5))
    assert run(["fingerprint", str(big)], tmp_path, capsys)[0] == 1


def test_race_does_not_delete_a_preexisting_file(tmp_path, capsys, monkeypatch):
    """Tệp xuất hiện giữa kiểm lexists và os.open (đua): FileExistsError KHÔNG được xoá tệp của lần chạy khác."""
    kd = tmp_path / "keys"
    kd.mkdir()
    real_lexists = os.path.lexists
    monkeypatch.setattr(os.path, "lexists", lambda p: False)           # bỏ qua kiểm trước, mô phỏng đua
    (kd / "may-2.key").write_bytes(b"OTHER-RUN\n")
    code, _, err = run(["gen", "may-2", "--url", URL], tmp_path, capsys)
    monkeypatch.setattr(os.path, "lexists", real_lexists)
    assert code == 1
    assert (kd / "may-2.key").read_bytes() == b"OTHER-RUN\n"
    assert not (kd / "may-2.url").exists()


def test_junction_or_reparse_dir_is_refused(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(pk, "_is_link", lambda p: p.endswith("keys"))
    code, _, err = run(["gen", "may-2", "--url", URL], tmp_path, capsys)
    assert code == 1 and "liên kết" in err
    assert not (tmp_path / "keys" / "may-2.key").exists()


def test_acl_failure_prints_warning_not_silence(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(pk, "_restrict_acl", lambda path: False)
    code, _, err = run(["gen", "may-2", "--url", URL], tmp_path, capsys)
    assert code == 0 and "CẢNH BÁO" in err


def test_key_file_is_not_written_through_a_symlinked_dir(tmp_path, capsys):
    if sys.platform == "win32":
        pytest.skip("symlink cần quyền đặc biệt trên Windows")
    real = tmp_path / "real"
    real.mkdir()
    os.symlink(real, tmp_path / "keys")
    code, _, err = run(["gen", "may-2", "--url", URL], tmp_path, capsys)
    assert code == 1 and not (real / "may-2.key").exists()
