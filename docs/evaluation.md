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

## Same six cases on other Nemotron models

On October 29 the six cases were run again with only `NEBIUS_MODEL_REASONING` changed, once on
`nvidia/Nemotron-3-Ultra-550b-a55b` and once on `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`
(no PRs; same seeded and known-good commits, same E2B, Tavily and gates). Super stays the
default. [`evaluation_models.csv`](evaluation_models.csv) is built the same way from
[`evaluation/models.json`](evaluation/models.json) and includes the Super rows above.

| Model | Verified | Attempts | Hidden double charge (seeded, 5 cases) | Repaired (case 02) | Known-good control | False positives |
|---|---|---|---|---|---|---|
| Nemotron 3 Super (120B) | 6/6 | all 1 | 5/5 | yes | none claimed | 0 |
| Nemotron 3 Ultra (550B) | 6/6 | all 1 | 4/5 | yes | none claimed | 0 |
| Nemotron 3 Nano (30B) | 6/6 | 1 or 2 | 4/5 | no (not found) | none claimed | 0 |

- **Every model got every incident verified.** The gates do not depend on which model writes the
  patch: the trusted reproducer, suite and hash checks decide.
- **Nano used the retry loop.** In cases 01 and 04 its first patch failed verification; the
  failure was fed back and its second patch verified. This is the first live use of the retry
  path (Super and Ultra never needed it).
- **Missed discoveries were safe misses.** Ultra's scenario reply for case 03 contained no
  usable catalog entry, so no scenario ran. Nano's case 02 proposals paired each scenario with
  an invariant the catalog does not approve for it; catalog validation rejected all three, so
  nothing ran and nothing was claimed. In both runs the verified incident fix still stood.
- **No false positives on any model.** On the known-good commit, all three models ran
  `retry_same_key` and the invariant held.
- Timings are not comparable across days: the Super runs also opened PRs.

Replay cache: cases 02 and 06 send the same prompts as case 01 (same alert text and reproducer,
and the known-good commit differs only in `payments.py`), so the first Ultra and Nano runs of
those two cases could have reused case 01's cached replies. They were discarded and rerun with
`NEBIUS_NO_CACHE=1`; the table uses only the rerun results. Cases 01, 03, 04 and 05 were the first request
of their prompts for each model.

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
  retry path is covered by tests (`tests/test_orchestrator.py`); live, only Nano used it (see
  the model comparison above).
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
  After this evaluation the query was changed to come from the observed failure
  (`agent/research.build_search_query`): for case 01 it is now
  `python pydantic ValidationError model_validate Field required`, which returns the Pydantic
  "Validation Errors" and "Error Handling" docs. The runs above used the old query.

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

# another model, no PRs (repeat for each fixture; add --repair-discovery for case 02):
NEBIUS_MODEL_REASONING=nvidia/Nemotron-3-Ultra-550b-a55b \
  python -m patchwarden.scripts.run_incident --fixture demo_app/fixtures/incident_01.json --no-pr
# put the run IDs in docs/evaluation/models.json, then make evaluation
```
