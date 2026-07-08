from server.session import SessionManager

def test_session_new_rename_load(tmp_path):
    sm = SessionManager(str(tmp_path))
    sid = sm.new("họp sáng")
    bb = sm.load(sid); bb.add("user","User","hi")
    sm.rename(sid, "họp chiều")
    lst = sm.list()
    assert lst[0]["name"]=="họp chiều" and lst[0]["id"]==sid
    bb2 = sm.load(sid); assert len(bb2.turns())==1


def test_archive_unarchive(tmp_path):
    from server.session import SessionManager
    sm = SessionManager(str(tmp_path))
    sid = sm.new("phiên test")
    sm.set_archived(sid, True)
    assert sm.list()[0]["archived"] is True
    sm.set_archived(sid, False)
    assert sm.list()[0].get("archived") is False
