def render_pr_body(result) -> str:
    verification = result.verification
    lines = [
        "## Incident summary",
        f"Incident: `{result.incident.incident_id}`",
        f"Pinned baseline: `{result.patch.base_sha if result.patch else 'unavailable'}`",
        "## Verification evidence",
        f"Status: `{result.status.value}`",
    ]
    if verification:
        lines.append(
            f"Red to green: `{verification.baseline_red}` -> `{verification.reproducer_green}`"
        )
        lines.append(f"Regression suite green: `{verification.suite_green}`")
    lines.extend(
        ["## Limitations", "Controlled seeded checkout demo; human review remains required."]
    )
    return "\n\n".join(lines)


def render_failure_report(result) -> str:
    return (
        f"Run `{result.run_id}` ended as `{result.status.value}`. "
        "No verified repair claim was made."
    )
