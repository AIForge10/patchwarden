"""Settings from environment variables. Owner: Satyabrata.

Plan section 5: validated Settings, get_settings, validate_startup, public_config.
Module-level names stay so callers and tests can keep reading `config.MAX_PATCH_ATTEMPTS`
and monkeypatching individual fields.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

_SECRET_FIELDS = frozenset(
    {
        "NEBIUS_API_KEY",
        "TAVILY_API_KEY",
        "E2B_API_KEY",
        "GITHUB_TOKEN",
        "WEBHOOK_SECRET",
    }
)


class Settings(BaseSettings):
    """Every plan-section-5 variable. Secrets are never included in public_config or repr."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    NEBIUS_API_KEY: str = ""
    NEBIUS_BASE_URL: str = ""
    NEBIUS_MODEL_REASONING: str = ""
    NEBIUS_MODEL_FAST: str = ""
    # Patch-model ladder, comma-separated: attempt N uses entry N (the last one repeats).
    # Empty: every attempt uses NEBIUS_MODEL_REASONING. Only a failed verification moves up.
    NEBIUS_PATCH_MODELS: str = ""
    TAVILY_API_KEY: str = ""
    E2B_API_KEY: str = ""
    GITHUB_TOKEN: str = ""
    GITHUB_OWNER: str = ""
    GITHUB_TARGET_REPO: str = ""
    WEBHOOK_SECRET: str = ""
    ALLOWED_REPO_URL: str = ""
    DATABASE_URL: str = "sqlite:///./patchwarden.db"
    MAX_PATCH_ATTEMPTS: int = Field(default=3, ge=1, le=5)
    MAX_SCENARIOS: int = Field(default=4, ge=0, le=5)
    SANDBOX_TIMEOUT_SECONDS: int = Field(default=180, ge=1)
    # auto: E2B when E2B_API_KEY is set, else a local disposable directory.
    SANDBOX_BACKEND: Literal["auto", "e2b", "local"] = "auto"
    RUN_DISCOVERY: bool = True
    OPEN_PR_ON_VERIFIED: bool = True
    REPAIR_DISCOVERY: bool = False
    # Public "run live" button on the hosted UI: live runs per UTC day. 0 turns it off.
    PUBLIC_DEMO_RUNS_PER_DAY: int = Field(default=0, ge=0, le=500)
    # Let those public runs open real human-review PRs (also needs OPEN_PR_ON_VERIFIED=true and
    # a GitHub token scoped to the demo repo). Off: public runs never open PRs.
    PUBLIC_DEMO_OPEN_PRS: bool = False

    def __repr__(self) -> str:
        return f"Settings({public_config(self)})"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_startup(settings: Any) -> None:
    """Fail closed before the API accepts alerts.

    Ranges are always checked. WEBHOOK_SECRET and ALLOWED_REPO_URL are required to
    start: a signed allowlisted alert is a P0 gate. Provider keys stay optional so
    a machine without Nebius or GitHub can still serve the UI and recordings.
    """
    attempts = settings.MAX_PATCH_ATTEMPTS
    scenarios = settings.MAX_SCENARIOS
    if not (1 <= attempts <= 5):
        raise ValueError("MAX_PATCH_ATTEMPTS must be in 1..5")
    if not (0 <= scenarios <= 5):
        raise ValueError("MAX_SCENARIOS must be in 0..5")
    if not settings.WEBHOOK_SECRET:
        raise ValueError("WEBHOOK_SECRET is required to start the API")
    if not settings.ALLOWED_REPO_URL:
        raise ValueError("ALLOWED_REPO_URL must be the exact allowlisted repository")


def patch_model(attempt: int) -> str:
    """The model that writes patch attempt `attempt` (1-based)."""
    module = sys.modules[__name__]
    ladder = [name.strip() for name in module.NEBIUS_PATCH_MODELS.split(",") if name.strip()]
    if not ladder:
        return module.NEBIUS_MODEL_REASONING
    return ladder[min(attempt, len(ladder)) - 1]


def public_config(settings: Settings | None = None) -> dict[str, Any]:
    """Return settings with secrets stripped. Safe to log or show in the UI."""
    data = (settings or get_settings()).model_dump()
    for key in _SECRET_FIELDS:
        data.pop(key, None)
    return data


def _publish(settings: Settings) -> None:
    module = sys.modules[__name__]
    for name, value in settings.model_dump().items():
        setattr(module, name, value)


try:
    _publish(get_settings())
except ValidationError:
    get_settings.cache_clear()
    raise
