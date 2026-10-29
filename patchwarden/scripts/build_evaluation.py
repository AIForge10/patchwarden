"""Build docs/evaluation.csv from executed runs only: evidence files plus the event log.

    python -m patchwarden.scripts.build_evaluation docs/evaluation/cases.json

cases.json maps each evaluation case to the run that executed it. Every column is read
back from that run's events and evidence manifest; nothing is typed in by hand. The
evidence files are copied next to the CSV so evidence_hash can be checked by anyone.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path

from patchwarden.store import get_run

COLUMNS = [
    "case_id",
    "variant_sha",
    "run_id",
    "model",
    "seeded",
    "blind",
    "reproduced",
    "patch_attempts",
    "primary_verified",
    "scenarios_proposed",
    "secondary_confirmed",
    "false_positive",
    "pr_created",
    "elapsed_seconds",
    "failure_reason",
    "evidence_hash",
]


def _flag(value: bool) -> str:
    return "true" if value else "false"


def row_for(case: dict, out_dir: Path) -> dict:
    run = get_run(case["run_id"])
    if run is None:
        raise SystemExit(f"{case['case_id']}: run {case['run_id']} is not in the database")
    events = run.events
    stages = [event.stage for event in events]
    messages = [event.message for event in events]
    attempts = [e.metadata["attempt"] for e in events if "attempt" in e.metadata]
    failures = [e.metadata["failure_code"] for e in events if "failure_code" in e.metadata]
    manifest, evidence_hash = {}, "none"
    if run.evidence_path:
        source = Path(run.evidence_path)
        manifest = json.loads(source.read_text())
        evidence_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, out_dir / source.name)
    discovery = manifest.get("discovery") or {}
    confirmed = discovery.get("confirmed", [])
    rejected = sum(message.startswith("Rejected a proposed scenario") for message in messages)
    expected = set(case.get("seeded_hidden_defects", []))
    elapsed = (events[-1].created_at - events[0].created_at).total_seconds() if events else 0
    return {
        "case_id": case["case_id"],
        "variant_sha": run.incident.commit_sha,
        "run_id": run.run_id,
        "model": manifest.get("model_id") or case.get("model", "none"),
        "seeded": "true",
        "blind": _flag(case.get("blind", False)),
        "reproduced": _flag("DIAGNOSING" in stages),
        "patch_attempts": max(attempts, default=0),
        "primary_verified": _flag("VERIFIED" in stages),
        "scenarios_proposed": discovery.get("scenarios_run", 0) + rejected,
        "secondary_confirmed": len(confirmed),
        "false_positive": len(set(confirmed) - expected),
        "pr_created": _flag(run.pr_url is not None),
        "elapsed_seconds": round(elapsed),
        "failure_reason": ";".join(dict.fromkeys(failures)) or "none",
        "evidence_hash": evidence_hash,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", type=Path)
    parser.add_argument("--csv", type=Path, default=Path("docs/evaluation.csv"))
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text())["cases"]
    rows = [row_for(case, args.cases.parent / "evidence") for case in cases]
    with args.csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        print(f"{row['case_id']:34s} {row['run_id']} verified={row['primary_verified']}")


if __name__ == "__main__":
    main()
