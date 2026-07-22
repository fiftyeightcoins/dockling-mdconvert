const state = {
  mode: "oil_dataset",
  provider: "gemini",
};

const els = {
  modeBtns: document.querySelectorAll(".mode-btn"),
  uploadPanel: document.getElementById("uploadPanel"),
  dropzone: document.getElementById("dropzone"),
  fileInput: document.getElementById("fileInput"),
  uploadStatus: document.getElementById("uploadStatus"),
  docList: document.getElementById("docList"),
  docCount: document.getElementById("docCount"),
  docListLabel: document.getElementById("docListLabel"),
  providerSelect: document.getElementById("providerSelect"),
  modeTitle: document.getElementById("modeTitle"),
  modeSub: document.getElementById("modeSub"),
  statusPill: document.getElementById("statusPill"),
  chat: document.getElementById("chat"),
  welcome: document.getElementById("welcome"),
  queryInput: document.getElementById("queryInput"),
  sendBtn: document.getElementById("sendBtn"),
};

const MODE_META = {
  oil_dataset: {
    title: "Oil Market Dataset",
    sub: "Events · sanctions · exports · risk · prices — graph-connected",
  },
  documents: {
    title: "Document Knowledge Base",
    sub: "Uploaded reports converted to Markdown via Docling, then graph-ingested",
  },
};

// ---------- mode switching ----------
els.modeBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    els.modeBtns.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.mode = btn.dataset.mode;
    const meta = MODE_META[state.mode];
    els.modeTitle.textContent = meta.title;
    els.modeSub.textContent = meta.sub;
    els.uploadPanel.style.display = state.mode === "documents" ? "block" : "none";
    els.docListLabel.textContent = state.mode === "documents" ? "Knowledge base" : "Dataset source";
    renderDocList();
  });
});

els.providerSelect.addEventListener("change", (e) => {
  state.provider = e.target.value;
});

// ---------- document list ----------
async function fetchDocs() {
  try {
    const res = await fetch("/api/documents");
    return await res.json();
  } catch {
    return [];
  }
}

async function renderDocList() {
  if (state.mode === "oil_dataset") {
    els.docList.innerHTML = `
      <div class="doc-item"><span class="dot-doc"></span> geopolitical_events.csv</div>
      <div class="doc-item"><span class="dot-doc"></span> sanctions_timeline.csv</div>
      <div class="doc-item"><span class="dot-doc"></span> iran_oil_exports.csv</div>
      <div class="doc-item"><span class="dot-doc"></span> risk_indicators.csv</div>
      <div class="doc-item"><span class="dot-doc"></span> oil_prices_daily.csv</div>`;
    els.docCount.textContent = "5";
    return;
  }
  const docs = await fetchDocs();
  els.docCount.textContent = docs.length;
  if (!docs.length) {
    els.docList.innerHTML = `<div class="empty-hint">No documents ingested yet.</div>`;
    return;
  }
  els.docList.innerHTML = docs
    .map((d) => `<div class="doc-item"><span class="dot-doc"></span> ${escapeHtml(d.filename)}</div>`)
    .join("");
}

// ---------- upload ----------
els.dropzone.addEventListener("click", () => els.fileInput.click());
els.dropzone.addEventListener("dragover", (e) => { e.preventDefault(); els.dropzone.style.borderColor = "var(--accent)"; });
els.dropzone.addEventListener("dragleave", () => { els.dropzone.style.borderColor = ""; });
els.dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  els.dropzone.style.borderColor = "";
  if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
});
els.fileInput.addEventListener("change", (e) => {
  if (e.target.files.length) uploadFiles(e.target.files);
});

async function uploadFiles(fileList) {
  const formData = new FormData();
  Array.from(fileList).forEach((f) => formData.append("files", f));
  formData.append("provider", state.provider);

  els.uploadStatus.innerHTML = `<div class="upload-item">Converting &amp; ingesting ${fileList.length} file(s)…</div>`;

  try {
    const res = await fetch("/api/upload", { method: "POST", body: formData });
    const data = await res.json();
    els.uploadStatus.innerHTML = data.results
      .map((r) => {
        if (r.status === "error") {
          return `<div class="upload-item error">✕ ${escapeHtml(r.filename)}<br/><span style="font-size:10px">${escapeHtml(r.error || "")}</span></div>`;
        }
        return `<div class="upload-item ok">✓ ${escapeHtml(r.filename)}</div>`;
      })
      .join("");
    renderDocList();
  } catch (e) {
    els.uploadStatus.innerHTML = `<div class="upload-item error">Upload failed: ${escapeHtml(String(e))}</div>`;
  }
}

