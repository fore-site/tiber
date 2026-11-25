"""HTTP request metrics and the Prometheus exposition endpoint."""

from __future__ import annotations

from collections.abc import Sequence
from time import perf_counter

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tiber.core.telemetry import get_meter, get_prometheus_registry

_METRICS_PATH = "/metrics"
_UNMATCHED_ROUTE = "__unmatched__"
_UNVERSIONED = "none"
_REQUEST_DURATION_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)


def render_metrics() -> Response:
    """Render the shared registry in Prometheus text exposition format."""
    return Response(
        content=generate_latest(get_prometheus_registry()),
        headers={"Content-Type": CONTENT_TYPE_LATEST},
    )


class RequestMetricsMiddleware:
    """Record low-cardinality HTTP server metrics for every request."""

    def __init__(self, app: ASGIApp, versions: Sequence[str] = ()) -> None:
        """Create the middleware and its OpenTelemetry instruments.

        ``versions`` is supplied by the app so this module stays unaware of
        which versions exist: it only labels a request with the prefix it was
        served under. Without that label a deprecated version cannot be
        retired safely, because nobody can see who still calls it.
        """
        self._app = app
        self._versions = tuple(versions)
        meter = get_meter("tiber.api.http")
        self._duration = meter.create_histogram(
            "http.server.request.duration",
            unit="s",
            description="Duration of inbound HTTP server requests.",
            explicit_bucket_boundaries_advisory=_REQUEST_DURATION_BUCKETS,
        )
        self._requests = meter.create_counter(
            "http.server.requests",
            unit="{request}",
            description="Number of inbound HTTP server requests.",
        )
        self._active = meter.create_up_down_counter(
            "http.server.active_requests",
            unit="{request}",
            description="Number of inbound HTTP server requests currently in flight.",
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Wrap one ASGI call and record its duration and outcome."""
        if scope["type"] != "http" or self._is_metrics_request(scope):
            await self._app(scope, receive, send)
            return

        method = scope.get("method", "UNKNOWN")
        active_attributes = {"http.request.method": method}
        started_at = perf_counter()
        status_code = 500

        self._active.add(1, active_attributes)
        try:

            async def _send(message: Message) -> None:
                nonlocal status_code
                if message["type"] == "http.response.start":
                    status_code = message["status"]
                await send(message)

            await self._app(scope, receive, _send)
        finally:
            duration = perf_counter() - started_at
            route = self._route_path(scope)
            attributes = {
                "http.request.method": method,
                "http.route": route,
                "http.response.status_code": status_code,
                "tiber.api.version": self._version(scope),
            }
            self._duration.record(duration, attributes)
            self._requests.add(1, attributes)
            self._active.add(-1, active_attributes)

    def _version(self, scope: Scope) -> str:
        """Return the API version whose prefix served this request."""
        path = scope.get("path", "")
        for version in self._versions:
            if path == f"/{version}" or path.startswith(f"/{version}/"):
                return version
        return _UNVERSIONED

    @staticmethod
    def _is_metrics_request(scope: Scope) -> bool:
        path = scope.get("path", "")
        return path == _METRICS_PATH or path.startswith(f"{_METRICS_PATH}/")

    @classmethod
    def _route_path(cls, scope: Scope) -> str:
        route = scope.get("route")
        route_path = getattr(route, "path", None)
        if not route_path:
            return _UNMATCHED_ROUTE

        route_segments = [segment for segment in route_path.split("/") if segment]
        if not route_segments:
            return "/"

        actual_segments = [
            segment for segment in scope.get("path", "").split("/") if segment
        ]
        for offset in range(len(actual_segments) - len(route_segments) + 1):
            candidate = actual_segments[offset : offset + len(route_segments)]
            if all(
                cls._segment_matches(template, actual)
                for template, actual in zip(route_segments, candidate, strict=True)
            ):
                return "/" + "/".join([*actual_segments[:offset], *route_segments])
        return route_path

    @staticmethod
    def _segment_matches(template: str, actual: str) -> bool:
        return (
            template.startswith("{") and template.endswith("}")
        ) or template == actual
