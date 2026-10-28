from patchwarden.models import DiscoveryResult

from .runner import evaluate_invariant, execute_scenario


def confirm_violation(handle, spec, catalog, baseline_commit: str = "") -> DiscoveryResult:
    first = execute_scenario(handle, spec)
    second = execute_scenario(handle, spec)
    violated = evaluate_invariant(spec, first, catalog)
    reproduced_twice = violated and evaluate_invariant(spec, second, catalog)
    return DiscoveryResult(
        scenario=spec,
        oracle_id=spec.invariant_id,
        observed=first,
        violated=violated,
        reproduced_twice=reproduced_twice,
        baseline_commit=baseline_commit,
    )


def run_negative_control(handle, spec, catalog) -> bool:
    """True when the scenario holds on the known-good control gateway (no false positive)."""
    return not evaluate_invariant(spec, execute_scenario(handle, spec, control=True), catalog)
