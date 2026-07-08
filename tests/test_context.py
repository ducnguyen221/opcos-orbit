from server.context_manager import is_protected, scan_folder, route_context


def test_protected():
    assert is_protected("C:/x/.env") and is_protected("a/.claude.json")
    assert not is_protected("src/main.py")


def test_scan_folder_filters(tmp_path):
    (tmp_path/"a.py").write_text("x"); (tmp_path/".env").write_text("SECRET")
    (tmp_path/"node_modules").mkdir(); (tmp_path/"node_modules"/"b.js").write_text("y")
    files = scan_folder(str(tmp_path))
    names = [f["path"].split("/")[-1].split("\\")[-1] for f in files]
    assert "a.py" in names and ".env" not in names and "b.js" not in names


def test_route_short_inline(tmp_path):
    p = tmp_path/"n.md"; p.write_text("ngắn", encoding="utf-8")
    r = route_context(str(p)); assert r["mode"]=="inline" and "ngắn" in r["content"]


def test_route_pdf_rag(tmp_path):
    p = tmp_path/"doc.pdf"; p.write_bytes(b"%PDF-1.4 ...")
    assert route_context(str(p))["mode"]=="rag"


def test_route_protected_skip(tmp_path):
    p = tmp_path/".env"; p.write_text("S=1")
    assert route_context(str(p))["mode"]=="skip"
