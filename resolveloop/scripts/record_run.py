"""Export a finished run so the progress UI can replay it offline (A7).

    python -m resolveloop.scripts.record_run <run_id>
    then open /ui/?replay=recordings/<run_id>.json   (or "Play recording" in the UI)

The recording is the run's public (redacted) state, its event log and its evidence
manifest, exactly as stored: a replay shows what really happened, at compressed speed.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from resolveloop.store import get_run

RECORDINGS = Path(__file__).resolve().parents[1] / "ui" / "recordings"


def record(run_id: str, directory: Path = RECORDINGS) -> Path:
    run = get_run(run_id)
    if run is None:
        raise SystemExit(f"no run {run_id} in this database")
    evidence = None
    if run.evidence_path and Path(run.evidence_path).is_file():
        evidence = json.loads(Path(run.evidence_path).read_text())
    status = run.model_dump(mode="json", exclude={"incident", "events"})
    recording = {
        "format": "resolveloop-recording/1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "run": status | {"incident_id": run.incident.incident_id},
        "events": [event.model_dump(mode="json") for event in run.events],
        "evidence": evidence,
    }
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run_id}.json"
    path.write_text(json.dumps(recording, indent=2) + "\n")

    index_path = directory / "index.json"
    index = json.loads(index_path.read_text()) if index_path.is_file() else []
    index = [entry for entry in index if entry["run_id"] != run_id]
    entry = {"run_id": run_id, "incident_id": run.incident.incident_id, "file": path.name}
    index.insert(0, entry | {"status": run.status.value})
    index_path.write_text(json.dumps(index, indent=2) + "\n")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    path = record(parser.parse_args().run_id)
    print(f"wrote {path}\nreplay at /ui/?replay=recordings/{path.name}")


if __name__ == "__main__":
    main()
