# -*- coding: utf-8 -*-
"""Unit test máy trạng thái jobs.py (Console v2) — luật distill từ herdr."""
import time

from server import jobs


def _fresh(engine="claude"):
    return jobs.create("t-1", engine, "làm việc gì đó dài dòng " * 10)


def test_prompt_preview_capped():
    j = _fresh()
    assert len(j.prompt_preview) <= 120


def test_working_khi_moi_chay():
    j = _fresh()
    j.feed_line("dang lam viec...")
    assert j.state() == "working"


def test_blocked_can_ca_im_lang_va_pattern():
    j = _fresh()
    j.feed_line("Do you want to proceed? (y/N)")
    # vừa có output → CHƯA blocked (chưa đủ im lặng)
    assert j.state() == "working"
    j._last_output_at = time.time() - 30
    assert j.state() == "blocked"


def test_im_lang_khong_pattern_van_working():
    j = _fresh()
    j.feed_line("dang suy nghi rat lau...")
    j._last_output_at = time.time() - 60
    assert j.state() == "working"   # im lặng dài KHÔNG pattern = vẫn working (đúng herdr)


def test_pattern_theo_engine_gemini():
    j = _fresh("gemini")
    j.feed_line("│ Apply this change")
    j._last_output_at = time.time() - 30
    assert j.state() == "blocked"


def test_done_va_error():
    j = _fresh()
    j.feed_line("xong viec")
    j.finish(0)
    assert j.state() == "done"
    j2 = _fresh()
    j2.finish(1, "boom")
    assert j2.state() == "error"


def test_seen_flow_kieu_herdr_done():
    j = _fresh()
    j.finish(0)
    assert j.seen is False          # done CHƯA XEM = nổi bật
    assert jobs.mark_seen(j.id)
    assert j.seen is True


def test_summary_attention_gom_blocked_va_error_unseen():
    before = jobs.summary()["attention"]
    jb = _fresh()
    jb.feed_line("waiting for permission")
    jb._last_output_at = time.time() - 30
    je = _fresh()
    je.finish(1, "x")
    s = jobs.summary()
    assert s["attention"] >= before + 2


def test_full_output_giu_tron_ket_qua():
    j = _fresh()
    for i in range(20):
        j.feed_line(f"dong {i}")
    assert "dong 0" in j.full_output() and "dong 19" in j.full_output()
    assert len(j._tail) == 8        # tail chỉ giữ 8 dòng đuôi cho dashboard


def test_list_jobs_sap_xep_blocked_truoc():
    jw = _fresh(); jw.feed_line("busy")
    jb = _fresh(); jb.feed_line("[y/n]"); jb._last_output_at = time.time() - 30
    items = jobs.list_jobs()
    states = [it["state"] for it in items]
    assert states.index("blocked") < states.index("working")
