"""Boundary checks for untrusted webhook and repository input."""

import hashlib
import hmac
import re


def verify_webhook_signature(body: bytes, signature: str | None, secret: str) -> bool:
    if not signature or not secret:
        return False
    supplied = signature.removeprefix("sha256=")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)


def assert_allowed_repo(repo_url: str, sha: str, settings) -> None:
    if repo_url != settings.ALLOWED_REPO_URL:
        raise PermissionError("repository is not allowlisted")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
        raise ValueError("commit SHA must be exactly 40 hexadecimal characters")


def redact_text(value: str) -> str:
    value = re.sub(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,]+", r"\1[REDACTED]", value)
    value = re.sub(
        r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]+)\b",
        "[REDACTED]",
        value,
    )
    value = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[REDACTED_EMAIL]", value)
    value = re.sub(r"\b(?:\d[ -]*?){13,16}\b", "[REDACTED_PAYMENT]", value)
    return value
