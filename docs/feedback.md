# Feedback log: Nebius Token Factory and NVIDIA Nemotron

Running notes from building PatchWarden. Facts only: what we ran and what happened.

## Oct 11: first day-one test (Nemotron 3 Ultra)

- Model: `nvidia/Nemotron-3-Ultra-550b-a55b`, base URL `https://api.tokenfactory.nebius.com/v1/`.
- Result: 0 of 6 runs fixed, but **this was our harness, not the model**:
  - Ultra writes long step-by-step reasoning into the reply text. With `max_tokens=1500`, 2 of 3 code-visible replies were cut off before the final code block.
  - In 1 run the model quoted the original code before its answer; our script took the first code block (the unchanged code) instead of the last.
- Fixes made: `max_tokens` raised to 8000, script takes the last code block and prints `finish_reason`.
- Feedback: on Ultra, the reasoning arrives in the normal reply text, so it costs output tokens and needs a large `max_tokens`. Worth checking whether a setting turns visible reasoning off or returns it in a separate field.

## Setup notes (Oct 10 to 21)

- `NEBIUS_MODEL_ID` (from an early plan draft) vs `NEBIUS_MODEL_REASONING` (what `config.py` reads) caused an `AttributeError`. One variable name everywhere avoids this.
- `models.list()` worked first time and is the easiest way to get exact model IDs. IDs are case-sensitive and mix styles (`Nemotron-3-Ultra-550b-a55b` vs `nemotron-3-super-120b-a12b`).
- Moving from a flat layout to the `patchwarden/` package meant every import had to change (`from patchwarden import config`). Running tests as `python -m pytest` avoids needing extra path config.

## Oct 21: day-one rerun (Nemotron 3 Super)

- Model: `nvidia/nemotron-3-super-120b-a12b` (used for development to save credits).
- Task: fix a `KeyError` on a malformed payment response; 2 tests, 1 failing. The fixed file is checked by running both tests.

| Mode | Run 1 | Run 2 | Run 3 | Fixed |
|---|---|---|---|---|
| Code visible (trace + source file) | FIXED | FIXED | FIXED | 3 / 3 |
| Trace only (no source file) | NOT FIXED | NOT FIXED | NOT FIXED | 0 / 3 |

- All 6 replies finished normally (`finish_reason: stop`), and Super's replies contained only the code block, with no long visible reasoning.
- Code visible: all 3 fixes wrapped the call in `try/except KeyError` and returned `"status": "failed"`. That is a small, correct change.
- Trace only: the model fixed the crash line correctly (`.get("data", {})`) but had to guess the rest of the file. It invented a `mark_order_completed()` function that does not exist and changed what `checkout()` returns, which broke the passing test.

### What this means for PatchWarden

- The model must always see the source files the traceback names. The context step (`patchwarden/agent/context.py`) already reads them before every patch request.
- Never trust a fix from the trace alone: the trace-only runs passed the original failing case but broke other behavior. This is why the verifier runs the full test suite, not just the reproducer.

## Oct 21: agent client check (A2 + A3)

- `healthcheck_model()` confirmed both configured models are available to our key.
- Diagnosis prompt returned the required format: `EVIDENCE: buggy_checkout.py:6 ...`, a correct hypothesis, and `UNCERTAINTY: medium`.
- Patch call cost 733 input and 572 output tokens on Super. A repeated identical call was served from our local replay cache with no API request.

## Oct 28: live runs on Nemotron 3 Super, E2B and Tavily

- First live end-to-end run (`run-59eab39b679d`): `ValidationError` fixed on attempt 1 of 3 in
  24 s, human-review PR opened on the demo repo. Per-case results for the six-case evaluation are
  in `docs/evaluation.md`, built from the evidence files rather than typed in.
- Nemotron 3 Super, given the observed red test output plus the source files that output names,
  returned a minimal whole-file fix with `finish_reason: stop`; no visible reasoning text.
- Scenario selection: given only the verified diff and the catalog IDs, Super picked
  `retry_same_key` among its scenarios, which is the one that exposes the hidden double charge.
  It was never told that defect exists.
- `nvidia/Nemotron-3-Ultra-550b-a55b` is now listed by `models.list()` for our key (it was not
  selectable in the console earlier). We kept Super for every recorded run so results stay
  comparable.
- Tavily: `search` returned three HTTPS results with titles and URLs for a pydantic
  `ValidationError` query. The results are passed to the model as untrusted hints and cited in
  the PR.
- E2B (not Nebius, but part of the stack): a sandbox starts in about 0.5 s; installing four pinned
  packages takes about 5 s. `network={"allow_out": [PyPI hosts], "deny_out": ["0.0.0.0/0"]}`
  blocked GitHub, Nebius and the open internet from inside the sandbox, which let us run
  model-written code with no route to any key.

## Oct 29: same six cases on Ultra and Nano

- Swapping models was one environment variable (`NEBIUS_MODEL_REASONING`); the OpenAI-compatible
  API, prompts and parsing worked unchanged for `nvidia/Nemotron-3-Ultra-550b-a55b` and
  `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`.
- Both verified all six incidents. Ultra fixed every one on attempt 1; Nano needed a second
  attempt in two cases and fixed them after seeing the verifier's failure. Full table in
  `docs/evaluation.md`.
- Ultra no longer put long visible reasoning in the reply (compare Oct 11): a probe reply ended
  with `finish_reason: stop` in 76 tokens, and every Ultra patch reply in the six runs was usable
  on the first attempt with no harness change.
- Structured output was the main gap between sizes: Nano once paired each challenge scenario with
  an invariant the catalog does not allow, and Ultra once returned no usable scenario list. Our
  validator rejected both safely. A JSON-schema or constrained-output option on Token Factory
  would make this reliable for agent loops.

### Suggestions for Token Factory

- An explicit way to switch visible reasoning off (or return it in a separate field) on Ultra would
  save output tokens for agent loops that only need the final answer.
- Showing the exact model ID string (with its casing) next to each model in the console would help:
  IDs mix styles (`Nemotron-3-Ultra-550b-a55b` vs `nemotron-3-super-120b-a12b`) and are case-sensitive.
