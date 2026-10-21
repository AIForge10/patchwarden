"""Turn a failure into a proposed patch (one attempt). The retry loop comes in A5. Owner: Satyabrata."""
from dataclasses import dataclass, field
from pathlib import Path

from resolveloop.agent.context import make_unified_diff, parse_model_files, paths_from_traceback, read_context
from resolveloop.agent.nebius_client import Reply, chat_full
from resolveloop.agent.prompts import DIAGNOSIS_SYSTEM, PATCH_SYSTEM, build_diagnosis_prompt, build_patch_prompt


@dataclass
class PatchProposal:
    """Carries the frozen PatchCandidate fields (base_sha, unified_diff, rationale,
    attempt, touched_paths) plus debugging extras. Convert to models.PatchCandidate
    once the shared models.py exists."""
    unified_diff: str               # empty if the model gave nothing usable
    files: dict = field(default_factory=dict)   # path -> new full content
    paths_read: list = field(default_factory=list)
    reply: Reply = None
    problem: str = ""               # why the diff is empty, if it is
    rationale: str = ""             # the diagnosis text
    attempt: int = 1
    base_sha: str = ""

    @property
    def diff(self) -> str:
        return self.unified_diff

    @property
    def touched_paths(self) -> list:
        return sorted(self.files)


def diagnose(traceback: str, files: dict, search_results: str = "",
             model: str = "", max_tokens: int = 3000) -> str:
    """Return EVIDENCE / HYPOTHESIS / UNCERTAINTY lines (empty string if cut off)."""
    reply = chat_full(build_diagnosis_prompt(traceback, files, search_results),
                      system=DIAGNOSIS_SYSTEM, model=model, max_tokens=max_tokens)
    if reply.finish_reason == "length":
        return ""
    keep = [l for l in reply.text.splitlines()
            if l.startswith(("EVIDENCE:", "HYPOTHESIS:", "UNCERTAINTY:"))]
    return "\n".join(keep)


def propose_patch(traceback: str, repo_root, feedback: str = "", attempt: int = 1,
                  diagnosis: str = "", base_sha: str = "",
                  model: str = "", max_tokens: int = 6000) -> PatchProposal:
    root = Path(repo_root)
    paths = paths_from_traceback(traceback, root)
    files = read_context(root, paths)
    prompt = build_patch_prompt(traceback, files, feedback, diagnosis, attempt)
    reply = chat_full(prompt, system=PATCH_SYSTEM, model=model, max_tokens=max_tokens)

    if reply.finish_reason == "length":
        return PatchProposal("", {}, paths, reply, "reply cut off by token limit", diagnosis, attempt, base_sha)

    new_files = parse_model_files(reply.text)
    new_files = {p: c for p, c in new_files.items() if p in files}  # only files we showed it
    diff = "".join(make_unified_diff(p, files[p], c) for p, c in new_files.items() if c != files[p])
    if not diff:
        return PatchProposal("", new_files, paths, reply, "model returned no usable change", diagnosis, attempt, base_sha)
    return PatchProposal(diff, new_files, paths, reply, "", diagnosis, attempt, base_sha)