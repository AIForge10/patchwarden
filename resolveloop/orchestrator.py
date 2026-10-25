"""Evidence-gated run coordinator.

This intentionally stops rather than inventing success whenever an external
credential, baseline, policy, or verifier gate is unavailable.
"""

from resolveloop.events import emit
from resolveloop.models import RunResult, RunStatus
from resolveloop.store import create_run, set_run_status


def advance(run_id: str, next_status: RunStatus) -> None:
    set_run_status(run_id, next_status)
    emit(run_id, next_status.value, f"Entered {next_status.value}")


def run_incident(incident) -> RunResult:
    run_id = create_run(incident)
    advance(run_id, RunStatus.BASELINING)
    # External sandbox/model execution is deliberately invoked by the service layer
    # only after all production credentials and exact commit validation are present.
    advance(run_id, RunStatus.UNREPRODUCED)
    emit(run_id, "UNREPRODUCED", "No verified sandbox reproduction was run", severity="warning")
    return RunResult(run_id=run_id, status=RunStatus.UNREPRODUCED, incident=incident)


def maybe_create_pr(result: RunResult) -> RunResult:
    if result.status != RunStatus.VERIFIED or not result.verification:
        return result
    if not all(
        (
            result.verification.reproducer_green,
            result.verification.suite_green,
            result.verification.oracle_intact,
        )
    ):
        return result
    return result
