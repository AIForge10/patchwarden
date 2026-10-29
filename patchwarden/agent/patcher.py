"""Turn one failure into a proposed patch, and retry until the verifier accepts one."""

from dataclasses import dataclass, field
from pathlib import Path

from patchwarden import config
from patchwarden.agent.context import (
    make_unified_diff,
    parse_model_files,
    paths_from_traceback,
    read_context,
)
from patchwarden.agent.nebius_client import Reply, chat_full
from patchwarden.agent.prompts import (
    DIAGNOSIS_SYSTEM,
    PATCH_SYSTEM,
    build_diagnosis_prompt,
    build_patch_prompt,
)
from patchwarden.models import PatchCandidate, RunStatus
from patchwarden.sandbox.repository import reset_to_commit
from patchwarden.verifier.baseline import failure_output
from patchwarden.verifier.patch_policy import parse_changed_paths
from patchwarden.verifier.verify import VerifyOutcome, run_verification


@dataclass
class PatchProposal:
    """Carries the frozen PatchCandidate fields (base_sha, unified_diff, rationale,
    attempt, touched_paths) plus debugging extras. Convert to models.PatchCandidate
    once the shared models.py exists."""

    unified_diff: str  # empty if the model gave nothing usable
    files: dict = field(default_factory=dict)  # path -> new full content
    paths_read: list = field(default_factory=list)
    reply: Reply = None
    problem: str = ""  # why the diff is empty, if it is
    rationale: str = ""  # the diagnosis text
    attempt: int = 1
    base_sha: str = ""

    @property
    def diff(self) -> str:
        return self.unified_diff

    @property
    def touched_paths(self) -> list:
        return sorted(self.files)


def diagnose(
    traceback: str, files: dict, search_results: str = "", model: str = "", max_tokens: int = 3000
) -> str:
    """Return EVIDENCE / HYPOTHESIS / UNCERTAINTY lines (empty string if cut off)."""
    reply = chat_full(
        build_diagnosis_prompt(traceback, files, search_results),
        system=DIAGNOSIS_SYSTEM,
        model=model,
        max_tokens=max_tokens,
    )
    if reply.finish_reason == "length":
        return ""
    keep = [
        line
        for line in reply.text.splitlines()
        if line.startswith(("EVIDENCE:", "HYPOTHESIS:", "UNCERTAINTY:"))
    ]
    return "\n".join(keep)


def propose_patch(
    traceback: str,
    repo_root,
    feedback: str = "",
    attempt: int = 1,
    diagnosis: str = "",
    base_sha: str = "",
    model: str = "",
    max_tokens: int = 6000,
) -> PatchProposal:
    root = Path(repo_root)
    paths = paths_from_traceback(traceback, root)
    files = read_context(root, paths)
    prompt = build_patch_prompt(traceback, files, feedback, diagnosis, attempt)
    reply = chat_full(prompt, system=PATCH_SYSTEM, model=model, max_tokens=max_tokens)

    if reply.finish_reason == "length":
        return PatchProposal(
            "", {}, paths, reply, "reply cut off by token limit", diagnosis, attempt, base_sha
        )

    new_files = parse_model_files(reply.text)
    new_files = {p: c for p, c in new_files.items() if p in files}  # only files we showed it
    diff = "".join(make_unified_diff(p, files[p], c) for p, c in new_files.items() if c != files[p])
    if not diff:
        return PatchProposal(
            "",
            new_files,
            paths,
            reply,
            "model returned no usable change",
            diagnosis,
            attempt,
            base_sha,
        )
    return PatchProposal(diff, new_files, paths, reply, "", diagnosis, attempt, base_sha)


def _no_step(status, message, metadata=None):
    pass


def repair_until_verified(
    incident, sandbox, baseline: dict, diagnosis: str = "", max_attempts: int = 0, step=_no_step
) -> tuple[PatchCandidate | None, VerifyOutcome | None]:
    """Propose -> verify, at most max_attempts times, each from a clean pinned checkout.

    Returns the first VERIFIED candidate, or (None, last outcome). There is no silent
    success: only run_verification can produce VERIFIED. `step(status, message, metadata)`
    reports progress to the orchestrator.
    """
    max_attempts = max_attempts or config.MAX_PATCH_ATTEMPTS
    sha = baseline["baseline_sha"]
    repo = sandbox.root / "repo"
    failure = failure_output(baseline)
    feedback, outcome = "", None
    for attempt in range(1, max_attempts + 1):
        model = config.patch_model(attempt)
        info = {"attempt": attempt, "model": model}
        message = f"Attempt {attempt} of {max_attempts}: requesting a patch from {model}"
        if attempt > 1 and model != config.patch_model(attempt - 1):
            message = (
                f"Attempt {attempt} of {max_attempts}: verifier rejected the last patch, "
                f"escalating to {model}"
            )
        step(RunStatus.PATCHING, message, info)
        reset_to_commit(sandbox, sha)  # context must come from the pinned files, not a past try
        proposal = propose_patch(failure, repo, feedback, attempt, diagnosis, sha, model=model)
        if not proposal.unified_diff:
            feedback = f"Your previous reply was not usable: {proposal.problem}."
            step(RunStatus.PATCHING, f"Attempt {attempt}: {proposal.problem}", info)
            continue
        candidate = PatchCandidate(
            base_sha=sha,
            unified_diff=proposal.unified_diff,
            rationale=diagnosis,
            attempt=attempt,
            touched_paths=parse_changed_paths(proposal.unified_diff),
        )
        paths = ", ".join(candidate.touched_paths)
        step(RunStatus.VERIFYING, f"Attempt {attempt}: verifying a patch to {paths}", info)
        outcome = run_verification(sandbox, baseline, candidate)
        if outcome.result.status == "VERIFIED":
            return candidate, outcome
        feedback = outcome.reason
        why = outcome.reason.splitlines()[0].rstrip(":") if outcome.reason else ""
        message = f"Attempt {attempt}: {outcome.result.status}" + (f": {why}" if why else "")
        step(RunStatus.VERIFYING, message, info)
    return None, outcome
