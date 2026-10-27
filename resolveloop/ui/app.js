// ResolveLoop progress page. Owner: Satyabrata.
// Live:   /ui/?run=<run_id>                    polls the API's append-only event log
// Replay: /ui/?replay=recordings/<file>.json   plays a recorded run (resolveloop.scripts.record_run)
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
  $("pipeline").replaceChildren(...PIPELINE.map((stage) => {
    let mark = "todo";
    if (reached.has(stage)) mark = stage === last && !FINAL.has(status) ? "current" : "done";
    if (stopped && stage === last) mark = "stopped";
    if (stage === "PR_OPENED" && status === "PR_OPENED") mark = "done";
    return el("li", { textContent: stage.replace("_", " "), dataset: { state: mark } });
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

function check(label, value) {
  const [text, tone] = value === true ? ["yes", "ok"] : value === false ? ["no", "bad"] : ["not reached", ""];
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
    check("Human-review PR opened", status === "PR_OPENED" && run.pr_url ? true : FINAL.has(status) || (state.done && status === "VERIFIED") ? false : null),
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
    if (evidence.discovery) kv.push(["scenarios run", evidence.discovery.scenarios_run], ["confirmed", (evidence.discovery.confirmed || []).join(", ") || "none"]);
    items.push(el("dl", { className: "kv" }, ...kv.filter(([, v]) => v !== undefined && v !== "").flatMap(([k, v]) => [el("dt", { textContent: k }), el("dd", { textContent: String(v) })])));
    if (state.mode === "live") items.push(el("p", { className: "evidence-note" }, el("a", { href: `/runs/${encodeURIComponent(run.run_id)}/evidence`, target: "_blank", textContent: "Full evidence manifest (JSON)" })));
  }
  for (const event of failures) {
    items.push(el("p", { className: "evidence-note" }, el("span", { className: "chip", dataset: { tone: event.severity === "error" ? "bad" : "warn" }, textContent: event.metadata.failure_code }), " ", event.message));
  }
  items.push(el("p", { className: "evidence-note", textContent: "Passing tests are bounded evidence, not proof. ResolveLoop never merges or deploys." }));
  $("evidence").replaceChildren(...items);
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
  document.title = `${status} · ${run.run_id || "ResolveLoop"}`;
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
      if (FINAL.has(run.status)) return;
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
    showError("Not a ResolveLoop recording (expected run + events).");
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

async function loadHome() {
  $("home").hidden = false;
  $("run").hidden = true;
  try {
    const runs = await getJSON("/runs");
    $("recent").replaceChildren(...(runs.length ? runs.map((run) => el("li", {},
      el("a", { href: `?run=${encodeURIComponent(run.run_id)}`, textContent: run.run_id }),
      el("span", { className: "muted", textContent: run.incident_id }),
      el("span", { className: "chip", textContent: run.status, dataset: TONE[run.status] ? { tone: TONE[run.status] } : {} }),
    )) : [el("li", { className: "muted", textContent: "No runs yet. Send a signed alert to start one." })]));
  } catch (error) {
    $("recent").replaceChildren(el("li", { className: "muted", textContent: `API unavailable (${error.message}). Recordings still play.` }));
  }
  try {
    const recordings = await getJSON("recordings/index.json");
    $("recordings").replaceChildren(...recordings.map((r) => el("li", {},
      el("a", { href: `?replay=${encodeURIComponent(`recordings/${r.file}`)}`, textContent: r.run_id }),
      el("span", { className: "muted", textContent: r.incident_id }),
      el("span", { className: "chip", textContent: r.status, dataset: TONE[r.status] ? { tone: TONE[r.status] } : {} }),
    )));
  } catch {
    $("recordings").replaceChildren(el("li", { className: "muted", textContent: "No recordings. Export one with: python -m resolveloop.scripts.record_run <run_id>" }));
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
