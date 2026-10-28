"""Stable, serialisable contracts shared by PatchWarden components."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RunStatus(StrEnum):
    RECEIVED = "RECEIVED"
    BASELINING = "BASELINING"
    UNREPRODUCED = "UNREPRODUCED"
    DIAGNOSING = "DIAGNOSING"
    PATCHING = "PATCHING"
    VERIFYING = "VERIFYING"
    CHALLENGING = "CHALLENGING"
    CONFIRMED_DISCOVERY = "CONFIRMED_DISCOVERY"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    PR_OPENED = "PR_OPENED"


class IncidentEvidence(BaseModel):
    incident_id: str
    repo_url: str
    commit_sha: str
    error_type: str
    message: str
    traceback: str
    reproducer_id: str
    sanitized_request: dict[str, Any] | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    environment: dict[str, Any] = Field(default_factory=dict)


class RunEvent(BaseModel):
    run_id: str
    seq: int = 0
    stage: str
    severity: str = "info"
    message: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class PatchCandidate(BaseModel):
    base_sha: str
    unified_diff: str
    rationale: str = ""
    attempt: int = 1
    touched_paths: list[str] = Field(default_factory=list)


class CommandResult(BaseModel):
    argv: list[str]
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    truncated: bool = False


class VerificationResult(BaseModel):
    baseline_red: bool = False
    reproducer_green: bool = False
    suite_green: bool = False
    paths_safe: bool = False
    oracle_intact: bool = False
    test_counts: dict[str, int] = Field(default_factory=dict)
    status: str = "FAILED"


class ScenarioSpec(BaseModel):
    scenario_id: str
    invariant_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""


class DiscoveryResult(BaseModel):
    scenario: ScenarioSpec
    oracle_id: str
    observed: dict[str, Any]
    violated: bool
    reproduced_twice: bool = False
    baseline_commit: str = ""
    control_clean: bool | None = None  # None: negative control not run
    repaired: bool = False


class RunResult(BaseModel):
    run_id: str
    status: RunStatus
    incident: IncidentEvidence
    patch: PatchCandidate | None = None
    verification: VerificationResult | None = None
    discoveries: list[DiscoveryResult] = Field(default_factory=list)
    events: list[RunEvent] = Field(default_factory=list)
    evidence_path: str | None = None
    pr_url: str | None = None
