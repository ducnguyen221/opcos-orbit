import pytest

from server import approvals, security

# TestClient của Starlette dùng Host "testserver" — chỉ cho phép trong môi trường test.
security.EXTRA_HOSTS.add("testserver")


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    """Sổ ghi nhận lượt agent riêng mỗi test: không ghi sessions/agent-ledger.jsonl thật."""
    from server import ledger
    led = ledger.Ledger(str(tmp_path / "agent-ledger.jsonl"))
    monkeypatch.setattr(ledger, "_LEDGER", led)
    return led


@pytest.fixture(autouse=True)
def _isolated_workspace(tmp_path, monkeypatch):
    """cwd riêng của instance (RF8) nằm trong tmp — test không tạo thư mục thật dưới ~/OpcOS/workspaces."""
    monkeypatch.setenv("ORBIT_WORKSPACE_ROOT", str(tmp_path / "ws"))


@pytest.fixture(autouse=True)
def _isolated_approvals(tmp_path, monkeypatch):
    """Mọi test dùng kho duyệt riêng (nhật ký + PIN trong tmp): không ghi sessions/approvals.jsonl thật,
    không đọc ~/.secret thật."""
    store = approvals.ApprovalStore(log_path=str(tmp_path / "approvals.jsonl"),
                                    pin=approvals.PinStore(str(tmp_path / "approval-pin.json")))
    monkeypatch.setattr(approvals, "_STORE", store)
    return store
