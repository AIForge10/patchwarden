"""Optional, untrusted documentation lookup kept outside decision-making."""

import re
from urllib.parse import urlparse

from patchwarden.security import redact_text

# pytest's exception line, e.g. "E   pydantic_core._pydantic_core.ValidationError: 1 validation…"
_EXCEPTION_LINE = re.compile(r"^E\s+((?:\w+\.)*)(\w+):?(.*)$", re.M)
_SOURCE_LINE = re.compile(r"^>\s+(.*)$", re.M)
_CALL = re.compile(r"\.(\w+)\(")


def build_search_query(error_type: str, message: str, failure_output: str = "") -> str:
    """A docs-oriented query built from the observed failure, not from repository code.

    A library exception (pydantic_core…ValidationError) becomes
    "python pydantic ValidationError model_validate Field required"; a built-in one becomes
    "python KeyError <alert message>". Redacted before it leaves the process.
    """
    matches = [m for m in _EXCEPTION_LINE.finditer(failure_output) if m.group(2) == error_type]
    if not matches:
        return redact_text(f"python {error_type} {message}".strip())
    found = matches[-1]
    package = re.sub(r"_(core|impl|internal)$", "", found.group(1).split(".")[0])
    if not package:
        return redact_text(f"python {error_type} {message}".strip())
    sources = _SOURCE_LINE.findall(failure_output[: found.start()])
    calls = _CALL.findall(sources[-1]) if sources else []
    detail = ""
    for line in failure_output[found.end() :].splitlines()[:6]:
        text = line.removeprefix("E").split("[", 1)[0].strip()
        if len(text.split()) >= 2:
            detail = text
            break
    parts = ["python", package, error_type, calls[-1] if calls else "", detail]
    return redact_text(" ".join(part for part in parts if part))[:200]


def search_error(query: str) -> list[dict]:
    from patchwarden import config

    if not config.TAVILY_API_KEY:
        return []
    from tavily import TavilyClient

    response = TavilyClient(api_key=config.TAVILY_API_KEY).search(query=query, max_results=3)
    return [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", ""),
        }
        for item in response.get("results", [])
        if urlparse(item.get("url", "")).scheme == "https"
    ]


def format_sources(results: list[dict]) -> str:
    seen: set[str] = set()
    lines = []
    for result in results:
        url = result.get("url", "")
        if url and url not in seen:
            seen.add(url)
            lines.append(f"- {result.get('title', 'Source')}: {url}")
    return "\n".join(lines)
