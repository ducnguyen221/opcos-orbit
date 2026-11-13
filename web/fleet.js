// fleet.js — màn "Máy trạm" (Giai đoạn 2, TK5): xem việc/thẻ duyệt/sổ lượt của các máy phụ và DỪNG việc, TỪ CHỐI, HOÃN thẻ.
// KHÔNG có Approve và KHÔNG giao việc mới tới máy phụ (duyệt chỉ trên Orbit của chính máy đó). Mọi chuỗi từ máy phụ là DỮ LIỆU
// không tin cậy: dựng DOM bằng textContent, kiểm lại khuôn id/tên trước khi dựng đường gọi, không bao giờ hiện URL hay khoá.
(function () {
  "use strict";
  var box = document.getElementById("fleetList");
  if (!box) return;
  var POLL_MS = 15000;                              // khớp cache 15 s của hub: không thăm dò nhanh hơn
  var NAME_RE = /^[a-z0-9-]{1,32}$/;
  var HEX32 = /^[0-9a-f]{32}$/;
  var ERR = {
    no_key: "chưa có khoá cho máy này", no_pin: "chưa ghim URL (chạy peer_keys gen)", pin_mismatch: "URL trong config khác URL đã ghim",
    bad_url: "URL không hợp lệ (chỉ IP riêng/Tailscale)", bad_name: "tên máy không hợp lệ", bad_config: "cấu hình máy không hợp lệ",
    duplicate_name: "trùng tên máy", duplicate_key: "trùng khoá với máy khác", duplicate_url: "trùng địa chỉ với máy khác",
    unauthorized: "sai khoá hoặc lệch giờ giữa hai máy", forbidden: "máy phụ không cho IP của hub (allowlist)",
    rate_limited: "đang giới hạn tần suất, thử lại sau", unreachable: "không kết nối được", timeout: "quá thời gian chờ",
    bad_response: "máy phụ trả dữ liệu không hợp lệ", upstream_unavailable: "Orbit trên máy phụ không phản hồi",
    local_error: "không đọc được máy này", not_found: "không tìm thấy", not_pending: "thẻ đã được xử lý hoặc hết hạn",
    invalid: "yêu cầu không hợp lệ", bad_request: "yêu cầu không hợp lệ"
  };

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = String(text);
    return e;
  }
  function errText(code) { return ERR[code] || "lỗi"; }

  var msg = el("div", "fleet-msg");

  function act(url, note) {
    msg.textContent = "…";
    fetch(url, { method: "POST" }).then(function (r) {
      return r.json().then(function (d) { return { ok: r.ok, d: d }; }, function () { return { ok: false, d: {} }; });
    }).then(function (x) {
      msg.textContent = x.ok && x.d && x.d.ok ? note + " ✓" : "Không thành công: " + errText(x.d && x.d.error);
      tick();
    }).catch(function () { msg.textContent = "Không gọi được máy chủ."; });
  }

  function stopBtn(peer, job) {
    var b = el("button", "job-kill", "Dừng");
    b.title = "Dừng việc này trên máy phụ";
    b.addEventListener("click", function () {
      if (!window.confirm("Dừng việc #" + job.id + " (" + job.instance + ") trên máy '" + peer + "'? Việc đang ghi dở có thể hỏng.")) return;
      act("/api/fleet/" + encodeURIComponent(peer) + "/jobs/" + job.id + "/stop", "Đã gửi lệnh dừng");
    });
    return b;
  }
  function apprBtn(peer, a, action, label) {
    var b = el("button", "appr-" + (action === "reject" ? "no" : "later"), label);
    b.addEventListener("click", function () {
      act("/api/fleet/" + encodeURIComponent(peer) + "/approvals/" + a.id + "/" + action, label === "Từ chối" ? "Đã từ chối" : "Đã hoãn");
    });
    return b;
  }

  function machineCard(m) {
    var local = m.local === true;
    var c = el("div", "fleet-card" + (m.reachable ? "" : " fleet-down"));
    var head = el("div", "fleet-head");
    head.appendChild(el("span", "dot " + (m.reachable ? "d-working" : "d-error")));
    head.appendChild(el("b", null, local ? "Máy này" : String(m.name)));
    if (m.machine && !local) head.appendChild(el("span", "job-eng", String(m.machine)));
    if (m.stale) head.appendChild(el("span", "sum-pill p-blocked", "dữ liệu cũ " + Number(m.age || 0) + "s"));
    c.appendChild(head);
    if (!m.reachable) {
      c.appendChild(el("div", "fleet-err", "⚠ " + errText(m.error)));
      return c;
    }
    var peerOk = !local && typeof m.name === "string" && NAME_RE.test(m.name);
    var s = m.summary || {};
    var bits = [];
    if (s.working) bits.push(s.working + " đang chạy");
    if (s.blocked) bits.push(s.blocked + " chờ");
    if (s.approvals) bits.push(s.approvals + " chờ duyệt");
    c.appendChild(el("div", "fleet-sum", bits.length ? bits.join(" · ") : "yên ắng"));
    (m.jobs || []).forEach(function (j) {
      var row = el("div", "job-row");
      row.appendChild(el("b", null, String(j.instance)));
      row.appendChild(el("span", "job-eng", String(j.engine)));
      row.appendChild(el("span", "job-time", String(j.state) + (j.elapsed != null ? " · " + Math.round(Number(j.elapsed)) + "s" : "")));
      if (peerOk && (j.state === "working" || j.state === "blocked") && Number.isInteger(j.id) && j.id > 0) row.appendChild(stopBtn(m.name, j));
      c.appendChild(row);
    });
    (m.approvals || []).forEach(function (a) {
      var row = el("div", "appr-card");
      row.appendChild(el("div", "appr-sum", "Chờ duyệt: " + a.instance + " · " + a.engine + " · mức " + a.level + " · #" + a.fp16 + " · còn " + a.expires_in + "s"));
      row.appendChild(el("div", "hint", "Duyệt chỉ làm được trên Orbit của máy đó (cần PIN) — ở đây chỉ từ chối hoặc hoãn."));
      if (peerOk && HEX32.test(String(a.id))) {
        var acts = el("div", "appr-acts");
        acts.appendChild(apprBtn(m.name, a, "reject", "Từ chối"));
        acts.appendChild(apprBtn(m.name, a, "defer", "Hoãn"));
        row.appendChild(acts);
      }
      c.appendChild(row);
    });
    var led = m.ledger || {}, eng = led.engines || {}, parts = Object.keys(eng).map(function (k) {
      return k + " " + eng[k].count + "/" + eng[k].cap + (eng[k].state === "over" ? " ⚠" : "");
    });
    if (parts.length) c.appendChild(el("div", "ledger-line", "Hôm nay: " + parts.join(" · ")));
    return c;
  }

  function render(d) {
    box.textContent = "";
    var ms = (d && d.machines) || [];
    if (d && d.error) box.appendChild(el("div", "fleet-err", "⚠ vòng chụp lỗi: " + errText(d.error)));
    if (ms.length <= 1) box.appendChild(el("p", "empty", "Chưa có máy phụ nào. Thêm trong config.json (settings.peers) theo hướng dẫn «Thêm một máy trạm» trong README."));
    ms.forEach(function (m) { box.appendChild(machineCard(m)); });
    box.appendChild(msg);
  }

  function tick() {
    fetch("/api/fleet").then(function (r) { return r.json(); }).then(render)
      .catch(function () { box.textContent = "Không gọi được /api/fleet."; });
  }
  var refresh = document.getElementById("fleetRefreshBtn");
  if (refresh) refresh.addEventListener("click", function () {
    refresh.disabled = true;
    tick();
    setTimeout(function () { refresh.disabled = false; }, 5000);            // không cho bấm dồn dập
  });
  setInterval(function () { if (!document.hidden) tick(); }, POLL_MS);       // không thăm dò khi tab ẩn (giữ ngân sách GET)
  tick();
})();