// ---------- chat ----------
function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** Highlight trader-relevant signals: $ amounts, %, citation ids, dates. */
function formatAnswer(raw) {
  let text = escapeHtml(raw);

  // citation ids like [event_12], [sanction_3], [price_month_2012-05]
  text = text.replace(/\[(event|sanction|export|risk|price_event|price_month)_[\w-]+\]/g,
    (m) => `<span class="cite">${m}</span>`);

  // dollar amounts
  text = text.replace(/\$\d[\d,]*(\.\d+)?(\/bbl|\/oz|bn|mbd)?/g,
    (m) => `<span class="num">${m}</span>`);

  // percentages — color by sign
  text = text.replace(/-?\d+(\.\d+)?%/g, (m) =>
    m.startsWith("-") ? `<span class="pct-down">${m}</span>` : `<span class="pct-up">${m}</span>`);

  // ISO dates and YYYY-MM
  text = text.replace(/\b\d{4}-\d{2}(-\d{2})?\b/g, (m) => `<span class="datechip">${m}</span>`);

  return text;
}

function appendUserMessage(text) {
  els.welcome.style.display = "none";
  const div = document.createElement("div");
  div.className = "msg user";
  div.innerHTML = `<div class="bubble-user">${escapeHtml(text)}</div>`;
  els.chat.appendChild(div);
  els.chat.scrollTop = els.chat.scrollHeight;
}

function appendAssistantPlaceholder() {
  const div = document.createElement("div");
  div.className = "msg assistant";
  div.innerHTML = `
    <div class="bubble-assistant">
      <div class="assistant-meta">
        <span class="badge">${state.mode === "oil_dataset" ? "Oil Dataset GraphRAG" : "Document GraphRAG"}</span>
        <span>${state.provider}</span>
      </div>
      <div class="typing"><span></span><span></span><span></span></div>
    </div>`;
  els.chat.appendChild(div);
  els.chat.scrollTop = els.chat.scrollHeight;
  return div;
}

async function sendQuery() {
  const q = els.queryInput.value.trim();
  if (!q) return;
  els.queryInput.value = "";
  els.queryInput.style.height = "auto";
  els.sendBtn.disabled = true;
  els.statusPill.classList.add("loading");
  els.statusPill.querySelector(".dot").nextSibling.textContent = " Thinking…";

  appendUserMessage(q);
  const placeholder = appendAssistantPlaceholder();

  try {
    const res = await fetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q, mode: state.mode, provider: state.provider }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Query failed");

    placeholder.querySelector(".bubble-assistant").innerHTML = `
      <div class="assistant-meta">
        <span class="badge">${state.mode === "oil_dataset" ? "Oil Dataset GraphRAG" : "Document GraphRAG"}</span>
        <span>${data.provider}</span>
      </div>
      <div class="answer-text">${formatAnswer(data.answer)}</div>`;
  } catch (e) {
    placeholder.querySelector(".bubble-assistant").classList.add("error-bubble");
    placeholder.querySelector(".bubble-assistant").innerHTML = `
      <div class="assistant-meta"><span class="badge">Error</span></div>
      <div class="answer-text">${escapeHtml(String(e.message || e))}</div>`;
  } finally {
    els.sendBtn.disabled = false;
    els.statusPill.classList.remove("loading");
    els.statusPill.querySelector(".dot").nextSibling.textContent = " Ready";
    els.chat.scrollTop = els.chat.scrollHeight;
  }
}

els.sendBtn.addEventListener("click", sendQuery);
els.queryInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendQuery();
  }
});
els.queryInput.addEventListener("input", () => {
  els.queryInput.style.height = "auto";
  els.queryInput.style.height = Math.min(els.queryInput.scrollHeight, 140) + "px";
});

document.querySelectorAll(".suggestion-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    els.queryInput.value = chip.dataset.q;
    sendQuery();
  });
});

// initial paint
renderDocList();
