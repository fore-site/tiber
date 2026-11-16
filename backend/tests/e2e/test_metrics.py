"""End-to-end coverage for the Prometheus metrics endpoint."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


async def test_metrics_endpoint_exposes_request_duration(client, project) -> None:
    """A real request is recorded with a route template, not the raw URL."""
    response = await client.get(
        f"/v1/projects/{project.id}/recipients",
        headers={"Authorization": "Bearer e2e"},
    )
    assert response.status_code == 200

    metrics = await client.get("/metrics")

    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")
    body = metrics.text
    assert "http_server_request_duration_seconds_bucket" in body
    assert 'http_route="/v1/projects/{project_id}/recipients"' in body
    assert 'http_response_status_code="200"' in body
    assert 'http_request_method="GET"' in body
    assert 'http_route="/metrics"' not in body
