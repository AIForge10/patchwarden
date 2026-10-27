"""Export a UI recording of a verified fake-model run (no Nebius cost).

python -m resolveloop.scripts.export_demo_recording
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from resolveloop import config
from resolveloop.agent import patcher
from resolveloop.agent.nebius_client import Reply
from resolveloop.agent.prompts import DIAGNOSIS_SYSTEM
from resolveloop.models import IncidentEvidence
from resolveloop.orchestrator import run_incident
from resolveloop.scripts.record_run import RECORDINGS, record

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "demo_app/app/main.py").read_text()
BUG = "    result = PaymentResult.model_validate(response)\n"
FIX = MAIN.replace(
    BUG,
    "    if not isinstance(response, PaymentResult):\n"
    '        return create_order(request.order_id, "failed")\n'
    "    result = response\n",
)
DIAGNOSIS = (
    "EVIDENCE: demo_app/app/main.py:14 - validates an unchecked gateway payload\n"
    "HYPOTHESIS: malformed gateway response raises ValidationError\n"
    "UNCERTAINTY: low - trace is direct"
)


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="resolveloop-recording-"))
    repo = tmp / "checkout-demo"
    shutil.copytree(
        ROOT / "demo_app",
        repo / "demo_app",
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"),
    )
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "-C", str(repo), "add", "."], check=True)
    subprocess.run([*git, "-C", str(repo), "commit", "-qm", "seed"], check=True)
    sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()

    os.environ["PATH"] = os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", "")
    config.ALLOWED_REPO_URL = str(repo)
    config.DATABASE_URL = f"sqlite:///{tmp / 'runs.db'}"
    config.MAX_PATCH_ATTEMPTS = 3
    config.OPEN_PR_ON_VERIFIED = False
    config.RUN_DISCOVERY = True
    config.TAVILY_API_KEY = ""
    os.chdir(tmp)

    def chat_full(prompt, system="", model="", max_tokens=0, use_cache=True):
        if system == DIAGNOSIS_SYSTEM:
            return Reply(DIAGNOSIS, "stop", False)
        return Reply(f"FILE: demo_app/app/main.py\n```python\n{FIX}```\n", "stop", False)

    patcher.chat_full = chat_full
    from resolveloop.discovery import scenarios

    scenarios.chat_full = lambda *args, **kwargs: Reply(
        '[{"scenario_id":"normal_success","invariant_id":"success_exactly_one_order",'
        '"params":{"amount":10},"rationale":"happy path still holds"}]',
        "stop",
        False,
    )

    incident = IncidentEvidence(
        incident_id="demo-001",
        repo_url=str(repo),
        commit_sha=sha,
        error_type="ValidationError",
        message="Unexpected payment response",
        traceback="Traceback (most recent call last): ...",
        reproducer_id="checkout_malformed_response",
    )
    result = run_incident(incident)
    path = record(result.run_id, RECORDINGS)
    print(f"status {result.status.value}")
    print(f"wrote {path}")
    print(f"replay at /ui/?replay=recordings/{path.name}")


if __name__ == "__main__":
    main()
