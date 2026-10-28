"""Optional, untrusted documentation lookup kept outside decision-making."""

from urllib.parse import urlparse


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
