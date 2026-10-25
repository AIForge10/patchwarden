import hashlib
import hmac

import pytest

from resolveloop.security import assert_allowed_repo, redact_text, verify_webhook_signature


def test_webhook_signature_and_redaction() -> None:
    body, secret = b'{"incident":"one"}', "shared-secret"
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, f"sha256={signature}", secret)
    assert not verify_webhook_signature(body, signature, "wrong")
    assert "ghp_" not in redact_text("Authorization: Bearer ghp_secret jane@example.com")


def test_allowlisted_repo_requires_exact_url_and_sha() -> None:
    settings = type("Settings", (), {"ALLOWED_REPO_URL": "https://github.com/a/b"})()
    assert_allowed_repo("https://github.com/a/b", "a" * 40, settings)
    with pytest.raises(PermissionError):
        assert_allowed_repo("https://github.com/a/other", "a" * 40, settings)
    with pytest.raises(ValueError):
        assert_allowed_repo("https://github.com/a/b", "main", settings)
