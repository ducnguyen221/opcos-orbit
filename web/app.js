const statusEl = document.getElementById("status");
const transcriptEl = document.getElementById("transcript");
const textInput = document.getElementById("textInput");
const micBtn = document.getElementById("micBtn");
const muteBtn = document.getElementById("muteBtn");
const player = document.getElementById("player");

// Công tắc giọng — MẶC ĐỊNH TẮT. Server chỉ chạy OmniVoice khi BẬT (tiết kiệm tài nguyên).
let voiceOn = localStorage.getItem("ac_voice") === "1";
function applyVoice() {
  muteBtn.textContent = voiceOn ? "🔊" : "🔇";
  muteBtn.classList.toggle("muted", !voiceOn);
  muteBtn.title = voiceOn
    ? "Giọng: BẬT — bấm để tắt (đỡ tốn OmniVoice)"
    : "Giọng: TẮT — bấm để bật nghe";
  if (!voiceOn) player.pause();
}
function sendVoiceState() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "voice", on: voiceOn }));
  }
}
muteBtn.addEventListener("click", () => {
  voiceOn = !voiceOn;
  localStorage.setItem("ac_voice", voiceOn ? "1" : "0");
  applyVoice();
  sendVoiceState();   // báo server: có synth hay không
});
applyVoice();

let ws;
let mediaRecorder;
let chunks = [];
let recording = false;

function setStatus(text, cls) {
  statusEl.textContent = text;
  statusEl.className = "status" + (cls ? " " + cls : "");
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => { setStatus("đã kết nối", "connected"); sendVoiceState(); };
  ws.onclose = () => {
    setStatus("mất kết nối, thử lại…", "error");
    setTimeout(connect, 1500);
  };
  ws.onerror = () => setStatus("lỗi kết nối", "error");

  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "turn") {
      addTurn(msg.speaker, msg.role, msg.content);
    } else if (msg.type === "pending") {
      setPending(true);
    } else if (msg.type === "pending_off") {
      setPending(false);
    } else if (msg.type === "say") {
      // Server chỉ gửi "say" khi giọng đang BẬT → cứ phát.
      player.src = msg.audio_url;
      player.play().catch(() => {});
    } else if (msg.type === "history") {
      // MỞ phiên: xoá khung chat + render toàn bộ lịch sử của phiên
      transcriptEl.innerHTML = "";
      (msg.turns || []).forEach((t) => addTurn(t.speaker, t.role, t.content));
      activeTabId = msg.id;
      renderTabs();
    } else if (msg.type === "cleared") {
      // ĐÓNG phiên: về nháp
      transcriptEl.innerHTML = "";
      activeTabId = null;
      renderTabs();
    }
  };
}

// ── Tab phiên: hiện TẤT CẢ phiên đã lưu + nút ＋ tạo (gộp từ tab Sessions) ──
const sessionTabsEl = document.getElementById("sessionTabs");
const agentStripEl = document.getElementById("agentStrip");
let allSessions = [];     // [{id, name, turns}]
let activeTabId = null;

async function loadSessionTabs() {
  try { allSessions = await (await fetch("/api/sessions")).json(); } catch { allSessions = []; }
  renderTabs();
}

