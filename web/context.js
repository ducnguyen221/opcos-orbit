// Panel Context: quét folder, upload file, gắn (attach) vào 1 instance.
const ctxScanPathInput = document.getElementById("ctxScanPathInput");
const ctxScanBtn = document.getElementById("ctxScanBtn");
const ctxFileList = document.getElementById("ctxFileList");
const ctxUploadInput = document.getElementById("ctxUploadInput");
const ctxInstanceSelect = document.getElementById("ctxInstanceSelect");
const ctxAttachedList = document.getElementById("ctxAttachedList");

let ctxFiles = [];
let ctxAttached = [];

async function ctxFetchJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}

function ctxEscape(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function renderCtxFiles() {
  if (!ctxFileList) return;
  ctxFileList.innerHTML = ctxFiles.map((f, idx) => `
    <div class="agent-row">
      <span class="agent-name">${ctxEscape(f.path)}</span>
      <span class="agent-meta">${f.size}b · ${ctxEscape(f.type)}</span>
      <button data-idx="${idx}" class="ctxAttachBtn">Gắn vào instance</button>
    </div>`).join("") || "<p class='empty'>Chưa quét file nào.</p>";
  ctxFileList.querySelectorAll(".ctxAttachBtn").forEach((btn) => {
    btn.addEventListener("click", () => attachFile(ctxFiles[Number(btn.dataset.idx)].path));
  });
}

function renderCtxAttached() {
  if (!ctxAttachedList) return;
  ctxAttachedList.innerHTML = ctxAttached.map((a) => `
    <div class="agent-row">
      <span class="agent-name">${ctxEscape(a.instance)}</span>
      <span class="agent-meta">${ctxEscape(a.path)} · ${ctxEscape(a.mode)}</span>
    </div>`).join("") || "<p class='empty'>Chưa gắn context nào.</p>";
}

async function attachFile(path) {
  const instance = ctxInstanceSelect && ctxInstanceSelect.value;
  if (!instance) { alert("Chọn instance trước."); return; }
  const r = await ctxFetchJSON("/api/context/attach", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instance, path }),
  });
  ctxAttached.push(r);
  renderCtxAttached();
}

async function loadCtxInstances() {
  if (!ctxInstanceSelect) return;
  const instances = await ctxFetchJSON("/api/instances");
  ctxInstanceSelect.innerHTML = instances
    .map((i) => `<option value="${ctxEscape(i.name)}">${ctxEscape(i.name)}</option>`)
    .join("") || "<option value=''>(chưa có instance)</option>";
}

if (ctxScanBtn) {
  ctxScanBtn.addEventListener("click", async () => {
    const path = ctxScanPathInput.value.trim();
    if (!path) return;
    ctxFiles = await ctxFetchJSON("/api/context/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    renderCtxFiles();
    await loadCtxInstances();
  });
}

if (ctxUploadInput) {
  ctxUploadInput.addEventListener("change", async () => {
    const file = ctxUploadInput.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch("/api/context/upload", { method: "POST", body: fd });
    if (!r.ok) return;
    const body = await r.json();
    ctxFiles.push({ path: body.path, size: file.size, type: (file.name.split(".").pop() || "") });
    renderCtxFiles();
    ctxUploadInput.value = "";
  });
}

renderCtxFiles();
renderCtxAttached();
loadCtxInstances();
