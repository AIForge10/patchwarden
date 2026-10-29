# Three-minute demo storyboard

One continuous live run is the spine of the video: hosted **Run live** on **case 07** (no
reproducer attached). It shows every step, from a stack trace to a real PR, in about a minute.
Record that run once, then cut to the replays below only for the two moments a single run may
not hit (a verifier rejection and model escalation).

Disclosure, spoken once: this controlled checkout app contains seeded defects. The second defect
is not in any alert, test or prompt. Every claim is checked by trusted code, never by the model.

Name the stack on screen once: NVIDIA Nemotron 3 (Nano, Super, Ultra) on Nebius Token Factory,
Tavily for docs, E2B for the sandbox, GitHub for the PR.

## Before recording

- Hosted env (Northflank) has `PUBLIC_DEMO_OPEN_PRS=true`, `OPEN_PR_ON_VERIFIED=true`, the GitHub
  token, and `NEBIUS_PATCH_MODELS` (Nano, Super, Ultra). `/health` shows them.
- Open three tabs: the hosted UI, the E2B dashboard (Sandboxes list), and
  https://github.com/Satyabratadas/patchwarden-demo/pulls.

## 0:00–0:15 — The problem

"At 3 a.m. an AI agent can write a fix in seconds, but nobody can trust it: it may fix the
symptom, break something else, or quietly edit the test. PatchWarden ships a fix only after it
proves it."

## 0:15–0:40 — Alert in, sandbox up, the agent writes the failing test

Press **Run live** on 07. Point out:
- "Sandbox ready: e2b". Switch to the E2B dashboard: the same sandbox ID is running right now.
  Its network reaches only PyPI.
- "No reproducer shipped with the alert: Nemotron is writing one from the stack trace", then
  "Model-written reproducer accepted: fails with ValidationError at demo_app/app/main.py:14, the
  line the alert names (1 failed in 0.2s)". Say: "the model wrote the test, but trusted code
  accepted it only because it crashed at the exact line production reported."
- The **Reproducer written by the model** panel shows the test.

## 0:40–1:15 — Diagnose, patch, verify

- "Baseline red … (reproducer: 1 failed); suite green (3 passed)": real pytest output from E2B.
- Tavily sources consulted, then the Nemotron diagnosis citing `main.py:14`.
- "Attempt 1 of 3: requesting a patch from Nemotron Nano". If the verifier rejects it, the next
  line says why and "escalating to Super". If not, cut to the ladder replay
  (`?replay=recordings/run-6f018665190c.json`) for 5 seconds: "a rejected patch is the only thing
  that moves the run to a bigger model."
- "Reproducer green (1 passed), original suite green (3 passed), protected files unchanged". Show
  the **Verified patch** diff.

## 1:15–1:55 — The wow: a bug nobody reported

CHALLENGING. The model may only pick catalog scenarios. It picks `retry_same_key`. Trusted code
runs it twice (two charges for one idempotency key), then swaps in the known-good gateway where it
holds: **"Confirmed a second defect: retry_same_key"**. Say: "no alert, test or prompt mentioned
this double charge. It found it, and a negative control stopped it from crying wolf."

## 1:55–2:30 — The real PR

The run ends with "Opened human-review PR …". Click it. On GitHub show: the fix and the new
regression test in **Files changed**, the reproduced failing test section, the confirmed second
defect, residual risks, Tavily sources, and the evidence manifest. "It never merges; a human
reviews."

## 2:30–3:00 — Results and limits

Show the tables in `docs/evaluation.md`: six cases plus three stack-trace-only alerts, three
Nemotron models and the ladder, every number rebuilt from evidence files, 0 false positives.
Limits in one breath: seeded demo app, logic bugs still need a shipped test, passing tests are
evidence not proof, never merges.

## Fallbacks

If a live run is slow or a service is down, use the recorded runs (real model, real E2B):

- `?replay=recordings/run-376fefbdfc1a.json`: headline signed alert to PR #8
- `?replay=recordings/run-4e9997e40534.json`: no reproducer attached; Nemotron writes the test
- `?replay=recordings/run-6f018665190c.json`: verifier rejects Nano's patch, escalates to Super

Locally, the signed-webhook path with PRs on:

```sh
make run
python -m patchwarden.scripts.send_demo_alert --fixture demo_app/fixtures/incident_07.json
# open http://127.0.0.1:8000/ui/?run=<run_id>
```
