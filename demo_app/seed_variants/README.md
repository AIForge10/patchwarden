# Seeded demo defects (disclosure)

This checkout app is a controlled demo target. Its defects are deliberate, and every
one is listed here. The agent never sees this file: its prompts contain only the
observed failing test output, the source files named in that output, and the scenario
catalog IDs.

| Defect | Where | Reported to the agent? | Reproducer (trusted ID → test) |
|---|---|---|---|
| Malformed gateway payload crashes checkout (`ValidationError`) | `app/main.py` | Yes, incident demo-001 | `checkout_malformed_response` → `tests/test_incident.py` |
| A payment held for review completes the order | `app/main.py` | Yes, incident demo-003 | `checkout_unapproved_payment` → `tests/test_incident_review.py` |
| Unknown SKU crashes checkout (`KeyError`) | `app/store.py` | Yes, incident demo-004 | `checkout_unknown_sku` → `tests/test_incident_inventory.py` |
| Gateway timeout crashes checkout (`TimeoutError`) | `app/main.py` | Yes, incident demo-005 | `checkout_gateway_timeout` → `tests/test_incident_timeout.py` |
| **Hidden:** a retry with the same idempotency key charges the card again | `app/payments.py` | **No.** No alert, test or comment points to it | None. Only the trusted `retry_same_key` scenario and the `at_most_one_charge` invariant can expose it |

`tests/test_baseline.py` is the original regression suite. It is green on the seeded
commit and must stay green after every repair.

## Negative control

`control/payments.py` is an independent, known-good gateway: it never charges a retried
idempotency key twice. Before PatchWarden reports a second defect, the trusted runner
re-runs the same scenario with this gateway swapped in. A sound oracle must hold there;
if it does not, the violation is not claimed. The patch policy only allows edits under
`app/`, so a candidate repair cannot change the control, and its hash is recorded with the
protected tests.

The `known-good` branch of the demo repository is the seeded commit with the hidden
double charge fixed. Evaluation case 06 runs incident demo-001 there to count false
positives.
