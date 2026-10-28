from buggy_checkout import checkout


def test_normal_response():
    out = checkout("o1", {"data": {"charge_id": "c1"}})
    assert out["status"] == "completed"


def test_malformed_response_is_not_completed():
    # The gateway sometimes returns no "data" at all. We must not crash,
    # and the order must not be marked completed.
    out = checkout("o2", {"error": "bad gateway"})
    assert out["status"] != "completed"
