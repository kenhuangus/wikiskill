"use strict";
/* WikiSkill UI client — vanilla JS, no dependencies (ui_design.md §6–§7). */

const $ = (id) => document.getElementById(id);
const S = {
  ws: null,               // workspace data {root, tree, files}
  lastResult: null,       // {evolution, evaluation, workspace_root}
  activeRoot: null,
};

/* ---------- utils ---------- */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    method: opts.method || (opts.body ? "POST" : "GET"),
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (_) { /* empty */ }
  if (!res.ok) {
    const msg = (data && data.error) || `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return data;
}
function fmtPct(v) { return `${(v * 100).toFixed(1)}%`; }

/* ---------- tabs ---------- */
function switchTab(name) {
  document.querySelectorAll(".tab").forEach((b) =>
    b.classList.toggle("is-active", b.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((p) =>
    p.classList.toggle("is-active", p.id === `tab-${name}`));
}
document.querySelectorAll(".tab").forEach((b) =>
  b.addEventListener("click", () => switchTab(b.dataset.tab)));

/* ---------- status pill ---------- */
function setStatus(status, label) {
  const pill = $("status-pill");
  pill.textContent = label || status;
  const cls = { idle: "pill-idle", starting: "pill-running", running: "pill-running",
    evaluating: "pill-evaluating", done: "pill-done", error: "pill-error" };
  pill.className = `pill ${cls[status] || "pill-idle"}`;
  $("btn-cancel").classList.toggle("hidden",
    !["starting", "running", "evaluating"].includes(status));
  $("btn-start").disabled = ["starting", "running", "evaluating"].includes(status);
}

/* ---------- console ---------- */
function logLine(text, cls) {
  const con = $("console");
  const div = document.createElement("span");
  div.className = `ln ${cls || "ln-tail"}`;
  div.textContent = text;
  con.appendChild(div);
  con.scrollTop = con.scrollHeight;
}
function renderEvent(ev) {
  if (ev.type === "log") logLine(ev.message, "ln-tail");
  else if (ev.type === "status") {
    logLine(`—— ${ev.message || ev.phase} ——`, "ln-cmd");
    if (ev.phase) setStatus(ev.phase === "evaluating" ? "evaluating" :
      ["starting", "running"].includes(ev.phase) ? "running" : ev.phase);
  } else if (ev.type === "react") {
    if (ev.kind === "read") {
      logLine(`  [proposer] read ${ev.path} ${ev.found ? "" : "(MISSING)"}`, "ln-react");
    } else if (ev.kind === "proposal") {
      logLine(`  [proposer] → proposal ${ev.action} '${ev.skill}'`, "ln-react");
    } else {
      logLine(`  [proposer] ${esc(ev.kind)}`, "ln-react");
    }
  } else if (ev.type === "done") {
    S.lastResult = ev.result;
    setStatus("done", "done");
    if (ev.result) {
      showDashboard(ev.result.evolution);
      showEval(ev.result.evaluation);
      S.activeRoot = ev.result.workspace_root;
      $("log-root-label").textContent = `→ ${S.activeRoot}`;
    }
    logLine("✔ run finished", "ln-accept");
  } else if (ev.type === "error") {
    logLine(`✖ error: ${ev.error}`, "ln-reject");
    setStatus("error", "error");
  }
}

/* ---------- run form ---------- */
$("cfg-backend").addEventListener("change", () => {
  $("openai-fields").classList.toggle("hidden", $("cfg-backend").value !== "openai");
});
$("run-form").addEventListener("submit", async (e) => {
/* ---------- SSE ---------- */
let esSource = null;
function connectStream() {
  if (esSource) esSource.close();
  setStatus("running", "running…");
  esSource = new EventSource("/api/stream");
  esSource.onmessage = (m) => {
    let ev;
    try { ev = JSON.parse(m.data); } catch (_) { return; }
    renderEvent(ev);
    if (ev.type === "done" || ev.type === "error") esSource.close();
  };
  esSource.onerror = () => { if (esSource) esSource.close(); };
}

/* ---------- dashboard ---------- */
function showDashboard(evo) {
  $("dash-emptystate").classList.add("hidden");
  $("dash-charts").classList.remove("hidden");
  const history = evo.history || [];
  drawRbest(history);
  drawGate(history);
  const tbody = document.querySelector("#dash-table tbody");
  tbody.innerHTML = "";
  if (!history.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="muted">No proposals evaluated.</td></tr>';
    return;
  }
  for (const h of history) {
    const tr = document.createElement("tr");
    const outcome = h.accepted ? "accepted" : (h.proposal ? "rejected" : "none");
    tr.innerHTML = `<td>${h.iteration}</td><td>${esc(h.proposal || "—")}</td>
      <td>${esc(h.action || "—")}</td>
      <td>${h.val_score == null ? "—" : h.val_score.toFixed(4)}</td>
      <td><span class="badge ${outcome}">${outcome}</span></td>`;
    tbody.appendChild(tr);
  }
}
function drawRbest(history) {
  const svg = $("chart-rbest");
  // Reconstruct R_best trajectory: starts at baseline (0 by convention here, or the
  // first accepted score), then holds between accepted proposals.
  const accepted = history.filter((h) => h.accepted && h.val_score != null);
  const start = accepted.length ? firstVal(history) : 0;
  if (!accepted.length) {
    svg.innerHTML = `<text x="12" y="70" fill="#999">no accepted proposals (R_best = baseline)</text>`;
    return;
  }
  const pts = [{ lab: "base", v: start }];
  let cur = start;
  for (const h of history) {
    if (h.accepted) cur = h.val_score;
    pts.push({ lab: `k${h.iteration}`, v: cur });
  }
  renderLine(svg, pts);
}
function firstVal(history) {
  for (const h of history) if (h.accepted) return h.val_score;
  return 0;
}
function renderLine(svg, pts) {
  const W = 400, H = 180, pad = { l: 34, r: 10, t: 12, b: 24 };
  const minV = Math.min(...pts.map((p) => p.v), 0);
  const maxV = Math.max(...pts.map((p) => p.v), 1);
  const span = Math.max(0.2, maxV - minV);
  const x = (i) => pad.l + (i / Math.max(1, pts.length - 1)) * (W - pad.l - pad.r);
  const y = (v) => H - pad.b - ((v - minV) / span) * (H - pad.t - pad.b);
  let html = "";
  for (let g = 0; g <= 4; g++) {
    const gv = minV + (span * g) / 4;
    const gy = y(gv);
    html += `<line x1="${pad.l}" y1="${gy}" x2="${W - pad.r}" y2="${gy}" stroke="#efefea"/>`;
    html += `<text x="2" y="${gy + 3}" fill="#999">${gv.toFixed(2)}</text>`;
  }
  const px = pts.map((p, i) => `${x(i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  html += `<polyline points="${px}" fill="none" stroke="#3b5bdb" stroke-width="2"/>`;
  pts.forEach((p, i) => {
    html += `<circle cx="${x(i)}" cy="${y(p.v)}" r="3" fill="#3b5bdb">`;
    html += `<title>${p.lab}: ${p.v.toFixed(3)}</title></circle>`;
  });
  html += `<text x="${pad.l}" y="${H - 6}" fill="#999">baseline</text>`;
  svg.innerHTML = html;
}
function drawGate(history) {
  const svg = $("chart-gate");
  const W = 400, H = 180, pad = { l: 34, r: 10, t: 12, b: 24 };
  const vals = history.filter((h) => h.val_score != null);
  const maxV = Math.max(1, ...vals.map((v) => v.val_score));
  let html = "";
  for (let g = 0; g <= 4; g++) {
    const gy = H - pad.b - (g / 4) * (H - pad.t - pad.b);
    html += `<line x1="${pad.l}" y1="${gy}" x2="${W - pad.r}" y2="${gy}" stroke="#efefea"/>`;
  }
  if (!vals.length) {
    html += `<text x="${pad.l}" y="60" fill="#999">no proposals evaluated yet</text>`;
    svg.innerHTML = html; return;
  }
  const bw = Math.min(46, (W - pad.l - pad.r) / vals.length - 8);
  vals.forEach((h, i) => {
    const bh = (h.val_score / maxV) * (H - pad.t - pad.b);
    const bx = pad.l + i * ((W - pad.l - pad.r) / vals.length) + 4;
    const by = H - pad.b - bh;
    const color = h.accepted ? "#099268" : "#e03131";
    html += `<rect x="${bx}" y="${by}" width="${bw}" height="${Math.max(2, bh)}" fill="${color}">`;
    html += `<title>iter ${h.iteration}: ${h.val_score.toFixed(3)} ${h.accepted ? "accepted" : "rejected"}</title></rect>`;
    html += `<text x="${bx + bw / 2 - 8}" y="${H - 8}" fill="#999">k${h.iteration}</text>`;
  });
  svg.innerHTML = html;
}
  e.preventDefault();
  $("form-error").textContent = "";
  const cfg = {
    llm_backend: $("cfg-backend").value,
    iterations: parseInt($("cfg-iterations").value, 10),
    max_react_turns: parseInt($("cfg-react").value, 10),
    workspace_root: $("cfg-root").value.trim() || undefined,
  };
  if (cfg.llm_backend === "openai") {
    cfg.model = $("cfg-model").value.trim();
    cfg.base_url = $("cfg-base-url").value.trim() || undefined;
    cfg.api_key = $("cfg-api-key").value.trim() || undefined;
    cfg.temperature = parseFloat($("cfg-temperature").value);
  }
  try {
    await api("/api/run", { body: cfg });
    $("console").textContent = "";
    connectStream();
  } catch (err) {
/* ---------- evaluation ---------- */
function showEval(ev) {
  if (!ev) return;
  $("eval-emptystate").classList.add("hidden");
  $("eval-cards").classList.remove("hidden");
  $("eval-bars").classList.remove("hidden");
  $("eval-verdict").classList.remove("hidden");
  const sk = ev.skilled_accuracy, base = ev.baseline_accuracy;
  const d = sk - base;
  $("eval-cards").innerHTML = `
    <div class="kpi"><div class="v">${fmtPct(sk)}</div><div class="l">with evolved skills</div></div>
    <div class="kpi"><div class="v">${fmtPct(base)}</div><div class="l">no skills (baseline)</div></div>
    <div class="kpi"><div class="v">${d >= 0 ? "+" : ""}${fmtPct(d)}</div><div class="l">Δ</div></div>
    <div class="kpi"><div class="v">${ev.bootstrap_p_value.toFixed(4)}</div><div class="l">bootstrap p (1000)</div></div>`;
  const W = 420, H = 90;
  const maxV = Math.max(sk, base, 0.01);
  const bar = (label, v, color) => `
    <text x="4" y="26" fill="#666">${label}</text>
    <rect x="4" y="36" width="${Math.max(4, (v / maxV) * (W - 8))}" height="18" fill="${color}" rx="4">
      <title>${fmtPct(v)}</title></rect>
    <text x="6" y="76" fill="#444" font-size="11">${fmtPct(v)}</text>`;
  $("eval-bars").innerHTML = `
    <svg viewBox="0 0 430 92" class="chart">${bar("evolved skills", sk, "#099268")}
      ${bar("no-skill baseline", base, "#adb5bd")}</svg>`;
  const verdict = $("eval-verdict");
  if (ev.significant && d > 0) {
    verdict.className = "verdict ok";
    verdict.textContent = `✔ Evolved skills are significantly better than the no-skill baseline (p = ${ev.bootstrap_p_value.toFixed(4)} < 0.05).`;
  } else if (d < 0) {
    verdict.className = "verdict bad";
    verdict.textContent = `✖ Skills underperform the baseline on the test split.`;
  } else {
    verdict.className = "verdict neutral";
    verdict.textContent = `∽ No significant difference from the baseline (p = ${ev.bootstrap_p_value.toFixed(4)}).`;
  }
}
$("btn-evaluate").addEventListener("click", async () => {
  $("eval-error").textContent = "";
  const root = $("eval-root").value.trim() || S.activeRoot;
  if (!root) {
    $("eval-error").textContent = "No workspace yet — run an evolution first, or enter a root.";
    return;
  }
  const btn = $("btn-evaluate");
  btn.disabled = true; btn.textContent = "Evaluating…";
  try {
    $("eval-load-form").classList.remove("hidden");
    const res = await api("/api/evaluate", { body: { llm_backend: "mock",
      workspace_root: root, iterations: 3 } });
    showEval(res.evaluation);
    S.activeRoot = root;
  } catch (err) {
    $("eval-error").textContent = err.message;
  } finally {
    btn.disabled = false; btn.textContent = "Re-evaluate current workspace";
  }
});
$("btn-eval-load").addEventListener("click", async () => {
  const root = $("eval-root").value.trim();
  if (!root) { $("eval-error").textContent = "Enter a workspace root."; return; }
  try {
    const res = await api("/api/evaluate", { body: { llm_backend: "mock",
      workspace_root: root, iterations: 3 } });
    showEval(res.evaluation);
  } catch (err) { $("eval-error").textContent = err.message; }
});
/* ---------- workspace explorer ---------- */
async function loadWorkspace(root) {
  $("ws-error").textContent = "";
  try {
    const data = await api(`/api/workspace?root=${encodeURIComponent(root)}`);
    S.ws = data;
    S.activeRoot = root;
    $("ws-split").classList.remove("hidden");
    renderTree(data.tree);
    showFile("run_state.json");
    renderKnowledge(data.files);
    $("eval-root").value = root;
    $("ws-root").value = root;
  } catch (err) {
    $("ws-error").textContent = err.message;
  }
}
$("btn-ws-load").addEventListener("click", () =>
  loadWorkspace($("ws-root").value.trim()));
$("btn-ws-last").addEventListener("click", () => {
  if (S.activeRoot) { $("ws-root").value = S.activeRoot; loadWorkspace(S.activeRoot); }
  else $("ws-error").textContent = "No last run yet.";
});
function renderTree(node) {
  const ul = document.createElement("ul");
  node.children.forEach((ch) => ul.appendChild(renderNode(ch)));
  const tree = $("ws-tree");
  tree.innerHTML = "";
  tree.appendChild(ul);
}
function renderNode(node) {
  const li = document.createElement("li");
  if (node.type === "dir") {
    const label = document.createElement("span");
    label.className = "node-dir";
    label.innerHTML = `<span class="toggle">▾</span>📁 ${esc(node.name)}`;
    li.appendChild(label);
    const childUl = document.createElement("ul");
    node.children.forEach((ch) => childUl.appendChild(renderNode(ch)));
    li.appendChild(childUl);
    label.addEventListener("click", () => {
      childUl.classList.toggle("hidden");
      label.querySelector(".toggle").textContent =
        childUl.classList.contains("hidden") ? "▸" : "▾";
    });
  } else {
    const f = document.createElement("span");
    f.className = "node-file";
    const icon = node.name.endsWith(".json") ? "🧾" :
      (node.name.endsWith(".md") ? "📝" : "📄");
    f.innerHTML = `${icon} ${esc(node.name)}`;
    f.addEventListener("click", () => showFile(node.path));
    li.appendChild(f);
  }
  return li;
}
function showFile(path) {
  if (!S.ws || !S.ws.files[path]) { $("ws-content").textContent = "(not available)"; return; }
  $("ws-file-path").textContent = path;
  let content = S.ws.files[path];
  const mode = $("ws-view-mode").value;
  if (path.endsWith(".json") && (mode === "auto" || mode === "json")) {
    try { content = JSON.stringify(JSON.parse(content), null, 2); }
    catch (_) { /* keep raw */ }
  }
  $("ws-content").textContent = content;
}
$("ws-view-mode").addEventListener("change", () => {
  if (S.ws) showFile($("ws-file-path").textContent);
});

/* ---------- knowledge ---------- */
let ktab = "skills";
document.querySelectorAll(".ktab").forEach((b) =>
  b.addEventListener("click", () => {
    ktab = b.dataset.ktab;
    document.querySelectorAll(".ktab").forEach((x) =>
      x.classList.toggle("is-active", x === b));
    if (S.ws) renderKnowledge(S.ws.files);
  }));
function renderKnowledge(files) {
  if (!files) return;
  $("know-emptystate").classList.add("hidden");
  const out = $("know-content");
  if (ktab === "skills") {
    const names = Object.keys(files).filter((p) => p.endsWith("/SKILL.md"));
    if (!names.length) { out.innerHTML = '<p class="muted">No evolved skills in this workspace.</p>'; return; }
    out.innerHTML = "";
    names.forEach((skillPath) => {
      const purposePath = skillPath.replace("/SKILL.md", "/PURPOSE.md");
      const card = document.createElement("div");
      card.className = "skill-card";
      const name = skillPath.split("/")[1];
      card.innerHTML = `<h4>📦 ${esc(name)}</h4><h5>SKILL.md</h5>
        <pre>${esc(files[skillPath])}</pre><h5>PURPOSE.md</h5>
        <pre>${esc(files[purposePath] || "(none)")}</pre>`;
      out.appendChild(card);
    });
  } else {
    const map = {
      patterns: (p) => p.startsWith("wiki/patterns/"),
      index: (p) => p === "wiki/index.md",
      logs: (p) => p === "wiki/logs.md",
      impact: (p) => p === "wiki/skill-impact.md",
    };
    const keep = map[ktab];
    const paths = Object.keys(files).filter(keep).sort();
    if (!paths.length) { out.innerHTML = '<p class="muted">Nothing here yet.</p>'; return; }
    out.innerHTML = "";
    paths.forEach((p) => {
      const box = document.createElement("div");
      box.className = "kdoc";
      box.innerHTML = `<b>${esc(p)}</b>\n\n${esc(files[p])}`;
      out.appendChild(box);
    });
  }
}

/* ---------- restore state on load ---------- */
(async function init() {
  try {
    const st = await api("/api/status");
    const state = st.state;
    if (state) {
      (state.events || []).forEach(renderEvent);
      if (state.result) {
        S.lastResult = state.result;
        showDashboard(state.result.evolution);
        showEval(state.result.evaluation);
        S.activeRoot = state.result.workspace_root;
        $("log-root-label").textContent = `→ ${S.activeRoot}`;
        $("eval-root").value = S.activeRoot || "";
      }
      if (state.status === "done") setStatus("done", "done");
      if (st.active) connectStream();
    }
  } catch (_) { /* server unreachable; keep idle state */ }
})();
    $("form-error").textContent = err.message;
  }
});
$("btn-cancel").addEventListener("click", async () => {
  try { await api("/api/cancel", { body: {} }); logLine("—— cancel requested ——", "ln-cmd"); }
  catch (_) { /* ignore */ }
});