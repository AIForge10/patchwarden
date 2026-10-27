"""Run one incident through the full pipeline from the command line (no API server).

    python -m resolveloop.scripts.run_incident               # ALLOWED_REPO_URL at its HEAD
    python -m resolveloop.scripts.run_incident --sha <40-hex>

Uses the real model and, when OPEN_PR_ON_VERIFIED=true and GitHub is configured,
opens a real human-review PR on GITHUB_TARGET_REPO.
"""

import argparse
import subprocess
import time

from resolveloop import config
from resolveloop.models import IncidentEvidence
from resolveloop.orchestrator import run_incident
from resolveloop.store import list_events


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=config.ALLOWED_REPO_URL)
    parser.add_argument("--sha", help="pinned commit (default: the repo's current HEAD)")
    parser.add_argument("--error-type", default="ValidationError")
    parser.add_argument("--reproducer", default="checkout_malformed_response")
    args = parser.parse_args()
    if not args.repo:
        parser.error("set ALLOWED_REPO_URL in .env or pass --repo")
    sha = (
        args.sha
        or subprocess.check_output(["git", "ls-remote", args.repo, "HEAD"], text=True).split()[0]
    )

    incident = IncidentEvidence(
        incident_id=f"cli-{int(time.time())}",
        repo_url=args.repo,
        commit_sha=sha,
        error_type=args.error_type,
        message="Run from the command line",
        traceback="(observed by the reproducer)",
        reproducer_id=args.reproducer,
    )
    print(f"repo {args.repo} @ {sha[:12]} | model {config.NEBIUS_MODEL_REASONING}")
    result = run_incident(incident)
    for event in list_events(result.run_id):
        print(f"{event.seq:3d} {event.stage:12s} {event.severity:7s} {event.message[:160]}")
    print(f"\nSTATUS {result.status.value}")
    if result.evidence_path:
        print(f"evidence {result.evidence_path}")
    if result.pr_url:
        print(f"PR {result.pr_url}")


if __name__ == "__main__":
    main()
