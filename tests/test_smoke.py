def test_config_imports():
    from patchwarden import config

    assert 1 <= config.MAX_PATCH_ATTEMPTS <= 5
