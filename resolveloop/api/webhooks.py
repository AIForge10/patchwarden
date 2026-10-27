import json

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from resolveloop.events import emit
from resolveloop.models import IncidentEvidence
from resolveloop.orchestrator import run_incident
from resolveloop.security import assert_allowed_repo, verify_webhook_signature
from resolveloop.store import create_run, get_run, list_events

router = APIRouter()
KNOWN_REPRODUCERS = {"checkout_malformed_response"}


def parse_alert(payload: dict) -> IncidentEvidence:
    try:
        incident = IncidentEvidence.model_validate(payload)
    except Exception as error:
        raise ValueError("invalid incident payload") from error
    if incident.reproducer_id not in KNOWN_REPRODUCERS:
        raise ValueError("unknown reproducer")
    return incident


@router.post("/webhooks/incident", status_code=202)
async def incident_webhook(request: Request, background: BackgroundTasks) -> dict:
    body = await request.body()
    settings = request.app.state.settings
    signature = request.headers.get("X-ResolveLoop-Signature")
    if not verify_webhook_signature(body, signature, settings.WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="invalid webhook signature")
    try:
        incident = parse_alert(json.loads(body))
        assert_allowed_repo(incident.repo_url, incident.commit_sha, settings)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except (ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    run_id = create_run(incident)
    if not list_events(run_id):  # a duplicate alert must not start a second run
        emit(run_id, "RECEIVED", "Signed incident accepted", {"incident_id": incident.incident_id})
        background.add_task(run_incident, incident)
        return {"run_id": run_id, "status": "RECEIVED"}
    return {"run_id": run_id, "status": get_run(run_id).status.value}
