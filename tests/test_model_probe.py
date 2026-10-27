"""A1 model probe: missing keys and failed healthcheck never hit the network."""

from types import SimpleNamespace

import pytest

from resolveloop import config
from resolveloop.agent.nebius_client import ModelUnavailable
from resolveloop.scripts import model_probe


def test_probe_exits_when_keys_are_missing(monkeypatch) -> None:
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "")
    monkeypatch.setattr(config, "NEBIUS_BASE_URL", "")
    with pytest.raises(SystemExit, match="NEBIUS_API_KEY"):
        model_probe.main()


def test_probe_exits_when_healthcheck_fails(monkeypatch) -> None:
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "k")
    monkeypatch.setattr(config, "NEBIUS_BASE_URL", "https://example.invalid")
    monkeypatch.setattr(config, "NEBIUS_MODEL_REASONING", "nvidia/missing")
    monkeypatch.setattr(
        model_probe,
        "healthcheck_model",
        lambda: {
            "ok": False,
            "models": {"reasoning": {"id": "nvidia/missing", "available": False}},
        },
    )
    with pytest.raises(SystemExit, match="not available"):
        model_probe.main()


def test_probe_uses_healthcheck_then_one_uncached_chat(monkeypatch, capsys) -> None:
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "k")
    monkeypatch.setattr(config, "NEBIUS_BASE_URL", "https://example.invalid")
    monkeypatch.setattr(config, "NEBIUS_MODEL_REASONING", "nvidia/ok")
    monkeypatch.setattr(
        model_probe,
        "healthcheck_model",
        lambda: {"ok": True, "models": {"reasoning": {"id": "nvidia/ok", "available": True}}},
    )
    called = []

    def fake_chat(prompt, max_tokens=20, use_cache=True):
        called.append(SimpleNamespace(prompt=prompt, max_tokens=max_tokens, use_cache=use_cache))
        return "ready"

    monkeypatch.setattr(model_probe, "chat", fake_chat)
    model_probe.main()
    assert called[0].prompt == "Reply with the single word: ready"
    assert called[0].max_tokens == 20 and called[0].use_cache is False
    assert "nvidia/ok (available)" in capsys.readouterr().out


def test_probe_reports_model_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(config, "NEBIUS_API_KEY", "k")
    monkeypatch.setattr(config, "NEBIUS_BASE_URL", "https://example.invalid")

    def boom() -> dict:
        raise ModelUnavailable("no key")

    monkeypatch.setattr(model_probe, "healthcheck_model", boom)
    with pytest.raises(SystemExit, match="no key"):
        model_probe.main()
