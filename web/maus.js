// maus.js — thẻ OpenMausBot (bước 6b, D1): chỉ hiện trạng thái + nút mở ở tab riêng. KHÔNG nhúng iframe
// (OpenMausBot gắn frame-ancestors 'none'). Không có nút khởi động/tắt: việc đó chạy bằng maus.ps1 / run.ps1.
(function () {
  "use strict";
  var card = document.getElementById("mausCard");
  var dot = document.getElementById("mausDot");
  if (!card) return;
  var URL_OK = /^http:\/\/127\.0\.0\.1:\d{4,5}\/?$/;       // chỉ chấp nhận đúng dạng loopback từ máy chủ

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = String(text);
    return e;
  }

  function render(st) {
    card.textContent = "";
    var running = !!st.running;
    if (dot) { dot.hidden = !running; dot.title = "OpenMausBot đang chạy"; }
    var row = el("div", "maus-row");
    row.appendChild(el("span", "dot " + (running ? "d-working" : "d-idle")));
    row.appendChild(el("b", null, running ? "Đang chạy" : "Chưa chạy"));
    row.appendChild(el("span", "job-eng", "cổng " + st.port));
    card.appendChild(row);
    if (running && typeof st.url === "string" && URL_OK.test(st.url)) {
      var a = el("a", "maus-open", "Mở OpenMausBot ở tab mới ↗");
      a.href = st.url; a.target = "_blank"; a.rel = "noopener noreferrer";
      card.appendChild(a);
    } else if (!running) {
      card.appendChild(el("p", "empty", "Chưa có OpenMausBot ở cổng này. Khởi động bằng lệnh bên dưới."));
    }
  }

  function tick() {
    fetch("/api/maus/status").then(function (r) { return r.json(); }).then(render)
      .catch(function () { card.textContent = "Không gọi được /api/maus/status."; });
  }
  setInterval(tick, 5000);
  tick();
})();
