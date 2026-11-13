// approvals.js — thẻ duyệt quyền (bước 5, SPEC FR7). Approve CHỈ ở đây, kèm PIN; Kira chỉ xem/Từ chối/Hoãn.
// Mọi nội dung từ agent đi vào DOM bằng textContent (không innerHTML) — prompt là DỮ LIỆU không tin cậy.
(function () {
  "use strict";
  var box = document.getElementById("approvalList");
  if (!box) return;
  var POLL_MS = 2000;
  var typing = false;          // đang nhập PIN: không vẽ lại để khỏi mất chữ
  var MSG = {
    pin_not_set: "Chưa đặt PIN — chạy `python -m server.approvals set-pin` rồi thử lại.",
    bad_pin: "PIN sai.", pin_locked: "Nhập sai quá nhiều lần — đã khoá tạm, thử lại sau vài phút.",
    not_pending: "Yêu cầu này đã được xử lý hoặc hết hạn.", not_found: "Yêu cầu không còn (hết hạn).",
    channel_cannot_approve: "Kênh này không được duyệt.", invalid: "Yêu cầu không hợp lệ.",
    confirm_untrusted: "Hãy tích ô xác nhận nguồn không tin cậy rồi duyệt lại."
  };

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = String(text);
    return e;
  }

  function decide(id, decision, pin, note, confirm) {
    note.textContent = "";
    fetch("/api/approvals/" + encodeURIComponent(id) + "/decide", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision: decision, pin: pin || null, confirm_untrusted: !!confirm })
    }).then(function (r) {
      return r.json().then(function (d) { return { ok: r.ok, d: d }; });
    }).then(function (x) {
      if (!x.ok) note.textContent = MSG[x.d && x.d.detail] || ("Lỗi: " + (x.d && x.d.detail));
      typing = false; tick();
    }).catch(function () { note.textContent = "Không gọi được máy chủ."; });
  }

  function card(a, pinSet) {
    var open = a.state === "pending" || a.state === "deferred";
    var c = el("div", "appr-card appr-" + a.state);
    var head = el("div", "appr-head");
    head.appendChild(el("b", null, a.requester));
    head.appendChild(el("span", "job-eng", a.engine));
    head.appendChild(el("span", "sum-pill p-blocked", "cần mức " + a.target_level));
    if (open) head.appendChild(el("span", "job-time", "còn " + a.expires_in + "s"));
    c.appendChild(head);
    c.appendChild(el("div", "appr-sum", a.summary + " · #" + a.fp16));
    if (a.runs_with_bypass) c.appendChild(el("div", "appr-warn",
      "⚠ Duyệt = chạy engine agy với cờ BỎ-QUA-QUYỀN của CLI (skip_permissions đang bật)."));
    if (a.limit_untrusted) c.appendChild(el("div", "appr-warn",
      "⚠ Nguồn KHÔNG tin cậy: " + (a.limit_reason || "tin không xác thực đã được nạp vào việc này") +
      ". Đọc kỹ prompt bên dưới — nó có thể chứa chỉ dẫn từ bên ngoài."));
    c.appendChild(el("pre", "appr-prompt", a.prompt));
    if (!open) {
      c.appendChild(el("div", "hint", "Trạng thái: " + a.state + (a.decided_by ? " (bởi " + a.decided_by + ")" : "")));
      if (a.result) c.appendChild(el("pre", "appr-prompt", a.result));
      return c;
    }
    var pin = el("input", "appr-pin"); pin.type = "password"; pin.placeholder = "PIN";
    pin.autocomplete = "off"; pin.maxLength = 64;
    pin.addEventListener("focus", function () { typing = true; });
    pin.addEventListener("blur", function () { typing = false; });
    var note = el("div", "appr-note", pinSet ? "" : MSG.pin_not_set);
    var ok = el("button", "appr-ok", "Duyệt chạy một lần"); ok.disabled = !pinSet;
    var no = el("button", "appr-no", "Từ chối");
    var later = el("button", "appr-later", "Hoãn");
    var conf = null, confRow = null;
    if (a.limit_untrusted) {
      confRow = el("label", "appr-confirm");
      conf = document.createElement("input"); conf.type = "checkbox";
      confRow.appendChild(conf);
      confRow.appendChild(document.createTextNode(" Tôi đã đọc và vẫn muốn chạy việc từ nguồn không tin cậy"));
    }
    ok.addEventListener("click", function () {
      decide(a.id, "approve", pin.value, note, conf && conf.checked); pin.value = "";
    });
    no.addEventListener("click", function () { decide(a.id, "reject", null, note); });
    later.addEventListener("click", function () { decide(a.id, "defer", null, note); });
    var row = el("div", "appr-acts");
    [pin, ok, no, later].forEach(function (n) { row.appendChild(n); });
    if (confRow) c.appendChild(confRow);
    c.appendChild(row); c.appendChild(note);
    return c;
  }

  function render(d) {
    if (typing) return;
    var list = d.approvals || [];
    box.textContent = "";
    if (!list.length) return;                       // không có gì chờ => ẩn hẳn khu này
    box.appendChild(el("h3", null, "🔐 Chờ duyệt (" + list.filter(function (a) {
      return a.state === "pending" || a.state === "deferred"; }).length + ")"));
    list.forEach(function (a) { box.appendChild(card(a, d.pin_set)); });
  }

  function tick() {
    fetch("/api/approvals").then(function (r) { return r.json(); }).then(render).catch(function () {});
  }
  setInterval(tick, POLL_MS);
  tick();
})();
