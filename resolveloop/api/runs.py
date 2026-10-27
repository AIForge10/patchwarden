import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from resolveloop.store import get_run, list_events, list_runs

router = APIRouter()


@router.get("/runs")
def recent_runs(limit: int = 20) -> list[dict]:
    return list_runs(min(max(limit, 1), 100))


@router.get("/runs/{run_id}")
def run_status(run_id: str) -> dict:
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    payload = run.model_dump(mode="json", exclude={"incident"})
    return payload | {"incident_id": run.incident.incident_id}


@router.get("/runs/{run_id}/events")
def run_events(run_id: str, after: int = 0) -> list[dict]:
    if get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    return [event.model_dump(mode="json") for event in list_events(run_id, after)]


@router.get("/runs/{run_id}/evidence")
def run_evidence(run_id: str) -> dict:
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if not run.evidence_path:
        raise HTTPException(status_code=404, detail="run has no verified evidence")
    path = Path(run.evidence_path)
    # Only the bundle the verifier wrote for this run, never an arbitrary file.
    if path.name != f"{run_id}.json" or path.parent.name != "evidence" or not path.is_file():
        raise HTTPException(status_code=404, detail="evidence bundle not found")
    return json.loads(path.read_text())
