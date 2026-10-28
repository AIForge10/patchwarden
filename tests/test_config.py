"""A2: Settings validation. No network, no secrets required in the environment."""

import pytest
from pydantic import ValidationError

from patchwarden.config import Settings, public_config, validate_startup


def _settings(**overrides) -> Settings:
    fields = {
        "NEBIUS_API_KEY": "dummy-key",  # pragma: allowlist secret
        "WEBHOOK_SECRET": "dummy-hook",  # pragma: allowlist secret
        "ALLOWED_REPO_URL": "https://github.com/acme/checkout",
        "MAX_PATCH_ATTEMPTS": 3,
        "MAX_SCENARIOS": 4,
    } | overrides
    return Settings(_env_file=None, **fields)


def test_ranges_and_public_config_hide_secrets() -> None:
    settings = _settings()
    public = public_config(settings)
    assert public["MAX_PATCH_ATTEMPTS"] == 3
    assert public["ALLOWED_REPO_URL"] == "https://github.com/acme/checkout"
    assert "WEBHOOK_SECRET" not in public
    assert "NEBIUS_API_KEY" not in public
    assert "dummy-key" not in repr(settings)
    assert "dummy-hook" not in repr(settings)


def test_out_of_range_attempts_and_scenarios_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(MAX_PATCH_ATTEMPTS=0)
    with pytest.raises(ValidationError):
        _settings(MAX_PATCH_ATTEMPTS=6)
    with pytest.raises(ValidationError):
        _settings(MAX_SCENARIOS=6)
    with pytest.raises(ValidationError):
        _settings(MAX_SCENARIOS=-1)


def test_startup_requires_webhook_secret_and_allowlisted_repo() -> None:
    validate_startup(_settings())
    with pytest.raises(ValueError, match="WEBHOOK_SECRET"):
        validate_startup(_settings(WEBHOOK_SECRET=""))
    with pytest.raises(ValueError, match="ALLOWED_REPO_URL"):
        validate_startup(_settings(ALLOWED_REPO_URL=""))


def test_startup_rejects_monkeypatched_out_of_range_values() -> None:
    settings = _settings()
    settings.MAX_PATCH_ATTEMPTS = 9
    with pytest.raises(ValueError, match="MAX_PATCH_ATTEMPTS"):
        validate_startup(settings)
