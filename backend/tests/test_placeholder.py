def test_import_settings():
    """Assert imports work. Smokescreen test."""
    from tiber.core.config import get_settings

    assert get_settings() is not None
