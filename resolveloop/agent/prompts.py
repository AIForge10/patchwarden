"""Prompts for diagnosis, patch generation and failure analysis. Owner: Satyabrata."""

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


def build_patch_prompt(traceback: str, files: dict, feedback: str = "",
                       diagnosis: str = "", attempt: int = 1) -> str:
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