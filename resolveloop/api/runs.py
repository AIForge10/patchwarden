from fastapi import APIRouter, HTTPException

from resolveloop.store import get_run, list_events

router = APIRouter()


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
