// Panel Thư viện Agent: chọn agent từ DROPDOWN (có lọc) + engine → tạo instance; quản lý instances.
const instanceListEl = document.getElementById("instanceList");
const scanPathInput = document.getElementById("scanPathInput");
const scanBtn = document.getElementById("scanBtn");
const agentSearch = document.getElementById("agentSearch");
const agentSelect = document.getElementById("agentSelect");
const createEngine = document.getElementById("createEngine");
const createInstBtn = document.getElementById("createInstBtn");
const ENGINES = ["", "claude", "codex", "agy", "gemini", "ollama"];
const EDIT_ENGINES = ["claude", "codex", "agy", "gemini", "ollama"];
const ROLES = ["Lead", "Coder", "Researcher", "Reviewer", "Assistant"];

let agents = [];

async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// ── Agent dropdown (có lọc) ───────────────────────────────────────────
function fillEngineSelect() {
  if (!createEngine) return;
  createEngine.innerHTML = ENGINES.map((e) =>
    `<option value="${e}">${e || "(mặc định của agent)"}</option>`).join("");
}
function renderAgentOptions() {
  if (!agentSelect) return;
  const q = (agentSearch && agentSearch.value.trim().toLowerCase()) || "";
  const filtered = agents.filter((a) =>
    !q || `${a.name} ${a.role} ${a.engine}`.toLowerCase().includes(q));
  agentSelect.innerHTML = filtered.length
    ? filtered.map((a) =>
        `<option value="${escapeHtml(a.name)}">${escapeHtml(a.name)} — ${escapeHtml(a.role)} · ${escapeHtml(a.engine)}</option>`).join("")
    : `<option value="" disabled>Không có agent khớp</option>`;
}
async function loadAgents() {
  agents = await fetchJSON("/api/agents");
  renderAgentOptions();
}
if (agentSearch) agentSearch.addEventListener("input", renderAgentOptions);

async function createInstance() {
  if (!agentSelect || !agentSelect.value) return;
  const agent = agents.find((a) => a.name === agentSelect.value);
  if (!agent) return;
  const engine = createEngine && createEngine.value ? createEngine.value : null;
  createInstBtn.disabled = true;
  try {
    await fetchJSON("/api/instances", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent_name: agent.name, engine, voice: "my-voice" }),
    });
    await loadInstances();
  } finally {
    createInstBtn.disabled = false;
  }
}
if (createInstBtn) createInstBtn.addEventListener("click", createInstance);

// ── Instances ─────────────────────────────────────────────────────────
async function loadInstances() {
  const instances = await fetchJSON("/api/instances");
  renderInstances(instances);
  if (window.acRenderAgentStrip) window.acRenderAgentStrip(instances);
}
window.acReloadInstances = loadInstances;

function optionList(values, selected) {
  return values.map((v) =>
    `<option value="${escapeHtml(v)}"${v === selected ? " selected" : ""}>${escapeHtml(v)}</option>`).join("");
}

function renderInstances(instances) {
  if (!instanceListEl) return;
  const hasLead = instances.some((i) => i.role === "Lead");
  instanceListEl.innerHTML = instances.map((i) => {
    // role có thể là giá trị lạ (từ agent .md) → thêm vào list để select không mất giá trị
    const roleOpts = ROLES.includes(i.role) ? ROLES : [i.role].concat(ROLES);
    const isOllama = i.engine === "ollama";
    return `
    <div class="instance-row" data-name="${escapeHtml(i.name)}">
      <span class="instance-name">${escapeHtml(i.name)}${i.role === "Lead" ? " <span class='lead-badge'>Lead</span>" : ""}</span>
      <span class="instance-meta">${escapeHtml(i.voice)}</span>
      <label class="inst-field">vai
        <select class="editRole">${optionList(roleOpts, i.role)}</select></label>
      <label class="inst-field">engine
        <select class="editEngine">${optionList(EDIT_ENGINES, i.engine)}</select></label>
      <label class="inst-field model-field" ${isOllama ? "" : "hidden"}>model
        <input class="editModel" placeholder="qwen2.5:7b" value="${escapeHtml(i.model || "")}" /></label>
      <button class="saveBtn" disabled>Lưu</button>
      <input class="renameInput" placeholder="tên mới" aria-label="Tên mới" />
      <button class="renameBtn">Đổi tên</button>
      <button class="removeBtn">Xoá</button>
    </div>`;
  }).join("") || "<p class='empty'>Chưa có instance nào.</p>";

  if (!hasLead && instances.length) {
    const warn = document.createElement("p");
    warn.className = "empty inst-warn";
    warn.textContent = "⚠ Chưa có instance nào là Lead — đặt 1 cái thành 'Lead' để Lead điều phối đúng.";
    instanceListEl.prepend(warn);
  }

  instanceListEl.querySelectorAll(".instance-row").forEach((row) => {
    const name = row.dataset.name;
    const roleSel = row.querySelector(".editRole");
    const engSel = row.querySelector(".editEngine");
    const modelInp = row.querySelector(".editModel");
    const modelField = row.querySelector(".model-field");
    const saveBtn = row.querySelector(".saveBtn");
    const markDirty = () => { saveBtn.disabled = false; };
    roleSel.addEventListener("change", markDirty);
    engSel.addEventListener("change", () => {
      if (modelField) modelField.hidden = engSel.value !== "ollama";
      markDirty();
    });
    if (modelInp) modelInp.addEventListener("input", markDirty);

    saveBtn.addEventListener("click", async () => {
      saveBtn.disabled = true;
      await fetchJSON(`/api/instances/${encodeURIComponent(name)}/update`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          role: roleSel.value, engine: engSel.value,
          model: modelInp ? modelInp.value.trim() : null,
        }),
      });
      await loadInstances();
    });
    row.querySelector(".renameBtn").addEventListener("click", async () => {
      const newName = row.querySelector(".renameInput").value.trim();
      if (!newName) return;
      await fetchJSON(`/api/instances/${encodeURIComponent(name)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_name: newName }),
      });
      await loadInstances();
    });
    row.querySelector(".removeBtn").addEventListener("click", async () => {
      await fetchJSON(`/api/instances/${encodeURIComponent(name)}`, { method: "DELETE" });
      await loadInstances();
    });
  });
}

if (scanBtn) {
  scanBtn.addEventListener("click", async () => {
    const path = scanPathInput.value.trim();
    if (!path) return;
    const found = await fetchJSON("/api/agents/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    agents = found;
    renderAgentOptions();
  });
}

fillEngineSelect();
loadAgents();
loadInstances();