function renderTabs() {
  // Chip phiên trên topbar (đồng bộ với tab đang mở)
  const sessionChip = document.getElementById("sessionChip");
  if (sessionChip) {
    const cur = allSessions.find((t) => t.id === activeTabId);
    sessionChip.textContent = cur ? "📂 " + cur.name : "✎ Nháp";
  }
  if (!sessionTabsEl) return;
  const active = allSessions.filter((t) => !t.archived);   // archive thì ẩn khỏi tab
  const tabs = active.map((t) =>
    `<div class="stab ${t.id === activeTabId ? "active" : ""}" data-id="${t.id}" title="${escapeHtml(t.name)} (${t.turns} lượt)">
       <span class="stab-name">📂 ${escapeHtml(t.name)}</span>
       ${t.id === activeTabId ? `<span class="stab-close" data-id="${t.id}" title="Tắt phiên: dừng task nền + lưu trữ (resume ở tab Khác)">⏻</span>` : ""}
     </div>`).join("");
  sessionTabsEl.innerHTML =
    `<div class="stab ${activeTabId === null ? "active" : ""}" data-id="__draft">✎ Nháp</div>` +
    tabs +
    `<button class="stab-new" id="newSessionTabBtn" title="Tạo phiên mới">＋</button>`;

  sessionTabsEl.querySelectorAll(".stab").forEach((el) => {
    el.addEventListener("click", (e) => {
      if (e.target.classList.contains("stab-close")) return;
      const id = el.dataset.id;
      if (id === "__draft") { window.acCloseSession(); return; }
      const t = allSessions.find((x) => x.id === id);
      if (t) window.acOpenSession(t.id, t.name);
    });
  });
  sessionTabsEl.querySelectorAll(".stab-close").forEach((el) => {
    el.addEventListener("click", async (e) => {
      e.stopPropagation();
      const id = el.dataset.id;
      const t = allSessions.find((x) => x.id === id);
      if (!confirm(`Tắt phiên "${t ? t.name : id}"?\n• Dừng toàn bộ task agent đang chạy nền\n• Lưu trữ phiên (resume sau ở tab Khác)`)) return;
      const r = await fetch(`/api/sessions/${encodeURIComponent(id)}/stop`, { method: "POST" });
      const res = await r.json();
      setPending(false);
      window.acCloseSession();
      await loadSessionTabs();
      if (window.acReloadArchived) window.acReloadArchived();
      addTurn("hệ thống", "", `⏻ Đã tắt phiên (${res.killed_jobs || 0} task nền bị dừng) — lưu trữ, resume ở tab Khác.`);
    });
  });
  const newBtn = document.getElementById("newSessionTabBtn");
  if (newBtn) newBtn.addEventListener("click", async () => {
    const name = prompt("Tên phiên mới:", `phiên ${new Date().toLocaleDateString("vi-VN")}`);
    if (!name) return;
    const r = await fetch("/api/sessions", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const s = await r.json();
    await loadSessionTabs();
    window.acOpenSession(s.id || s.sid || (allSessions[0] && allSessions[0].id), name);
  });
}

window.acOpenSession = function (id, name) {
  if (!ws || ws.readyState !== WebSocket.OPEN || !id) return;
  ws.send(JSON.stringify({ type: "open", id }));   // server trả history
};
window.acCloseSession = function () {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: "close" }));
};
window.acReloadSessionTabs = loadSessionTabs;

// ── Dải "đang làm việc với" = các agent (instance) đang có ─────────────
const ROLE_ICON = { Lead: "🟦", Coder: "🟧", Researcher: "🟪", Reviewer: "🟥" };
loadSessionTabs();
window.acRenderAgentStrip = function (instances) {
  if (!agentStripEl) return;
  const agentsChip = document.getElementById("agentsChip");
  if (agentsChip) agentsChip.textContent = (instances && instances.length) ? "👥 " + instances.length + " agent" : "";
  if (!instances || instances.length === 0) {
    agentStripEl.innerHTML = "<span class='strip-empty'>Chưa có agent — tạo ở tab Agents (bên trái).</span>";
    return;
  }
  agentStripEl.innerHTML = "<span class='strip-label'>Đang làm việc với:</span>" +
    instances.map((i) =>
      `<span class="agent-chip role-${escapeHtml(i.role)}">${ROLE_ICON[i.role] || "⬤"} ${escapeHtml(i.name)} <em>${escapeHtml(i.role)} · ${escapeHtml(i.engine)}</em></span>`).join("");
};
renderTabs();

