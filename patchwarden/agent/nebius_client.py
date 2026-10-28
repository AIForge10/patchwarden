"""Nebius client: chat calls, retries, timeouts, and a replay cache. Owner: Satyabrata.

Usage:
    from agent.nebius_client import chat
    text = chat("Say hi", max_tokens=200)

Replay cache: the same request (model + system + prompt + max_tokens) is only
sent to Nebius once. Later identical calls are read from .cache/nebius/ for free.
Set NEBIUS_NO_CACHE=1 to turn the cache off.
"""

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import openai
from openai import OpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from patchwarden import config, ratelimit

CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "nebius"  # repo root
TIMEOUT_SECONDS = 120

_client = None  # created on first use; tests replace it with a fake


class ModelUnavailable(RuntimeError):
    """The model cannot be called at all (missing key, URL or model name)."""


@dataclass
class Reply:
    text: str
    finish_reason: str
    cached: bool
    prompt_tokens: int = 0
    completion_tokens: int = 0


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not (config.NEBIUS_API_KEY and config.NEBIUS_BASE_URL):
            raise ModelUnavailable("Fill NEBIUS_API_KEY and NEBIUS_BASE_URL in .env first.")
        _client = OpenAI(
            api_key=config.NEBIUS_API_KEY,
            base_url=config.NEBIUS_BASE_URL,
            timeout=TIMEOUT_SECONDS,
            max_retries=0,  # we do our own retries below, so each retry is visible
        )
    return _client


def _cache_key(model: str, system: str, prompt: str, max_tokens: int) -> str:
    raw = json.dumps([model, system, prompt, max_tokens], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _read_cache(key: str):
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def _write_cache(key: str, reply: Reply) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(
        json.dumps(
            {
                "text": reply.text,
                "finish_reason": reply.finish_reason,
                "prompt_tokens": reply.prompt_tokens,
                "completion_tokens": reply.completion_tokens,
            }
        )
    )


# Only retry things that can succeed on a second try (network, rate limit, server errors).
# A wrong model name or bad key will NOT be retried: it fails fast with a clear message.
@retry(
    retry=retry_if_exception_type(
        (
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.RateLimitError,
            openai.InternalServerError,
        )
    ),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _call_api(model: str, messages: list, max_tokens: int):
    return get_client().chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )


def chat_full(
    prompt: str, system: str = "", model: str = "", max_tokens: int = 4000, use_cache: bool = True
) -> Reply:
    """Send one prompt and return a Reply (text, finish_reason, cached, token counts)."""
    model = model or config.NEBIUS_MODEL_REASONING
    if not model:
        raise ModelUnavailable("Set NEBIUS_MODEL_REASONING in .env first.")
    if len(prompt) + len(system) > ratelimit.MODEL_MAX_PROMPT_CHARS:
        raise ModelUnavailable("Prompt exceeds MODEL_MAX_PROMPT_CHARS")
    use_cache = use_cache and os.getenv("NEBIUS_NO_CACHE") != "1"

    key = _cache_key(model, system, prompt, max_tokens)
    if use_cache:
        hit = _read_cache(key)
        if hit:
            return Reply(
                hit["text"],
                hit["finish_reason"],
                True,
                hit.get("prompt_tokens", 0),
                hit.get("completion_tokens", 0),
            )

    if not ratelimit.limiter.allow("model", ratelimit.MODEL_LIMIT, ratelimit.WINDOW_SECONDS):
        raise ModelUnavailable("Model rate limit exceeded")

    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    resp = _call_api(model, messages, max_tokens)
    choice = resp.choices[0]
    usage = getattr(resp, "usage", None)
    reply = Reply(
        text=choice.message.content or "",
        finish_reason=choice.finish_reason or "",
        cached=False,
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
    )
    # Never cache a cut-off reply: it would keep returning the broken answer.
    if use_cache and reply.finish_reason != "length":
        _write_cache(key, reply)
    return reply


def chat(
    prompt: str, system: str = "", model: str = "", max_tokens: int = 4000, use_cache: bool = True
) -> str:
    """Same as chat_full but returns only the text."""
    return chat_full(prompt, system, model, max_tokens, use_cache).text


def healthcheck_model() -> dict:
    """A2 done-when: confirm the configured models exist for this key (no tokens spent)."""
    available = {m.id for m in get_client().models.list()}
    wanted = {"reasoning": config.NEBIUS_MODEL_REASONING, "fast": config.NEBIUS_MODEL_FAST}
    return {
        "ok": all(v in available for v in wanted.values() if v),
        "models": {k: {"id": v, "available": v in available} for k, v in wanted.items() if v},
    }
