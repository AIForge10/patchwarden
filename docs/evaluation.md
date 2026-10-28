# Evaluation

Six controlled cases from plan section 12, run live on October 28, 2026. Every number below
comes from an executed run: `make evaluation` rebuilds [`evaluation.csv`](evaluation.csv) from
the run event log and the evidence manifests listed in [`evaluation/cases.json`](evaluation/cases.json).
Copies of those manifests are in [`evaluation/evidence/`](evaluation/evidence/); `evidence_hash`
is the SHA-256 of each file, so anyone can check them.

**Setup for every run:** model `nvidia/nemotron-3-super-120b-a12b` on Nebius Token Factory, a
fresh E2B sandbox with egress limited to PyPI, Tavily on, discovery on, at most 3 patch attempts
and 4 scenarios. Target: [`Satyabratadas/patchwarden-demo`](https://github.com/Satyabratadas/patchwarden-demo)
pinned at `1e83628` (seeded) or `d58b4df` (`known-good` branch, hidden defect fixed).

## Results

| Case | Alert / variant | Reproduced | Verified (attempts) | Second defect confirmed | False positives | PR |
|---|---|---|---|---|---|---|
| 01 malformed gateway response | demo-001 `ValidationError`, seeded | yes | yes (1) | yes: `retry_same_key`, reported unresolved | 0 | [#2](https://github.com/Satyabratadas/patchwarden-demo/pull/2) |
| 02 duplicate retry charge | demo-002, same crash, `--repair-discovery` | yes | yes (1) | yes: **repaired and re-verified** | 0 | [#3](https://github.com/Satyabratadas/patchwarden-demo/pull/3) |
| 03 unapproved payment completes order | demo-003 `AssertionError`, seeded | yes | yes (1) | yes, reported | 0 | [#4](https://github.com/Satyabratadas/patchwarden-demo/pull/4) |
| 04 unknown SKU (blind) | demo-004 `KeyError`, seeded | yes | yes (1) | yes, reported | 0 | [#5](https://github.com/Satyabratadas/patchwarden-demo/pull/5) |
| 05 gateway timeout (blind) | demo-005 `TimeoutError`, seeded | yes | yes (1) | yes, reported | 0 | [#6](https://github.com/Satyabratadas/patchwarden-demo/pull/6) |
| 06 known-good control | demo-006 `ValidationError`, `known-good` | yes | yes (1) | no (correct: there is none) | 0 | [#7](https://github.com/Satyabratadas/patchwarden-demo/pull/7) |

**Repeatability of the headline case.** Case 01 was run two more times on the same alert
(no PR): both verified on attempt 1 and both confirmed the hidden double charge
(`run-e06f338fd0a2`, `run-ec9b624590ab`). Case 01 overall: 3/3 verified, 3/3 discoveries.

**No cached replies.** The Nebius client has a local replay cache for identical prompts. During
these eight runs it wrote 25 new entries for 25 model requests (3 per run, plus 1 for case 02's
second repair), so every reply came from a live API call.

**In numbers (8 runs):** 8/8 reproduced, 8/8 primary fixes verified (all on attempt 1), PRs
opened for the 6 main cases. The hidden double charge was confirmed in 7/7 runs on the seeded
commit and repaired in 1/1 run that allowed it. 0 confirmed discoveries on the known-good
variant, and 0 false positives across all 8 runs (22 scenarios, each executed twice, with a
negative control for every repeated violation). Runs took 26–66 s end to end.

## What each case measures

- **01** The reported incident: red to green, original suite still green. Discovery runs with the
  default settings, so the second defect is reported, not repaired.
- **02** The same crash reported again, with the plan's P2 second repair loop on. The model's
  second patch (an idempotency check in `payments.py`) had to make the confirmed oracle hold
  while the incident reproducer and suite stayed green.
- **03** A logic bug, not a crash: the failing test names only itself, so context selection
  follows the test's imports to the code under test.
- **04, 05** Blind cases: written after the prompts were final, not used to tune anything.
- **06** Negative control at the plan level: the same incident on a commit without the hidden
  defect. Any confirmed discovery here would be a false positive.

`seeded` is true for every case because every variant contains at least the reported seeded
defect. `blind` is false for 03 because the context-import fallback was written after seeing
that its traceback names no source file.

## Observations

- **Every primary fix verified on the first attempt.** With the observed failure and the right
  source files, Super did not need verifier feedback on these small, single-cause bugs. The
  retry path is covered by tests (`tests/test_orchestrator.py`) but was not exercised live.
- **Case 03's fix is narrow.** The model special-cased the new `"review"` status
  (`if result.status == "review": ...`) instead of fixing the root cause
  (`if result.status != "approved"`). Every gate passed because the tests accept it. This is
  why PatchWarden opens a PR for human review instead of merging: passing tests are bounded
  evidence.
- **Scenario choice.** Given only the verified diff and the catalog IDs, the model included
  `retry_same_key` in all six runs. It proposed 2–3 scenarios per run and none was rejected by
  catalog validation.
- **Tavily hints were generic.** The query is the error type plus the alert message, so for
  `ValidationError: Unexpected payment response` the results were payment-provider error pages
  rather than pydantic docs. The fixes came from the observed failure and the source files.

## Limits

Six cases on one small seeded app, one run each, plus two repeats of case 01. The
reproducers ship with the target repo and each alert names one. This does not estimate how
PatchWarden would do on production incidents.

## Reproduce

```sh
export NEBIUS_NO_CACHE=1   # force live model calls
for n in 01 03 04 05 06; do make incident FIXTURE=demo_app/fixtures/incident_$n.json; done
python -m patchwarden.scripts.run_incident --fixture demo_app/fixtures/incident_02.json --repair-discovery
# put the new run IDs in docs/evaluation/cases.json, then:
make evaluation
```
