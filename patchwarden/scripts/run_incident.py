"""Run one incident through the full pipeline from the command line (no API server).

    python -m patchwarden.scripts.run_incident               # ALLOWED_REPO_URL at its HEAD
    python -m patchwarden.scripts.run_incident --sha <40-hex>
    python -m patchwarden.scripts.run_incident --local --mock # local zero-cost test
    python -m patchwarden.scripts.run_incident --fixture demo_app/fixtures/incident_03.json

Uses the real model and, when OPEN_PR_ON_VERIFIED=true and GitHub is configured,
opens a real human-review PR on GITHUB_TARGET_REPO.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from patchwarden import config
from patchwarden.agent import patcher
from patchwarden.agent.nebius_client import Reply
from patchwarden.agent.prompts import DIAGNOSIS_SYSTEM
from patchwarden.discovery import scenarios
from patchwarden.models import IncidentEvidence
from patchwarden.orchestrator import run_incident
from patchwarden.store import list_events


def _setup_mock_model() -> None:
    root = Path(__file__).resolve().parents[2]
    main_code = (root / "demo_app/app/main.py").read_text()
    bug = "    result = PaymentResult.model_validate(response)\n"
    fix = main_code.replace(
        bug,
        "    if not isinstance(response, PaymentResult):\n"
        '        return create_order(request.order_id, "failed")\n'
        "    result = response\n",
    )
    diagnosis = (
        "EVIDENCE: demo_app/app/main.py:14 - validates an unchecked gateway payload\n"
        "HYPOTHESIS: malformed gateway response raises ValidationError\n"
        "UNCERTAINTY: low - trace is direct"
    )

    def fake_chat_full(prompt, system="", model="", max_tokens=0, use_cache=True):
        if system == DIAGNOSIS_SYSTEM:
            return Reply(diagnosis, "stop", False)
        return Reply(f"FILE: demo_app/app/main.py\n```python\n{fix}```\n", "stop", False)

    patcher.chat_full = fake_chat_full
    scenarios.chat_full = lambda *args, **kwargs: Reply(
        '[{"scenario_id":"normal_success","invariant_id":"success_exactly_one_order",'
        '"params":{"amount":10},"rationale":"happy path still holds"}]',
        "stop",
        False,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=config.ALLOWED_REPO_URL)
    parser.add_argument("--sha", help="pinned commit (default: HEAD)")
    parser.add_argument("--error-type", default="ValidationError")
    parser.add_argument("--reproducer", default="checkout_malformed_response")
    parser.add_argument(
        "--local",
        action="store_true",
        help="run against current local repository path and commit",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="use deterministic mock model replies (offline / zero API cost)",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        help="alert JSON (repo, SHA, error type, reproducer); a unique run suffix is added",
    )
    parser.add_argument(
        "--incident-id", help="exact incident ID (duplicates return the earlier run)"
    )
    parser.add_argument(
        "--repair-discovery",
        action="store_true",
        help="also try to repair a confirmed second defect",
    )
    parser.add_argument("--no-pr", action="store_true", help="never open a pull request")
    args = parser.parse_args()
    if args.repair_discovery:
        config.REPAIR_DISCOVERY = True
    if args.no_pr:
        config.OPEN_PR_ON_VERIFIED = False
    fixture = json.loads(args.fixture.read_text()) if args.fixture else {}
    if fixture:
        args.repo = fixture["repo_url"]
        args.sha = args.sha or fixture["commit_sha"]
        args.error_type = fixture["error_type"]
        args.reproducer = fixture["reproducer_id"]

    repo = args.repo
    if args.local:
        repo = str(Path.cwd().resolve())
        config.ALLOWED_REPO_URL = repo

    if not repo:
        parser.error("set ALLOWED_REPO_URL in .env or pass --repo / --local")

    if args.local:
        sha = args.sha or subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
    else:
        sha = (
            args.sha
            or subprocess.check_output(["git", "ls-remote", repo, "HEAD"], text=True).split()[0]
        )

    if args.mock:
        _setup_mock_model()
        if not config.GITHUB_TOKEN:
            config.OPEN_PR_ON_VERIFIED = False

    model_label = "mock-harness" if args.mock else config.NEBIUS_MODEL_REASONING
    print(f"repo {repo} @ {sha[:12]} | model {model_label}")
    stamp = int(time.time())
    fields = {
        "incident_id": f"cli-{stamp}",
        "message": "Run from the command line",
        "traceback": "(observed by the reproducer)",
    }
    if fixture:
        fields = {key: fixture[key] for key in ("message", "traceback")} | {
            "incident_id": f"{fixture['incident_id']}-r{stamp}",
            "sanitized_request": fixture.get("sanitized_request"),
            "environment": fixture.get("environment", {}),
        }
    incident = IncidentEvidence(
        **fields,
        repo_url=repo,
        commit_sha=sha,
        error_type=args.error_type,
        reproducer_id=args.reproducer,
    )
    if args.incident_id:
        incident.incident_id = args.incident_id
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