function addTurn(speaker, role, content) {
  const isUser = speaker === "user";
  const isError = typeof content === "string" && content.startsWith("[ERROR]");
  // Lượt của agent phụ (được Lead giao việc) → hàng collapse gọn như tool-call;
  // Lead (câu trả lời cuối) / user / lỗi → bong bóng đầy đủ.
  const isWorker = !isUser && !isError && role && role !== "Lead" && role !== "User";
  let div;
  if (isWorker) {
    div = document.createElement("details");
    div.className = `turn tool-turn role-${role}`;
    div.innerHTML =
      `<summary class="tool-summary">` +
        `<span class="tool-key">🔧</span>` +
        `<span class="tool-title">${escapeHtml(speaker)} · ${escapeHtml(role)}</span>` +
        `<span class="tool-chev">›</span>` +
      `</summary>` +
      `<div class="content">${escapeHtml(content)}</div>`;
  } else {
    div = document.createElement("div");
    div.className = `turn ${isUser ? "user" : "role-" + role}${isError ? " is-error" : ""}`;
    div.innerHTML = `<div class="meta">${escapeHtml(speaker)}${role ? " · " + escapeHtml(role) : ""}</div>` +
                     `<div class="content">${escapeHtml(content)}</div>`;
  }
  transcriptEl.appendChild(div);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// ── Pending: báo "đang xử lý" + khoá gửi (chống gõ dồn gây duplicate) ──
// + Stall-watchdog (ý Odysseus): nếu Lead im lặng > STALL_MS thì banner cảnh báo,
//   cross-ref Mission Control (job blocked = đang chờ bạn duyệt).
const STALL_MS = 60000;
let pending = false;
let pendingEl = null;
let pendingStart = 0;
let stallTimer = null;

function _pendingContent() {
  return pendingEl && pendingEl.querySelector(".content");
}

async function _checkStall() {
  if (!pending || !pendingEl) return;
  const secs = Math.round((Date.now() - pendingStart) / 1000);
  if (secs * 1000 < STALL_MS) return;
  // đã stall → soi Mission Control xem có job blocked (đang chờ duyệt) không
  let blocked = 0;
  try {
    const d = await (await fetch("/api/jobs")).json();
    blocked = (d.summary && d.summary.blocked) || 0;
  } catch (e) { /* offline: vẫn hiện cảnh báo theo thời gian */ }
  pendingEl.classList.add("stalled");
  const c = _pendingContent();
  if (!c) return;
  c.innerHTML = blocked
    ? `⛔ Có ${blocked} agent đang <b>chờ bạn duyệt</b> — mở <b>Mission Control</b> (⚡) để xử lý. Đã chờ ${secs}s.`
    : `⏳ Lead xử lý lâu (${secs}s) — CLI cold-start hoặc có thể đang treo. Xem <b>Mission Control</b> (⚡); nếu treo, tắt phiên (⏻) để dừng task nền.`;
}

function setPending(on) {
  pending = on;
  textInput.disabled = on;
  micBtn.disabled = on;
  if (on && !pendingEl) {
    pendingEl = document.createElement("div");
    pendingEl.className = "turn pending-turn";
    pendingEl.innerHTML = `<div class="meta">agents</div><div class="content">⏳ đang xử lý… (CLI có thể mất 10–60s lần đầu)</div>`;
    transcriptEl.appendChild(pendingEl);
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
    pendingStart = Date.now();
    stallTimer = setInterval(_checkStall, 5000);
  } else if (!on && pendingEl) {
    if (stallTimer) { clearInterval(stallTimer); stallTimer = null; }
    pendingEl.remove();
    pendingEl = null;
    textInput.focus();
  }
}

function sendText(text) {
  if (!text || pending || ws.readyState !== WebSocket.OPEN) return;
  addTurn("user", "User", text);          // local echo NGAY (server không gửi lại → hết duplicate)
  ws.send(JSON.stringify({ type: "text", data: text }));
}

textInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && textInput.value.trim()) {
    sendText(textInput.value.trim());
    textInput.value = "";
  }
});

async function startRecording() {
  if (recording) return;
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  chunks = [];
  mediaRecorder = new MediaRecorder(stream);
  mediaRecorder.ondataavailable = (e) => chunks.push(e.data);
  mediaRecorder.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    const blob = new Blob(chunks, { type: "audio/webm" });
    const b64 = await blobToBase64(blob);
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "audio", data: b64 }));
    }
  };
  mediaRecorder.start();
  recording = true;
  micBtn.classList.add("recording");
  micBtn.textContent = "🔴 Đang ghi… (thả để gửi)";
}

function stopRecording() {
  if (!recording) return;
  mediaRecorder.stop();
  recording = false;
  micBtn.classList.remove("recording");
  micBtn.textContent = "🎙️ Giữ để nói";
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(reader.result.split(",")[1]);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

micBtn.addEventListener("mousedown", startRecording);
micBtn.addEventListener("mouseup", stopRecording);
micBtn.addEventListener("mouseleave", () => recording && stopRecording());
micBtn.addEventListener("touchstart", (e) => { e.preventDefault(); startRecording(); });
micBtn.addEventListener("touchend", (e) => { e.preventDefault(); stopRecording(); });

connect();
