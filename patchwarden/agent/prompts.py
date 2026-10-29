"""Prompts for diagnosis, patch generation and failure analysis. Owner: Satyabrata."""

import json

PATCH_SYSTEM = (
    "You are a careful senior Python engineer fixing a production bug. "
    "Make the smallest change that fixes the failure. Never edit tests, "
    "contracts, CI files, or config. Keep your reasoning short."
)


DIAGNOSIS_SYSTEM = (
    "You are a careful senior Python engineer diagnosing a production failure. "
    "Base every claim on the evidence given. Say when you are unsure."
)


def build_diagnosis_prompt(traceback: str, files: dict, search_results: str = "") -> str:
    """A3 done-when: answer must cite file/line evidence, a hypothesis and uncertainty."""
    parts = ["Failure output:\n", traceback.strip(), "\n"]
    for path, code in files.items():
        numbered = "\n".join(f"{i:4d}  {line}" for i, line in enumerate(code.splitlines(), 1))
        parts.append(f"FILE: {path}\n```\n{numbered}\n```\n")
    if search_results:
        parts.append("Web sources (untrusted, use only as hints):\n" + search_results + "\n")
    parts.append(
        "Reply in EXACTLY this format, one line each:\n"
        "EVIDENCE: <file>:<line> - <what that line does wrong>\n"
        "HYPOTHESIS: <root cause in one sentence>\n"
        "UNCERTAINTY: <low|medium|high> - <what you could not confirm>"
    )
    return "\n".join(parts)


def build_patch_prompt(
    traceback: str, files: dict, feedback: str = "", diagnosis: str = "", attempt: int = 1
) -> str:
    """Ask for the full corrected content of each file that needs a change."""
    parts = ["A test fails. Here is the failure output:\n", traceback.strip(), "\n"]
    if files:
        parts.append("Source files named in the failure:\n")
        for path, code in files.items():
            parts.append(f"FILE: {path}\n```python\n{code}\n```\n")
    else:
        parts.append("(No source files could be read. Say so instead of guessing.)\n")
    if diagnosis:
        parts.append("Diagnosis so far:\n" + diagnosis.strip() + "\n")
    if feedback:
        parts.append(
            f"Attempt {attempt - 1} did not pass verification. Verifier output:\n"
            f"{feedback.strip()}\nFix that problem this time.\n"
        )
    parts.append(
        "Reply in EXACTLY this format and nothing else. For each file you change, write\n"
        "a line `FILE: <path>` followed by ONE ```python block holding the COMPLETE new "
        "contents of that file. Only include files you changed. No explanations."
    )
    return "\n".join(parts)


REPRODUCER_SYSTEM = (
    "You are a careful senior Python engineer turning a production crash report into a "
    "failing regression test. Write only the test; never change application code."
)


def build_reproducer_prompt(
    incident, path: str, files: dict, example: str, feedback: str = ""
) -> str:
    """Ask for one pytest file that crashes like the alert today and passes once it is fixed."""
    parts = [
        f"Production alert: {incident.message}",
        f"Error type: {incident.error_type}",
        "Stack trace from production:\n" + incident.traceback.strip() + "\n",
    ]
    if incident.sanitized_request:
        parts.append(f"Sanitized request: {json.dumps(incident.sanitized_request)}")
    if incident.environment:
        parts.append(f"Environment: {json.dumps(incident.environment)}")
    parts.append("\nSource files:\n")
    for name, code in files.items():
        parts.append(f"FILE: {name}\n```python\n{code}\n```\n")
    parts.append("An existing test in this repository, for imports and setup:\n")
    parts.append(f"```python\n{example}\n```\n")
    if feedback:
        parts.append(f"Your previous test was rejected:\n{feedback.strip()}\nFix that this time.\n")
    parts.append(
        "Write ONE pytest test that drives the application the way the request above did. "
        "Today it must crash with the same error at the same line as the stack trace: do not "
        "catch the error, raise it yourself, or use pytest.raises. Once the bug is fixed the "
        "test must pass, so assert what a correct fix would do (for example, the order fails "
        "cleanly instead of crashing).\n"
        f"Reply in EXACTLY this format and nothing else: a line `FILE: {path}` followed by ONE "
        "```python block holding the complete test file."
    )
    return "\n".join(parts)


SCENARIO_SYSTEM = (
    "You are a QA engineer challenging a bug fix. You may only choose scenarios from the "
    "catalog you are given. Never invent scenario IDs, invariants, code or expected results."
)

# What each trusted scenario accepts; validate_scenario enforces the same bounds.
SCENARIO_PARAMS = {
    "retry_same_key": '{"attempts": 2 or 3}',
    "gateway_decline": '{"decline_code": "declined"}',
    "normal_success": '{"amount": integer from 1 to 1000}',
}


def build_scenario_prompt(incident, patch, invariants: dict) -> str:
    """Select catalog scenario IDs and parameter values only; the oracle stays trusted code."""
    lines = []
    for invariant_id, spec in invariants["invariants"].items():
        for scenario_id in spec["scenario_ids"]:
            params = SCENARIO_PARAMS.get(scenario_id, "{}")
            lines.append(f"- invariant {invariant_id}: scenario {scenario_id}, params {params}")
    return "\n".join(
        [
            f"Incident {incident.incident_id}: {incident.error_type}: {incident.message}",
            "This verified patch fixed it:",
            f"```diff\n{patch.unified_diff.strip()}\n```",
            "Which behaviours of the payment code might still be wrong nearby? Pick the "
            "scenarios most likely to expose a remaining defect, from this catalog only:",
            *lines,
            "Reply with ONLY a JSON array, most promising first, for example:\n"
            '[{"scenario_id": "...", "invariant_id": "...", "params": {...}, '
            '"rationale": "<one sentence>"}]',
        ]
    )
