// Panel Session + Remote: list/new/rename/resume phiên hội thoại, bật/tắt remote-control.
const sessNewInput = document.getElementById("sessNewInput");
const sessNewBtn = document.getElementById("sessNewBtn");
const sessListEl = document.getElementById("sessionList");
const remoteOnBtn = document.getElementById("remoteOnBtn");
const remoteOffBtn = document.getElementById("remoteOffBtn");
const remoteStatusEl = document.getElementById("remoteStatus");

async function sessFetchJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}

function sessEscape(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function loadSessions() {
  const sessions = await sessFetchJSON("/api/sessions");
  renderSessions(sessions);
}
window.acReloadArchived = loadSessions;

function renderSessions(sessions) {
  if (!sessListEl) return;
  sessListEl.innerHTML = sessions.map((s) => `
    <div class="instance-row ${s.archived ? "archived" : ""}" data-id="${sessEscape(s.id)}">
      <span class="instance-name">${s.archived ? "🗄️ " : ""}${sessEscape(s.name)}</span>
      <span class="instance-meta">${s.turns} lượt${s.archived ? " · đã lưu trữ" : ""}</span>
      <input class="renameInput" placeholder="tên mới" />
      <button class="renameBtn">Đổi tên</button>
      ${s.archived
        ? `<button class="resumeArchBtn">▶ Resume</button>`
        : `<button class="openBtn">Mở</button>`}
    </div>`).join("") || "<p class='empty'>Chưa có phiên nào.</p>";

  sessListEl.querySelectorAll(".instance-row").forEach((row) => {
    const id = row.dataset.id;
    row.querySelector(".renameBtn").addEventListener("click", async () => {
      const name = row.querySelector(".renameInput").value.trim();
      if (!name) return;
      await sessFetchJSON(`/api/sessions/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      await loadSessions();
      if (window.acReloadSessionTabs) window.acReloadSessionTabs();   // sync tab bar
    });
    const openBtn = row.querySelector(".openBtn");
    if (openBtn) openBtn.addEventListener("click", () => {
      const name = row.querySelector(".instance-name").textContent;
      if (window.acOpenSession) window.acOpenSession(id, name);   // mở live trong khung chat
    });
    const resumeBtn = row.querySelector(".resumeArchBtn");
    if (resumeBtn) resumeBtn.addEventListener("click", async () => {
      await sessFetchJSON(`/api/sessions/${encodeURIComponent(id)}/unarchive`, { method: "POST" });
      await loadSessions();
      if (window.acReloadSessionTabs) window.acReloadSessionTabs();
      const name = row.querySelector(".instance-name").textContent.replace("🗄️ ", "");
      if (window.acOpenSession) window.acOpenSession(id, name);   // resume = hiện lại tab + mở luôn
    });
  });
}

if (sessNewBtn) {
  sessNewBtn.addEventListener("click", async () => {
    const name = (sessNewInput.value || "").trim() || `phiên ${new Date().toLocaleString("vi-VN")}`;
    await sessFetchJSON("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    sessNewInput.value = "";
    await loadSessions();
  });
}

async function toggleRemote(on) {
  if (!remoteStatusEl) return;
  remoteStatusEl.textContent = "đang xử lý…";
  try {
    const r = await sessFetchJSON("/api/remote/toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ on }),
    });
    remoteStatusEl.textContent = r.ok
      ? `Remote-control: ${r.requested === "on" ? "BẬT" : "TẮT"} (${sessEscape(r.output || "")})`
      : `Không tự bật được (${sessEscape(r.output || "")}). ${sessEscape(r.manual_hint)}`;
  } catch (e) {
    remoteStatusEl.textContent = `Lỗi: ${sessEscape(e.message)}`;
  }
}

if (remoteOnBtn) remoteOnBtn.addEventListener("click", () => toggleRemote(true));
if (remoteOffBtn) remoteOffBtn.addEventListener("click", () => toggleRemote(false));

loadSessions();
