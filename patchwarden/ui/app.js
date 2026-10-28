// PatchWarden progress page. Owner: Satyabrata.
// Live:   /ui/?run=<run_id>                    polls the API's append-only event log
// Replay: /ui/?replay=recordings/<file>.json   plays a recorded run (patchwarden.scripts.record_run)
// Every status shown here comes from the run state or event log; nothing is inferred as green.

const PIPELINE = [
  "RECEIVED", "BASELINING", "DIAGNOSING", "PATCHING", "VERIFYING",
  "VERIFIED", "CHALLENGING", "PR_OPENED",
];
const STATUSES = new Set([...PIPELINE, "UNREPRODUCED", "CONFIRMED_DISCOVERY", "FAILED"]);
const FINAL = new Set(["FAILED", "UNREPRODUCED", "PR_OPENED"]);
const TONE = { PR_OPENED: "ok", VERIFIED: "ok", FAILED: "bad", UNREPRODUCED: "warn" };
const LIVE_POLL_MS = 1000;
const IDLE_POLL_MS = 4000; // VERIFIED may still be challenging or opening a PR

const $ = (id) => document.getElementById(id);
const state = { mode: "live", run: null, events: [], evidence: null, timer: null };

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "dataset") Object.assign(node.dataset, value);
    else node[key] = value;
  }
  for (const child of children) if (child != null) node.append(child); // text nodes: no HTML
  return node;
}

function safeLink(url, text) {
  return /^https:\/\//.test(url) ? el("a", { href: url, target: "_blank", rel: "noopener", textContent: text || url }) : text || url;
}

function showError(message) {
  $("error").textContent = message;
  $("error").hidden = !message;
}

