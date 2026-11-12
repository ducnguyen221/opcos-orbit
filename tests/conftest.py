import pytest

from server import approvals, security

# TestClient của Starlette dùng Host "testserver" — chỉ cho phép trong môi trường test.
security.EXTRA_HOSTS.add("testserver")


@pytest.fixture(autouse=True)
def _isolated_approvals(tmp_path, monkeypatch):
    """Mọi test dùng kho duyệt riêng (nhật ký + PIN trong tmp): không ghi sessions/approvals.jsonl thật,
    không đọc ~/.secret thật."""
    store = approvals.ApprovalStore(log_path=str(tmp_path / "approvals.jsonl"),
                                    pin=approvals.PinStore(str(tmp_path / "approval-pin.json")))
    monkeypatch.setattr(approvals, "_STORE", store)
    return store
