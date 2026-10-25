# Feedback log: Nebius Token Factory and NVIDIA Nemotron

Running notes from building ResolveLoop. Facts only: what we ran and what happened.

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
- Moving from a flat layout to the `resolveloop/` package meant every import had to change (`from resolveloop import config`). Running tests as `python -m pytest` avoids needing extra path config.

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

### What this means for ResolveLoop

- The model must always see the source files the traceback names. The context step (`resolveloop/agent/context.py`) already reads them before every patch request.
- Never trust a fix from the trace alone: the trace-only runs passed the original failing case but broke other behavior. This is why the verifier runs the full test suite, not just the reproducer.

## Oct 21: agent client check (A2 + A3)

- `healthcheck_model()` confirmed both configured models are available to our key.
- Diagnosis prompt returned the required format: `EVIDENCE: buggy_checkout.py:6 ...`, a correct hypothesis, and `UNCERTAINTY: medium`.
- Patch call cost 733 input and 572 output tokens on Super. A repeated identical call was served from our local replay cache with no API request.
# Feedback log

| Date | Area | Finding | Outcome |
| --- | --- | --- | --- |
| 2026-10-25 | Baseline demo | The malformed gateway case is intentionally red before repair. | Preserve as an explicit reproducer. |
