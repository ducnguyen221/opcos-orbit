// ledger.js — dòng "Hôm nay" trong Mission Control (6c nhịp 1): số lượt agent theo engine + trần MỀM.
// Trần chỉ CẢNH BÁO (ok/warn/over), không chặn. Dữ liệu từ /api/ledger/summary; dựng DOM bằng textContent.
(function () {
  "use strict";
  var box = document.getElementById("ledgerLine");
  if (!box) return;
  var TRIG = { human_turn: "người gõ", lead_delegate: "Lead giao", approved: "đã duyệt", direct: "trực tiếp" };

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = String(text);
    return e;
  }

  function render(d) {
    box.textContent = "";
    var engines = d.engines || {};
    var names = Object.keys(engines);
    if (!names.length) { box.appendChild(el("span", "empty", "Hôm nay chưa có lượt agent nào.")); return; }
    box.appendChild(el("span", null, "Hôm nay: "));
    names.forEach(function (n) {
      var e = engines[n];
      var cls = "sum-pill " + (e.state === "over" ? "p-error" : e.state === "warn" ? "p-blocked" : "p-done");
      box.appendChild(el("span", cls, n + " " + e.count + "/" + e.cap));
      box.appendChild(document.createTextNode(" "));
    });
    var t = d.triggers || {};
    var bits = Object.keys(t).map(function (k) { return (TRIG[k] || k) + " " + t[k]; });
    if (bits.length) box.appendChild(el("span", "hint", " · " + bits.join(" · ")));
    var over = names.some(function (n) { return engines[n].state === "over"; });
    if (over) box.appendChild(el("div", "appr-warn",
      "⚠ Đã chạm trần mềm trong ngày (chỉ cảnh báo — Orbit không chặn). Lượt Orbit gọi CLI trực tiếp, không vào sổ của cầu ask-*."));
  }

  function tick() {
    fetch("/api/ledger/summary").then(function (r) { return r.json(); }).then(render).catch(function () {});
  }
  setInterval(tick, 10000);
  tick();
})();
