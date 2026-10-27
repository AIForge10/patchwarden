"""Sliding-window limiter: no network."""

from resolveloop.ratelimit import SlidingWindow


def test_window_allows_then_blocks_then_frees() -> None:
    window = SlidingWindow()
    assert window.allow("webhook", 2, 10, now=1.0)
    assert window.allow("webhook", 2, 10, now=2.0)
    assert not window.allow("webhook", 2, 10, now=3.0)
    assert window.retry_after("webhook", 10, now=3.0) == 9
    assert window.allow("webhook", 2, 10, now=11.1)


def test_keys_and_reset_are_independent() -> None:
    window = SlidingWindow()
    assert window.allow("webhook", 1, 60, now=1.0)
    assert window.allow("model", 1, 60, now=1.0)
    assert not window.allow("webhook", 1, 60, now=2.0)
    window.reset()
    assert window.allow("webhook", 1, 60, now=3.0)
