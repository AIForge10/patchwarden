"""In-process sliding-window limiter.

Rate-limit webhook and model requests; cap payload size.
One process is enough for the demo API. Cached model replies do not count.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

WINDOW_SECONDS = 60
WEBHOOK_LIMIT = 10
MODEL_LIMIT = 30
WEBHOOK_MAX_BODY_BYTES = 65_536
MODEL_MAX_PROMPT_CHARS = 100_000


class SlidingWindow:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_s: float, now: float | None = None) -> bool:
        if limit <= 0:
            return False
        now = time.monotonic() if now is None else now
        hits = self._hits[key]
        cutoff = now - window_s
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True

    def retry_after(self, key: str, window_s: float, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        hits = self._hits.get(key)
        if not hits:
            return 1
        return max(1, int(hits[0] + window_s - now) + 1)

    def reset(self) -> None:
        self._hits.clear()


limiter = SlidingWindow()