async function getJSON(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${url}: ${response.status} ${response.statusText}`);
  return response.json();
}

// A VERIFIED run is finished when the PR step was disabled or GitHub failed.
function prOutcome() {
  for (const event of state.events) {
    const meta = event.metadata || {};
    if (meta.pr_step === "disabled") return "disabled";
    if (meta.failure_code === "GITHUB_ERROR") return "error";
  }
  return null;
}

// ---- Rendering --------------------------------------------------------------

function currentStatus() {
  if (state.mode === "live" && state.run) return state.run.status;
  // Replay: the latest state change played so far; the recorded final status at the end.
  const stages = state.events.map((e) => e.stage).filter((s) => STATUSES.has(s));
  if (state.done && state.run) return state.run.status;
  return stages.length ? stages[stages.length - 1] : "RECEIVED";
}

function renderPipeline(status) {
  const reached = new Set(state.events.map((e) => e.stage));
  if (state.events.length) reached.add("RECEIVED");
  const stopped = status === "FAILED" || status === "UNREPRODUCED";
  const last = PIPELINE.filter((s) => reached.has(s)).pop();
  const pr = prOutcome();
  const finished = FINAL.has(status) || state.done || (status === "VERIFIED" && pr !== null && Boolean((state.run || {}).evidence_path));
  $("pipeline").replaceChildren(...PIPELINE.map((stage) => {
    let mark = "todo";
    if (reached.has(stage)) mark = stage === last && !finished ? "current" : "done";
    if (stopped && stage === last) mark = "stopped";
    if (stage === "PR_OPENED" && status === "PR_OPENED") mark = "done";
    const label = stage === "PR_OPENED" && pr === "disabled" && status !== "PR_OPENED" ? "PR off on this host" : stage.replace("_", " ");
    if (label !== stage.replace("_", " ")) mark = "skipped";
    return el("li", { textContent: label, dataset: { state: mark } });
  }));
}

function renderTimeline(events, fresh = 0) {
  const start = events.length ? Date.parse(events[0].created_at) : 0;
  $("timeline").replaceChildren(...events.map((event, index) => {
    const seconds = Math.max(0, Math.round((Date.parse(event.created_at) - start) / 1000));
    const meta = Object.entries(event.metadata || {});
    const details = meta.length ? el("details", { className: "meta" },
      el("summary", { textContent: `${meta.length} detail${meta.length > 1 ? "s" : ""}` }),
      el("dl", { className: "kv" }, ...meta.flatMap(([key, value]) => [
        el("dt", { textContent: key }),
        el("dd", {}, key.endsWith("_url") ? safeLink(String(value)) : String(value)),
      ])),
    ) : null;
    const tone = event.severity === "error" ? "bad" : event.severity === "warning" ? "warn" : TONE[event.stage];
    return el("li", { className: index >= events.length - fresh ? "fresh" : "", dataset: { severity: event.severity } },
      el("span", { className: "when", textContent: `+${seconds}s` }),
      el("div", {},
        el("span", { className: "chip", textContent: event.stage, dataset: tone ? { tone } : {} }),
        el("p", { className: "message", textContent: event.message }),
        details,
      ),
    );
  }));
}

function check(label, value, note) {
  const [text, tone] = value === true ? ["yes", "ok"] : value === false ? ["no", "bad"] : [note || "not reached", ""];
  return el("div", { className: "check" }, el("span", { textContent: label }),
    el("span", { className: "chip", textContent: text, dataset: tone ? { tone } : {} }));
}

function renderEvidence(status) {
  const stages = new Set(state.events.map((e) => e.stage));
  const failures = state.events.filter((e) => e.metadata && e.metadata.failure_code);
  const failed = status === "FAILED" || status === "UNREPRODUCED";
  const gate = (stage) => (stages.has(stage) ? true : failed ? false : null);
  const run = state.run || {};
  const items = [
    check("Baseline red for the reported error", status === "UNREPRODUCED" ? false : gate("DIAGNOSING")),
    check("Patch verified by the independent verifier", gate("VERIFIED")),
    check("Evidence bundle written", run.evidence_path ? true : failed ? false : null),
    prOutcome() === "disabled" && status !== "PR_OPENED"
      ? check("Human-review PR opened", null, "off on this host")
      : check("Human-review PR opened", status === "PR_OPENED" && run.pr_url ? true : FINAL.has(status) || (state.done && status === "VERIFIED") || prOutcome() ? false : null),
  ];
  if (status === "PR_OPENED" && run.pr_url) items.push(safeLinkBlock(run.pr_url));
  const evidence = state.evidence;
  if (evidence) {
    const kv = [
      ["baseline_sha", evidence.baseline_sha],
      ["patch_sha256", evidence.patch_sha256],
      ["protected files", Object.keys(evidence.protected_test_sha256 || {}).length],
      ["model", evidence.model_id],
      ["verified_at", evidence.verified_at],
    ];
    if (evidence.sandbox) kv.push(["sandbox", [evidence.sandbox.backend, evidence.sandbox.sandbox_id].filter(Boolean).join(" ")]);
    const discovery = evidence.discovery;
    if (discovery) {
      const controls = Object.entries(discovery.negative_controls || {}).map(([id, clean]) => `${id}: ${clean ? "clean" : "also failed"}`);
      kv.push(
        ["scenarios run", discovery.scenarios_run],
        ["second defect", (discovery.confirmed || []).join(", ") || "none confirmed"],
        ["negative control", controls.join(", ") || undefined],
        ["repaired", (discovery.repaired || []).join(", ") || undefined],
      );
    }
    items.push(el("dl", { className: "kv" }, ...kv.filter(([, v]) => v !== undefined && v !== "").flatMap(([k, v]) => [el("dt", { textContent: k }), el("dd", { textContent: String(v) })])));
    const sources = (evidence.tavily_sources || []).filter((item) => /^https:\/\//.test(item.url || ""));
    if (sources.length) {
      items.push(el("p", { className: "evidence-note", textContent: "Tavily sources consulted (untrusted hints):" }));
      items.push(el("ul", { className: "sources" }, ...sources.map((item) => el("li", {}, safeLink(item.url, item.title || item.url)))));
    }
    if (state.mode === "live") items.push(el("p", { className: "evidence-note" }, el("a", { href: `/runs/${encodeURIComponent(run.run_id)}/evidence`, target: "_blank", textContent: "Full evidence manifest (JSON)" })));
  }
  for (const event of failures) {
    items.push(el("p", { className: "evidence-note" }, el("span", { className: "chip", dataset: { tone: event.severity === "error" ? "bad" : "warn" }, textContent: event.metadata.failure_code }), " ", event.message));
  }
  items.push(el("p", { className: "evidence-note", textContent: "Passing tests are bounded evidence, not proof. PatchWarden never merges or deploys." }));
  $("evidence").replaceChildren(...items);
}

function renderPatch() {
  const diff = state.evidence && state.evidence.patch;
  $("patch-panel").hidden = !diff;
  if (!diff) return;
  const files = (diff.match(/^\+\+\+ b\/(.+)$/gm) || []).map((line) => line.slice(6));
  $("patch-note").textContent = `Applied by trusted code to a fresh pinned checkout, then verified. Files: ${files.join(", ")}. SHA-256 ${state.evidence.patch_sha256}.`;
  $("patch").replaceChildren(...diff.replace(/\n+$/, "").split("\n").map((line) => {
    const kind = line.startsWith("+++") || line.startsWith("---") ? "file" : line.startsWith("@@") ? "hunk" : line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : "";
    return el("span", { className: kind, textContent: line || " " });
  }));
}

function safeLinkBlock(url) {
  return /^https:\/\//.test(url) ? el("a", { className: "pr-link", href: url, target: "_blank", rel: "noopener", textContent: `Review PR: ${url}` }) : null;
}

function render(fresh = 0) {
  const status = currentStatus();
  const run = state.run || {};
  $("run-title").textContent = run.run_id || "";
  $("incident-line").textContent = run.incident_id ? `Incident ${run.incident_id}` : "";
  $("mode-label").textContent = state.mode === "replay" ? (state.done ? "Recorded run (replay finished)" : "Recorded run (replaying)") : "Live run";
  $("status").textContent = status.replace("_", " ");
  $("status").dataset.tone = TONE[status] || "pending";
  renderPipeline(status);
  renderTimeline(state.events, fresh);
  renderEvidence(status);
  renderPatch();
  document.title = `${status} · ${run.run_id || "PatchWarden"}`;
}

// ---- Live mode --------------------------------------------------------------

async function loadRun(runId) {
  clearTimeout(state.timer);
  Object.assign(state, { mode: "live", run: null, events: [], evidence: null, done: false });
  $("home").hidden = true;
  $("run").hidden = false;
  const id = encodeURIComponent(runId);
  const poll = async () => {
    try {
      const seq = state.events.length ? state.events[state.events.length - 1].seq : 0;
      const [run, fresh] = await Promise.all([getJSON(`/runs/${id}`), getJSON(`/runs/${id}/events?after=${seq}`)]);
      state.run = run;
      state.events.push(...fresh);
      if (run.evidence_path && !state.evidence) state.evidence = await getJSON(`/runs/${id}/evidence`).catch(() => null);
      showError("");
      render(fresh.length);
      if (FINAL.has(run.status) || (run.status === "VERIFIED" && run.evidence_path && prOutcome())) return;
      state.timer = setTimeout(poll, run.status === "VERIFIED" ? IDLE_POLL_MS : LIVE_POLL_MS);
    } catch (error) {
      showError(`Could not load run: ${error.message}`);
      state.timer = setTimeout(poll, IDLE_POLL_MS);
    }
  };
  await poll();
}

// ---- Replay mode ------------------------------------------------------------

function playRecording(recording, speed = 1) {
  clearTimeout(state.timer);
  if (!recording || !Array.isArray(recording.events) || !recording.run) {
    showError("Not a PatchWarden recording (expected run + events).");
    return;
  }
  Object.assign(state, { mode: "replay", run: recording.run, events: [], evidence: null, done: false });
  $("home").hidden = true;
  $("run").hidden = false;
  showError("");
  const queue = recording.events.slice();
  const step = () => {
    const event = queue.shift();
    if (!event) {
      state.done = true;
      state.evidence = recording.evidence || null;
      render();
      return;
    }
    state.events.push(event);
    render(1);
    const next = queue[0];
    // Real gaps, compressed: long sandbox / model waits play in at most 1.6 s.
    const gap = next ? Date.parse(next.created_at) - Date.parse(event.created_at) : 600;
    state.timer = setTimeout(step, Math.min(Math.max(gap, 300), 1600) / speed);
  };
  render();
  state.timer = setTimeout(step, 400 / speed);
}

// ---- Home -------------------------------------------------------------------

async function startLive(caseId, button) {
  button.disabled = true;
  button.textContent = "Starting…";
  try {
    const response = await fetch("/demo/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ case: caseId }),
    });
    const busy = response.headers.get("X-Run-Id");
    if (response.status === 409 && busy) {
      location.search = `?run=${encodeURIComponent(busy)}`;
      return;
    }
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `${response.status} ${response.statusText}`);
    location.search = `?run=${encodeURIComponent(body.run_id)}`;
  } catch (error) {
    showError(`Could not start a live run: ${error.message}`);
    button.disabled = false;
    button.textContent = "Run live";
  }
}

async function loadLive() {
  let demo;
  try {
    demo = await getJSON("/demo");
  } catch {
    return; // static hosting without the API: recordings only
  }
  $("live-panel").hidden = false;
  const busy = demo.busy_run;
  const note = demo.enabled
    ? `Each run checks out the pinned demo commit in a fresh E2B sandbox and calls the model live (about a minute). One run at a time; ${demo.remaining_today} left today. Pull requests are off for public runs.`
    : demo.reason;
  $("live-note").replaceChildren(note, busy ? el("span", {}, " A run is in progress: ", el("a", { href: `?run=${encodeURIComponent(busy)}`, textContent: "watch it" }), ".") : "");
  $("cases").replaceChildren(...demo.cases.map((item) => {
    const button = el("button", { type: "button", className: "run-live", textContent: "Run live", disabled: !demo.enabled || Boolean(busy) || demo.remaining_today <= 0 });
    button.addEventListener("click", () => startLive(item.case, button));
    return el("li", {},
      el("span", { className: "case-id", textContent: item.case }),
      el("div", { className: "case-body" },
        el("strong", { textContent: item.title }),
        el("div", { className: "muted small" },
          el("span", { className: "chip", textContent: item.error_type }), " ",
          `${item.incident_id} @ ${item.commit_sha.slice(0, 7)}`,
          item.repair_discovery ? " · second repair on" : ""),
      ),
      button,
    );
  }));
}

async function loadHome() {
  $("home").hidden = false;
  $("run").hidden = true;
  loadLive();
  try {
    const runs = await getJSON("/runs");
    $("recent").replaceChildren(...(runs.length ? runs.map((run) => el("li", {},
      el("a", { href: `?run=${encodeURIComponent(run.run_id)}`, textContent: run.run_id }),
      el("span", { className: "muted", textContent: run.incident_id }),
      el("span", { className: "chip", textContent: run.status, dataset: TONE[run.status] ? { tone: TONE[run.status] } : {} }),
    )) : [el("li", { className: "muted", textContent: "No runs on this server yet." })]));
  } catch (error) {
    $("recent").replaceChildren(el("li", { className: "muted", textContent: `API unavailable (${error.message}). Recordings still play.` }));
  }
  try {
    const recordings = await getJSON("recordings/index.json");
    $("recordings").replaceChildren(...recordings.map((r) => el("li", {},
      el("a", { href: `?replay=${encodeURIComponent(`recordings/${r.file}`)}`, textContent: r.label || r.run_id }),
      el("span", { className: "muted", textContent: r.label ? `${r.run_id} · ${r.incident_id}` : r.incident_id }),
      el("span", { className: "chip", textContent: r.status, dataset: TONE[r.status] ? { tone: TONE[r.status] } : {} }),
    )));
  } catch {
    $("recordings").replaceChildren(el("li", { className: "muted", textContent: "No recordings. Export one with: python -m patchwarden.scripts.record_run <run_id>" }));
  }
}

// ---- Wiring -----------------------------------------------------------------

$("open-run").addEventListener("submit", (event) => {
  event.preventDefault();
  const runId = $("run-id").value.trim();
  if (runId) location.search = `?run=${encodeURIComponent(runId)}`;
});

$("recording-file").addEventListener("change", async (event) => {
  const [file] = event.target.files;
  if (!file) return;
  try {
    playRecording(JSON.parse(await file.text()));
  } catch (error) {
    showError(`Could not read recording: ${error.message}`);
  }
});

const params = new URLSearchParams(location.search);
const speed = Number(params.get("speed")) || 1;
if (params.get("replay")) {
  const path = params.get("replay");
  // Same-origin relative paths only: a recording is data, never fetched from elsewhere.
  if (/^\w[\w./-]*\.json$/.test(path) && !path.includes("..")) {
    getJSON(path).then((recording) => playRecording(recording, speed)).catch((error) => showError(error.message));
  } else {
    showError("Recordings must be a relative .json path.");
  }
} else if (params.get("run")) {
  $("run-id").value = params.get("run");
  loadRun(params.get("run"));
} else {
  loadHome();
}
