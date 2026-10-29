"""Public "run live" demo: start one of the bundled alerts from the hosted UI.

A visitor picks a case number; nothing else they send is used. The alert comes from the
bundled fixture, the run goes through the same gates as a signed alert, and it is held to:
one public run at a time, PUBLIC_DEMO_RUNS_PER_DAY per UTC day (0 turns this off), and an E2B
sandbox (repository code never runs inside this server). Pull requests stay off unless the
host opts in with PUBLIC_DEMO_OPEN_PRS; then a verified run opens a human-review PR on the
configured demo repository, exactly as a signed alert would.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from patchwarden.events import emit
from patchwarden.models import IncidentEvidence
from patchwarden.orchestrator import run_incident
from patchwarden.sandbox.e2b_runner import use_e2b
from patchwarden.store import create_run

router = APIRouter()
FIXTURES = Path(__file__).resolve().parents[2] / "demo_app" / "fixtures"
CASES = {
    "01": ("incident_01.json", False, "Malformed gateway payload crashes checkout"),
    "02": ("incident_02.json", True, "Same crash, and repair the hidden second defect too"),
    "03": ("incident_03.json", False, "A payment held for review completes the order"),
    "04": ("incident_04.json", False, "Unknown SKU crashes checkout"),
    "05": ("incident_05.json", False, "Gateway timeout crashes checkout"),
    "06": ("incident_06.json", False, "Negative control: same crash, hidden defect absent"),
}

_lock = threading.Lock()
_state = {"active": None, "day": "", "used": 0}


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _unavailable(settings) -> str | None:
    """Why the public demo cannot start a run on this host, or None."""
    if settings.PUBLIC_DEMO_RUNS_PER_DAY <= 0:
        return "Live runs are turned off on this host. Recorded runs still play below."
    if not all((FIXTURES / name).is_file() for name, _, _ in CASES.values()):
        return "The bundled demo alerts are missing from this deployment."
    if settings.OPEN_PR_ON_VERIFIED and not settings.PUBLIC_DEMO_OPEN_PRS:
        return (
            "Live runs need OPEN_PR_ON_VERIFIED=false, or PUBLIC_DEMO_OPEN_PRS=true to let "
            "visitors open pull requests."
        )
    if settings.OPEN_PR_ON_VERIFIED and not _github_configured(settings):
        return "Public pull requests are on, but GitHub is not configured on this host."
    if not (settings.NEBIUS_API_KEY and settings.NEBIUS_MODEL_REASONING):
        return "The model is not configured on this host."
    try:
        if not use_e2b():
            return "Live runs need an E2B sandbox; this host has no E2B key."
    except RuntimeError as error:
        return str(error)
    return None


def _github_configured(settings) -> bool:
    return bool(settings.GITHUB_TOKEN and settings.GITHUB_OWNER and settings.GITHUB_TARGET_REPO)


def _remaining(settings) -> int:
    used = _state["used"] if _state["day"] == _today() else 0
    return max(0, settings.PUBLIC_DEMO_RUNS_PER_DAY - used)


def demo_status(settings) -> dict:
    reason = _unavailable(settings)
    opens_prs = reason is None and bool(settings.OPEN_PR_ON_VERIFIED)
    return {
        "enabled": reason is None,
        "reason": reason,
        "busy_run": _state["active"],
        "remaining_today": _remaining(settings) if reason is None else 0,
        "opens_prs": opens_prs,
        "pr_repo": (
            f"https://github.com/{settings.GITHUB_OWNER}/{settings.GITHUB_TARGET_REPO}"
            if opens_prs
            else None
        ),
    }


@router.get("/demo")
def demo_cases(request: Request) -> dict:
    cases = [
        {"case": key, "title": title, "repair_discovery": repair, **_alert_summary(name)}
        for key, (name, repair, title) in CASES.items()
    ]
    return demo_status(request.app.state.settings) | {"cases": cases}


def _alert_summary(name: str) -> dict:
    path = FIXTURES / name
    if not path.is_file():
        return {"incident_id": "", "error_type": "", "commit_sha": ""}
    alert = json.loads(path.read_text())
    return {
        "incident_id": alert["incident_id"],
        "error_type": alert["error_type"],
        "commit_sha": alert["commit_sha"],
    }


@router.post("/demo/runs", status_code=202)
def start_demo_run(payload: dict, request: Request, background: BackgroundTasks) -> dict:
    settings = request.app.state.settings
    case = CASES.get(str(payload.get("case", "")))
    if case is None:
        raise HTTPException(status_code=404, detail="unknown demo case")
    reason = _unavailable(settings)
    if reason:
        raise HTTPException(status_code=403, detail=reason)
    name, repair, _ = case
    with _lock:
        if _state["active"]:
            raise HTTPException(
                status_code=409,
                detail="A live run is already in progress; watch it, then try again.",
                headers={"X-Run-Id": _state["active"]},
            )
        if _remaining(settings) <= 0:
            raise HTTPException(status_code=429, detail="Today's live runs are used up.")
        alert = json.loads((FIXTURES / name).read_text())
        alert["incident_id"] = f"{alert['incident_id']}-live-{uuid.uuid4().hex[:8]}"
        alert.pop("timestamp", None)
        incident = IncidentEvidence.model_validate(alert)
        run_id = create_run(incident)
        if _state["day"] != _today():
            _state.update(day=_today(), used=0)
        _state["used"] += 1
        _state["active"] = run_id
    emit(run_id, "RECEIVED", "Live demo alert accepted", {"incident_id": incident.incident_id})
    background.add_task(_run, incident, repair)
    return {"run_id": run_id, "status": "RECEIVED"}


def _run(incident: IncidentEvidence, repair: bool) -> None:
    try:
        run_incident(incident, repair_discovery=repair)
    finally:
        with _lock:
            _state["active"] = None


def reset() -> None:
    """Tests only."""
    _state.update(active=None, day="", used=0)
