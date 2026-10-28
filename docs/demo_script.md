# Three-minute demo storyboard

Disclosure, spoken once: this controlled checkout app contains seeded defects.
PatchWarden receives the first incident. The second defect is not in the agent
prompt. Every claim is checked against prewritten tests and invariants.

## 0:00–0:20 — Signed alert

Show the checkout crash (`demo_app/tests/test_incident.py` is red on the pinned
baseline). Start the API and send the signed alert:

```sh
make run
python -m patchwarden.scripts.send_demo_alert --fixture demo_app/fixtures/incident_01.json
```

Open `/ui/?run=<run_id>`. Takeaway: a real signed trigger, not a manual prompt.

## 0:20–0:55 — Red baseline, then diagnosis

The timeline reaches BASELINING then DIAGNOSING. The reproducer failed for the
reported error; the original suite stayed green. Diagnosis cites file/line
evidence from the observed output, not the alert's own traceback.

## 0:55–1:35 — Patch and independent verifier

PATCHING → VERIFYING. The model never grades its own work: a fresh pinned
checkout, the patch applied by trusted code, then reproducer green, suite green,
protected hashes unchanged. If an attempt regresses, that verifier output is the
next attempt's feedback (max three).

## 1:35–2:15 — Scenario challenge (experimental)

CHALLENGING. The model may only pick catalog IDs and bounded parameters. Trusted
code runs each scenario twice. A confirmed second defect is labeled **unresolved**
and is not repaired in this PR. If discovery is noisy, say so and spend the time
on red/green verification.

## 2:15–2:40 — Evidence and human-review PR

Evidence JSON plus a GitHub PR on the pinned SHA. No merge, no deploy. The PR
body includes residual risks and Tavily sources actually consulted (or none).

## 2:40–3:00 — Results and limits

Point at `docs/evaluation.csv` (executed runs only) and the limitations: seeded
demo, bounded tests, no production claims.

## Offline fallback

If the live model or GitHub is unavailable, replay a stored run. The committed
recording is a harness replay (same gates, fake model) so the UI still has
something to play; the judged demo should be a live `make incident` run.

```sh
make run
# then open http://127.0.0.1:8000/ui/?replay=recordings/run-315b1e960373.json
```

Or `make record RUN=<run_id>` after any finished local run.
