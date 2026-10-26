import pytest

from resolveloop.verifier.patch_policy import assert_safe_patch, parse_changed_paths

SAFE = "--- a/demo_app/app/main.py\n+++ b/demo_app/app/main.py\n@@ -1 +1 @@\n-a\n+b\n"


def test_patch_policy_permits_only_application_python() -> None:
    assert parse_changed_paths(SAFE) == ["demo_app/app/main.py"]
    assert_safe_patch(SAFE)
    with pytest.raises(ValueError):
        assert_safe_patch(SAFE.replace("demo_app/app/main.py", "demo_app/tests/test_incident.py"))
