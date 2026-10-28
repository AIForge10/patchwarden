from .models import RunEvent
from .store import append_event, list_events


def emit(
    run_id: str,
    stage: str,
    message: str,
    metadata: dict | None = None,
    severity: str = "info",
) -> RunEvent:
    event = RunEvent(
        run_id=run_id,
        stage=stage,
        severity=severity,
        message=message,
        metadata=metadata or {},
    )
    return append_event(event)


__all__ = ["emit", "list_events"]
