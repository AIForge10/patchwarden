"""Small SQLite persistence layer; all public reads are redacted."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from .models import IncidentEvidence, RunEvent, RunResult, RunStatus
from .security import redact_text


def _path() -> str:
    from . import config

    return config.DATABASE_URL.removeprefix("sqlite:///")


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_path())
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    Path(_path()).parent.mkdir(parents=True, exist_ok=True)
    with _connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, incident_id TEXT UNIQUE NOT NULL,
          status TEXT NOT NULL, incident_json TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (run_id TEXT NOT NULL, seq INTEGER NOT NULL,
          event_json TEXT NOT NULL,
          PRIMARY KEY (run_id, seq));
        CREATE TABLE IF NOT EXISTS evidence (run_id TEXT PRIMARY KEY, manifest_json TEXT NOT NULL);
        """)


def create_run(incident: IncidentEvidence) -> str:
    init_db()
    with _connect() as db:
        row = db.execute(
            "SELECT run_id FROM runs WHERE incident_id = ?", (incident.incident_id,)
        ).fetchone()
        if row:
            return row["run_id"]
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        db.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?)",
            (
                run_id,
                incident.incident_id,
                RunStatus.RECEIVED.value,
                incident.model_dump_json(),
                incident.timestamp.isoformat(),
            ),
        )
    return run_id


def set_run_status(run_id: str, status: RunStatus) -> None:
    with _connect() as db:
        cursor = db.execute("UPDATE runs SET status = ? WHERE run_id = ?", (status.value, run_id))
        if not cursor.rowcount:
            raise KeyError(run_id)


def append_event(event: RunEvent) -> RunEvent:
    with _connect() as db:
        row = db.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE run_id = ?", (event.run_id,)
        ).fetchone()
        metadata = {key: redact_text(str(value)) for key, value in event.metadata.items()}
        stored = event.model_copy(
            update={"seq": row[0], "message": redact_text(event.message), "metadata": metadata}
        )
        db.execute(
            "INSERT INTO events VALUES (?, ?, ?)",
            (stored.run_id, stored.seq, stored.model_dump_json()),
        )
    return stored


def list_events(run_id: str, after_seq: int = 0) -> list[RunEvent]:
    with _connect() as db:
        rows = db.execute(
            "SELECT event_json FROM events WHERE run_id = ? AND seq > ? ORDER BY seq",
            (run_id, after_seq),
        )
        return [RunEvent.model_validate_json(row[0]) for row in rows]


def get_run(run_id: str) -> RunResult | None:
    with _connect() as db:
        row = db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    return RunResult(
        run_id=run_id,
        status=RunStatus(row["status"]),
        incident=IncidentEvidence.model_validate_json(row["incident_json"]),
        events=list_events(run_id),
    )
