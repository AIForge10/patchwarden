def test_config_imports():
    from resolveloop import config

    assert 1 <= config.MAX_PATCH_ATTEMPTS <= 5
