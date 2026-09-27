"""Smoke test: the API service must be importable.

The suite exercises the domain and application layers with fakes and never
imports the FastAPI app, so a broken import inside the API package (a renamed
domain exception, a bad dependency) ships unnoticed — the worker still imports
cleanly and every test stays green while the service cannot start. This pin
makes that failure visible in CI.
"""


def test_app_imports():
    """``create_app()`` runs, so every import in the API package resolves."""
    from tiber.api.main import app

    assert app is not None
