// Panel Voice Studio: liệt kê giọng OmniVoice, set-default, clone (wav), tạo (instruct),
// gán giọng cho instance, xoá giọng.
const voiceListEl = document.getElementById("voiceList");
const voiceCloneWavInput = document.getElementById("voiceCloneWavInput");
const voiceCloneRefText = document.getElementById("voiceCloneRefText");
const voiceCloneName = document.getElementById("voiceCloneName");
const voiceCloneBtn = document.getElementById("voiceCloneBtn");
const voiceCreateInstruct = document.getElementById("voiceCreateInstruct");
const voiceCreateName = document.getElementById("voiceCreateName");
const voiceCreateBtn = document.getElementById("voiceCreateBtn");
const voiceAssignInstanceSelect = document.getElementById("voiceAssignInstanceSelect");
const voiceAssignVoiceSelect = document.getElementById("voiceAssignVoiceSelect");
const voiceAssignBtn = document.getElementById("voiceAssignBtn");
const voiceStatusEl = document.getElementById("voiceStatus");

let voiceNames = [];

async function voiceFetchJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}

function voiceEscape(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function setVoiceStatus(msg) {
  if (voiceStatusEl) voiceStatusEl.textContent = msg;
}

async function loadVoices() {
  voiceNames = await voiceFetchJSON("/api/voices");
  renderVoices();
  fillVoiceSelect();
  await loadInstancesForAssign();
}

function renderVoices() {
  if (!voiceListEl) return;
  voiceListEl.innerHTML = voiceNames.map((v) => `
    <div class="instance-row" data-name="${voiceEscape(v)}">
      <span class="instance-name">${voiceEscape(v)}</span>
      <button class="voiceDefaultBtn">Set-default</button>
      <button class="voiceDeleteBtn">Xoá</button>
    </div>`).join("") || "<p class='empty'>Chưa có giọng nào.</p>";

  voiceListEl.querySelectorAll(".instance-row").forEach((row) => {
    const name = row.dataset.name;
    row.querySelector(".voiceDefaultBtn").addEventListener("click", async () => {
      await voiceFetchJSON("/api/voices/default", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      setVoiceStatus(`Đã đặt mặc định: ${name}`);
    });
    row.querySelector(".voiceDeleteBtn").addEventListener("click", async () => {
      await voiceFetchJSON(`/api/voices/${encodeURIComponent(name)}`, { method: "DELETE" });
      setVoiceStatus(`Đã xoá: ${name}`);
      await loadVoices();
    });
  });
}

function fillVoiceSelect() {
  if (!voiceAssignVoiceSelect) return;
  voiceAssignVoiceSelect.innerHTML = voiceNames.map((v) => `<option value="${voiceEscape(v)}">${voiceEscape(v)}</option>`).join("");
}

async function loadInstancesForAssign() {
  if (!voiceAssignInstanceSelect) return;
  const instances = await voiceFetchJSON("/api/instances");
  voiceAssignInstanceSelect.innerHTML = instances.map((i) => `<option value="${voiceEscape(i.name)}">${voiceEscape(i.name)} (${voiceEscape(i.voice)})</option>`).join("");
}

if (voiceCloneBtn) {
  voiceCloneBtn.addEventListener("click", async () => {
    const f = voiceCloneWavInput && voiceCloneWavInput.files[0];
    const refText = (voiceCloneRefText && voiceCloneRefText.value.trim()) || "";
    const name = (voiceCloneName && voiceCloneName.value.trim()) || "";
    if (!f || !refText || !name) { setVoiceStatus("Cần chọn wav + nhập ref text + tên."); return; }
    const fd = new FormData();
    fd.append("file", f); fd.append("ref_text", refText); fd.append("name", name);
    setVoiceStatus("Đang nhân bản giọng…");
    await voiceFetchJSON("/api/voices/clone", { method: "POST", body: fd });
    setVoiceStatus(`Đã tạo giọng: ${name}`);
    await loadVoices();
  });
}

if (voiceCreateBtn) {
  voiceCreateBtn.addEventListener("click", async () => {
    const instruct = (voiceCreateInstruct && voiceCreateInstruct.value.trim()) || "";
    const name = (voiceCreateName && voiceCreateName.value.trim()) || "";
    if (!instruct || !name) { setVoiceStatus("Cần nhập mô tả giọng + tên."); return; }
    setVoiceStatus("Đang tạo giọng…");
    await voiceFetchJSON("/api/voices/create", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruct, name }),
    });
    setVoiceStatus(`Đã tạo giọng: ${name}`);
    await loadVoices();
  });
}

if (voiceAssignBtn) {
  voiceAssignBtn.addEventListener("click", async () => {
    const inst = voiceAssignInstanceSelect && voiceAssignInstanceSelect.value;
    const voice = voiceAssignVoiceSelect && voiceAssignVoiceSelect.value;
    if (!inst || !voice) return;
    await voiceFetchJSON(`/api/instances/${encodeURIComponent(inst)}/voice`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ voice }),
    });
    setVoiceStatus(`Đã gán ${voice} cho ${inst}`);
    await loadInstancesForAssign();
  });
}

loadVoices();
