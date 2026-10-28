"""Offline tests for the Nebius client, context step and patcher. No network, no cost."""

from types import SimpleNamespace

import pytest

from patchwarden.agent import context, nebius_client, patcher
from patchwarden.agent.nebius_client import ModelUnavailable

TRACE = """\
buggy_checkout.py:10: in checkout
    charge_id = parse_payment_response(response)
buggy_checkout.py:6: in parse_payment_response
    return response["data"]["charge_id"]
E       KeyError: 'data'
test_checkout.py:12: in test_x
"""

OLD = 'def f(r):\n    return r["data"]\n'
NEW = 'def f(r):\n    return r.get("data")\n'
REPLY = f"FILE: buggy_checkout.py\n```python\n{NEW}```\n"


class FakeClient:
    """Stands in for the OpenAI client and counts calls."""

    def __init__(self, text=REPLY, finish="stop"):
        self.calls = 0
        self.text, self.finish = text, finish
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls += 1
        msg = SimpleNamespace(content=self.text)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=msg, finish_reason=self.finish)],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )


@pytest.fixture
def fake(tmp_path, monkeypatch):
    f = FakeClient()
    monkeypatch.setattr(nebius_client, "_client", f)
    monkeypatch.setattr(nebius_client, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(nebius_client.config, "NEBIUS_MODEL_REASONING", "test-model")
    monkeypatch.delenv("NEBIUS_NO_CACHE", raising=False)
    return f


def test_model_rate_limit_blocks_uncached_calls(fake, monkeypatch):
    monkeypatch.setattr(nebius_client.ratelimit, "MODEL_LIMIT", 1)
    nebius_client.chat_full("first", max_tokens=10)
    with pytest.raises(ModelUnavailable, match="rate limit"):
        nebius_client.chat_full("second", max_tokens=10)
    assert fake.calls == 1


def test_cached_model_call_does_not_count_against_limit(fake, monkeypatch):
    monkeypatch.setattr(nebius_client.ratelimit, "MODEL_LIMIT", 1)
    first = nebius_client.chat_full("hello", max_tokens=50)
    second = nebius_client.chat_full("hello", max_tokens=50)
    assert not first.cached and second.cached
    assert fake.calls == 1


def test_oversized_prompt_never_reaches_the_api(fake, monkeypatch):
    monkeypatch.setattr(nebius_client.ratelimit, "MODEL_MAX_PROMPT_CHARS", 8)
    with pytest.raises(ModelUnavailable, match="MODEL_MAX_PROMPT_CHARS"):
        nebius_client.chat_full("this is way too long")
    assert fake.calls == 0


def test_second_identical_call_is_cached(fake):
    first = nebius_client.chat_full("hello", max_tokens=50)
    second = nebius_client.chat_full("hello", max_tokens=50)
    assert not first.cached and second.cached
    assert fake.calls == 1


def test_cut_off_reply_is_not_cached(tmp_path, monkeypatch):
    f = FakeClient(text="partial", finish="length")
    monkeypatch.setattr(nebius_client, "_client", f)
    monkeypatch.setattr(nebius_client, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(nebius_client.config, "NEBIUS_MODEL_REASONING", "m")
    nebius_client.chat_full("x")
    nebius_client.chat_full("x")
    assert f.calls == 2


def test_paths_from_traceback_skips_tests_and_outside(tmp_path):
    (tmp_path / "buggy_checkout.py").write_text(OLD)
    (tmp_path / "test_checkout.py").write_text("")
    assert context.paths_from_traceback(TRACE, tmp_path) == ["buggy_checkout.py"]


def test_read_context_blocks_traversal(tmp_path):
    (tmp_path / "ok.py").write_text("x = 1\n")
    out = context.read_context(tmp_path, ["ok.py", "../secret.py"])
    assert list(out) == ["ok.py"]


def test_propose_patch_builds_diff(tmp_path, fake):
    (tmp_path / "buggy_checkout.py").write_text(OLD)
    result = patcher.propose_patch(TRACE, tmp_path)
    assert '-    return r["data"]' in result.diff
    assert '+    return r.get("data")' in result.diff
    assert result.diff.startswith("--- a/buggy_checkout.py")


def test_propose_patch_ignores_files_it_was_not_shown(tmp_path, monkeypatch, fake):
    (tmp_path / "buggy_checkout.py").write_text(OLD)
    fake.text = "FILE: tests/test_checkout.py\n```python\nassert True\n```\n"
    result = patcher.propose_patch(TRACE, tmp_path)
    assert result.diff == "" and result.problem


def test_healthcheck_reports_missing_model(monkeypatch):
    models = SimpleNamespace(list=lambda: [SimpleNamespace(id="nvidia/a")])
    monkeypatch.setattr(nebius_client, "_client", SimpleNamespace(models=models))
    monkeypatch.setattr(nebius_client.config, "NEBIUS_MODEL_REASONING", "nvidia/a")
    monkeypatch.setattr(nebius_client.config, "NEBIUS_MODEL_FAST", "nvidia/missing")
    out = nebius_client.healthcheck_model()
    assert out["ok"] is False
    assert out["models"]["reasoning"]["available"] is True


def test_diagnosis_prompt_marks_search_results_untrusted():
    from patchwarden.agent.prompts import build_diagnosis_prompt

    text = build_diagnosis_prompt("trace", {"a.py": "x = 1"}, "- Hint: https://example.com/x")
    assert "untrusted" in text.lower()
    assert "https://example.com/x" in text


def test_search_error_is_noop_without_a_key():
    from patchwarden.agent.research import search_error

    assert search_error("KeyError") == []


def test_search_error_keeps_https_results_only(monkeypatch):
    import tavily

    from patchwarden import config as cfg
    from patchwarden.agent.research import search_error

    monkeypatch.setattr(cfg, "TAVILY_API_KEY", "k")

    class FakeClient:
        def __init__(self, api_key):
            pass

        def search(self, query, max_results=3):
            return {
                "results": [
                    {"title": "ok", "url": "https://example.com/a", "content": "x"},
                    {"title": "bad", "url": "http://insecure.example/a", "content": "y"},
                ]
            }

    monkeypatch.setattr(tavily, "TavilyClient", FakeClient)
    found = search_error("ValidationError")
    assert [item["url"] for item in found] == ["https://example.com/a"]


def test_diagnose_keeps_only_the_three_lines(tmp_path, fake):
    fake.text = (
        "thinking...\nEVIDENCE: buggy_checkout.py:6 - no data key check\n"
        "HYPOTHESIS: KeyError on malformed response\nUNCERTAINTY: low - clear trace\n"
    )
    out = patcher.diagnose(TRACE, {"buggy_checkout.py": OLD})
    assert out.splitlines()[0].startswith("EVIDENCE: buggy_checkout.py:6")
    assert len(out.splitlines()) == 3


def test_patch_proposal_has_patch_candidate_fields(tmp_path, fake):
    (tmp_path / "buggy_checkout.py").write_text(OLD)
    p = patcher.propose_patch(TRACE, tmp_path, attempt=2, base_sha="abc")
    assert p.attempt == 2 and p.base_sha == "abc"
    assert p.touched_paths == ["buggy_checkout.py"]
    assert p.unified_diff == p.diff


def test_diff_marks_missing_final_newline(tmp_path):
    import subprocess

    old, new = "a = 1\nb = 2", "a = 1\nb = 3\n"
    (tmp_path / "f.py").write_text(old)
    diff = context.make_unified_diff("f.py", old, new)
    assert "\\ No newline at end of file" in diff
    (tmp_path / "p.diff").write_text(diff)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    r = subprocess.run(
        ["git", "apply", "--check", "p.diff"], cwd=tmp_path, capture_output=True, text=True
    )
    assert r.returncode == 0, r.stderr


def test_assertion_only_failure_follows_the_test_imports(tmp_path):
    """A plain assert names only the test; the code under test is what it imports."""
    (tmp_path / "shop/tests").mkdir(parents=True)
    (tmp_path / "shop/app.py").write_text("def total(): return 1\n")
    (tmp_path / "shop/tests/test_total.py").write_text(
        "import json\nfrom shop.app import total\n\ndef test_total():\n    assert total() == 2\n"
    )
    trace = "shop/tests/test_total.py:5: in test_total\nE   AssertionError: assert 1 == 2\n"
    assert context.paths_from_traceback(trace, tmp_path) == ["shop/app.py"]
