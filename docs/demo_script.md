# Three-minute demo storyboard

Disclosure, spoken once: this controlled checkout app contains seeded defects.
PatchWarden receives the first incident. The second defect is not in the agent
prompt. Every claim is checked against prewritten tests and invariants.

Name the stack on screen once: Nemotron 3 Super on Nebius Token Factory, Tavily
for docs, E2B for the sandbox, GitHub for the PR.

## 0:00–0:20 — Signed alert

Show the checkout crash (`demo_app/tests/test_incident.py` is red on the pinned
baseline). Start the API and send the signed alert:

```sh
make run
python -m patchwarden.scripts.send_demo_alert --fixture demo_app/fixtures/incident_01.json
```

Open `/ui/?run=<run_id>`. Takeaway: a real signed trigger, not a manual prompt.

## 0:20–0:55 — Red baseline, then diagnosis

The timeline reaches BASELINING ("Sandbox ready: e2b") then DIAGNOSING. The
reproducer failed for the reported error inside the E2B sandbox, whose network
reaches only PyPI; the original suite stayed green. Diagnosis cites file/line
evidence from the observed output, not the alert's own traceback, plus the
Tavily sources it consulted.

## 0:55–1:35 — Patch and independent verifier

PATCHING → VERIFYING. The model never grades its own work: a fresh pinned
checkout, the patch applied by trusted code, then reproducer green, suite green,
protected hashes unchanged. If an attempt regresses, that verifier output is the
next attempt's feedback (max three).

## 1:35–2:15 — Scenario challenge (experimental)

CHALLENGING. The model may only pick catalog IDs and bounded parameters. It was
never told about a second bug, yet it picks `retry_same_key`. Trusted code runs
the scenario twice (2 charges for one idempotency key, both times), then swaps in
the known-good control gateway, where it holds (1 charge). Only then is it
CONFIRMED_DISCOVERY. In the headline run the defect is reported as
**unresolved**; mention that case 02 (`--repair-discovery`) also repaired and
re-verified it (PR #3 on the demo repo).

## 2:15–2:40 — Evidence and human-review PR

Evidence JSON plus a GitHub PR on the pinned SHA. No merge, no deploy. The PR
body includes residual risks and Tavily sources actually consulted (or none).

## 2:40–3:00 — Results and limits

Point at `docs/evaluation.md`: six cases, one executed run each, every number
rebuilt from the evidence files. Then the limits: seeded demo, reproducers ship
with the repo, bounded tests, no production claims, never merges.

## Offline fallback

If the live model or GitHub is unavailable, replay the recorded headline run
(a real live run: real model, real E2B sandbox, real PR). It is also on the
hosted demo.

```sh
make run
# then open http://127.0.0.1:8000/ui/?replay=recordings/run-376fefbdfc1a.json
# (signed alert demo-001 -> PR #8 on the demo repo; also on the hosted demo)
```

Or `make record RUN=<run_id>` after any finished local run.
