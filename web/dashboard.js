// dashboard.js — Mission Control + System pane (Console v2).
// Hành vi distill từ herdr: badge tổng hợp blocked>working>done-unseen; notify
// CHỈ khi chuyển trạng thái VÀ tab/panel không active (suppress khi đang nhìn).
(function () {
  "use strict";

  var POLL_MS = 2000;
  var lastStates = {};        // job id -> state đã thấy lần trước (bắt transition)
  var dashPanel = document.getElementById("dashPanel");
  var jobList = document.getElementById("jobList");
  var summaryEl = document.getElementById("dashSummary");
  var badge = document.getElementById("dashBadge");

  function panelVisible() {
    return dashPanel && dashPanel.classList.contains("active") &&
      !document.getElementById("sidebar").classList.contains("collapsed") &&
      document.visibilityState === "visible";
  }

  function fmtElapsed(s) {
    s = Math.max(0, Math.round(s));
    if (s < 60) return s + "s";
    var m = Math.floor(s / 60);
    return m + "m" + String(s % 60).padStart(2, "0") + "s";
  }

  function esc(t) {
    var d = document.createElement("span");
    d.textContent = t == null ? "" : String(t);
    return d.innerHTML;
  }

  function notify(title, body) {
    if (!("Notification" in window)) return;
    if (Notification.permission === "granted") {
      new Notification(title, { body: body });
    } else if (Notification.permission !== "denied") {
      Notification.requestPermission();
    }
  }

  function render(data) {
    var jobs = data.jobs || [];
    var sum = data.summary || {};

    // rail badge: số job cần chú ý (blocked + error chưa xem) — kiểu herdr aggregate
    var attention = sum.attention || 0;
    if (badge) {
      badge.hidden = attention === 0;
      badge.textContent = attention;
    }
    if (summaryEl) {
      var bits = [];
      if (sum.blocked) bits.push('<span class="sum-pill p-blocked">' + sum.blocked + " blocked</span>");
      if (sum.working) bits.push('<span class="sum-pill p-working">' + sum.working + " working</span>");
      if (sum.done_unseen) bits.push('<span class="sum-pill p-done">' + sum.done_unseen + " done</span>");
      if (sum.error_unseen) bits.push('<span class="sum-pill p-error">' + sum.error_unseen + " lỗi</span>");
      summaryEl.innerHTML = bits.length ? bits.join(" ") : '<span class="empty">yên ắng — không job nào chạy</span>';
    }

    // transition detect → notify (suppress khi panel đang được nhìn — luật herdr)
    jobs.forEach(function (j) {
      var prev = lastStates[j.id];
      if (prev && prev !== j.state && !panelVisible()) {
        if (j.state === "blocked") notify("⛔ " + j.instance + " cần bạn", j.last_line || j.prompt);
        else if ((prev === "working" || prev === "blocked") && (j.state === "done" || j.state === "error"))
          notify((j.state === "done" ? "✅ " : "❌ ") + j.instance + " xong", j.prompt);
      }
      lastStates[j.id] = j.state;
    });

    if (!jobList) return;
    if (!jobs.length) {
      jobList.innerHTML = '<p class="empty">chưa có job nào — giao việc trong chat là thấy ở đây</p>';
      return;
    }
    jobList.innerHTML = jobs.map(function (j) {
      var live = j.state === "working" || j.state === "blocked";
      var stateCls = "st-" + j.state + (j.state === "done" && j.seen ? " seen" : "");
      return (
        '<div class="job-row ' + stateCls + '" data-id="' + j.id + '">' +
          '<span class="dot d-' + (j.state === "done" && j.seen ? "idle" : j.state) + '"></span>' +
          '<div class="job-main">' +
            '<div class="job-head"><b>' + esc(j.instance) + "</b>" +
              '<span class="job-eng">' + esc(j.engine) + "</span>" +
              '<span class="job-time">' + fmtElapsed(j.elapsed) + "</span></div>" +
            '<div class="job-prompt">' + esc(j.prompt) + "</div>" +
            (j.last_line ? '<div class="job-last">' + esc(j.last_line) + "</div>" : "") +
            (j.state === "blocked" ? '<div class="job-block-hint">⛔ có vẻ đang chờ bạn (im lặng ' + fmtElapsed(j.silence) + ")</div>" : "") +
          "</div>" +
          '<div class="job-acts">' +
            (live ? '<button class="job-kill" data-id="' + j.id + '" title="Dừng job">✕</button>' : "") +
            (!live && !j.seen ? '<button class="job-seen" data-id="' + j.id + '" title="Đã xem">✓</button>' : "") +
          "</div>" +
        "</div>"
      );
    }).join("");
  }

  // ── Bus feed (socket agent-to-agent) ──────────────────────────────────────
  var busFeed = document.getElementById("busFeed");
  var busTo = document.getElementById("busTo");
  var busText = document.getElementById("busText");
  var busSendBtn = document.getElementById("busSendBtn");
  var lastBusId = 0;

  function fmtTime(ts) {
    try { return new Date(ts * 1000).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" }); }
    catch (e) { return ""; }
  }

  function renderBus(msgs) {
    if (!busFeed) return;
    if (!msgs.length) { busFeed.innerHTML = '<p class="empty">chưa có tin trao đổi</p>'; return; }
    busFeed.innerHTML = msgs.map(function (m) {
      return '<div class="bus-msg' + (m.consumed ? " consumed" : "") + '">' +
        '<span class="bus-from">' + esc(m.sender) + "</span>" +
        '<span class="bus-arrow">→</span>' +
        '<span class="bus-to">' + esc(m.recipient) + "</span>" +
        '<span class="bus-txt">' + esc(m.text) + "</span>" +
        '<span class="bus-time">' + fmtTime(m.ts) + "</span></div>";
    }).join("");
    var last = msgs[msgs.length - 1];
    if (last && last.id !== lastBusId) { lastBusId = last.id; busFeed.scrollTop = busFeed.scrollHeight; }
  }

  function tickBus() {
    fetch("/api/bus").then(function (r) { return r.json(); })
      .then(function (d) { renderBus(d.messages || []); }).catch(function () {});
  }

  function fillBusTo() {
    if (!busTo) return;
    fetch("/api/instances").then(function (r) { return r.json(); }).then(function (insts) {
      busTo.innerHTML = '<option value="all">all</option>' +
        (insts || []).map(function (i) { return '<option value="' + esc(i.name) + '">' + esc(i.name) + "</option>"; }).join("");
    }).catch(function () {});
  }

  if (busSendBtn) busSendBtn.addEventListener("click", function () {
    var text = (busText.value || "").trim();
    if (!text) return;
    fetch("/api/bus", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sender: "user", recipient: busTo ? busTo.value : "all", text: text }),
    }).then(function () { busText.value = ""; tickBus(); });
  });
  if (busText) busText.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); busSendBtn.click(); }
  });

  function tick() {
    fetch("/api/jobs").then(function (r) { return r.json(); }).then(render).catch(function () {});
    tickBus();
  }

  if (jobList) {
    jobList.addEventListener("click", function (e) {
      var kill = e.target.closest(".job-kill");
      var seen = e.target.closest(".job-seen");
      if (kill) fetch("/api/jobs/" + kill.dataset.id + "/kill", { method: "POST" }).then(tick);
      if (seen) fetch("/api/jobs/" + seen.dataset.id + "/seen", { method: "POST" }).then(tick);
    });
    var seenAll = document.getElementById("seenAllBtn");
    if (seenAll) seenAll.addEventListener("click", function () {
      fetch("/api/jobs/seen-all", { method: "POST" }).then(tick);
    });
    setInterval(tick, POLL_MS);
    tick();
    fillBusTo();
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }
  }

  // ── System pane ────────────────────────────────────────────────────────────
  var sysReg = document.getElementById("sysRegistry");
  var sysMcp = document.getElementById("sysMcp");

  function loadSystem() {
    fetch("/api/system").then(function (r) { return r.json(); }).then(function (d) {
      var reg = d.registry || {};
      if (sysReg) {
        if (!reg.ok) { sysReg.innerHTML = '<p class="empty">' + esc(reg.error || "lỗi") + "</p>"; return; }
        var prio = reg.by_priority || {};
        sysReg.innerHTML =
          '<div class="sys-stat"><b>' + reg.total + "</b> thành phần · cập nhật " + esc(reg.updated) + "</div>" +
          '<div class="sys-pills">' +
            ["core", "recommended", "optional", "deprecated"].map(function (p) {
              return prio[p] ? '<span class="sum-pill p-' + p + '">' + prio[p] + " " + p + "</span>" : "";
            }).join(" ") + "</div>" +
          '<div class="sys-cats">' + Object.keys(reg.by_category || {}).map(function (c) {
            return esc(c) + " " + reg.by_category[c];
          }).join(" · ") + "</div>";
      }
      if (sysMcp) {
        var mcp = d.mcp || {};
        sysMcp.innerHTML = ["claude", "codex", "gemini"].map(function (tool) {
          var list = mcp[tool] || [];
          return '<div class="sys-mcp-tool"><b>' + tool + "</b> (" + list.length + "): " +
            (list.map(function (s) { return esc(s.name); }).join(", ") || "—") + "</div>";
        }).join("");
      }
    }).catch(function () {
      if (sysReg) sysReg.innerHTML = '<p class="empty">không gọi được /api/system</p>';
    });
  }

  var openReg = document.getElementById("sysOpenRegistryBtn");
  if (openReg) openReg.addEventListener("click", function () {
    window.open("/api/system/registry-page", "_blank");
  });
  var refresh = document.getElementById("sysRefreshBtn");
  if (refresh) refresh.addEventListener("click", loadSystem);

  // Kiểm tra LIVE MCP: gọi `claude mcp list` nền (chậm) → Connected/Failed thật.
  var mcpLiveBtn = document.getElementById("sysMcpLiveBtn");
  var mcpLiveEl = document.getElementById("sysMcpLive");
  if (mcpLiveBtn && mcpLiveEl) mcpLiveBtn.addEventListener("click", function () {
    mcpLiveBtn.disabled = true;
    var t0 = mcpLiveBtn.textContent;
    mcpLiveBtn.textContent = "⏳ đang nối từng server…";
    mcpLiveEl.innerHTML = '<p class="empty">đang chạy claude mcp list (10-60s)…</p>';
    fetch("/api/system/mcp-live").then(function (r) { return r.json(); }).then(function (d) {
      if (!d.ok) { mcpLiveEl.innerHTML = '<p class="empty">' + esc(d.error || "lỗi") + "</p>"; return; }
      mcpLiveEl.innerHTML =
        '<div class="sys-stat"><b>' + d.connected + "/" + d.total + "</b> Connected</div>" +
        (d.servers || []).map(function (s) {
          return '<div class="mcp-live-row ' + (s.connected ? "up" : "down") + '">' +
            '<span class="mcp-live-dot"></span>' + esc(s.name) +
            '<span class="mcp-live-st">' + esc(s.status) + "</span></div>";
        }).join("");
    }).catch(function () {
      mcpLiveEl.innerHTML = '<p class="empty">không gọi được /api/system/mcp-live</p>';
    }).then(function () {
      mcpLiveBtn.disabled = false; mcpLiveBtn.textContent = t0;
    });
  });
  var adoptBtn = document.getElementById("sysAdoptBtn");
  if (adoptBtn) adoptBtn.addEventListener("click", function () {
    var url = (document.getElementById("sysAdoptInput").value || "").trim();
    if (!url) return;
    var input = document.getElementById("textInput");
    if (input) {
      input.value = "Phân tích repo " + url + " theo quy trình adopt-repo (nghiên cứu → tư vấn → chờ mình duyệt).";
      input.focus();
    }
  });
  if (sysReg) loadSystem();
})();
