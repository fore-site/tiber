"""OpenTelemetry setup for Tiber services."""

from __future__ import annotations

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CollectorRegistry

from tiber.core.config import get_settings

settings = get_settings()

_prometheus_registry = CollectorRegistry()
_telemetry_configured = False


def get_prometheus_registry() -> CollectorRegistry:
    """Return the registry shared by the metrics reader and ``/metrics`` app."""
    return _prometheus_registry


def configure_telemetry(service_name: str) -> None:
    """Initialize OpenTelemetry once for the current process.

    Metrics are always exposed through the shared Prometheus registry. If an OTLP
    endpoint is configured, the same metrics are also exported there periodically,
    and spans are exported as well.
    """
    global _telemetry_configured

    if _telemetry_configured:
        return

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": settings.app_version,
        }
    )

    _configure_tracing(resource)
    _configure_metrics(resource)
    _telemetry_configured = True


def _configure_tracing(resource: Resource) -> None:
    """Configure tracing, exporting spans only when OTLP is configured."""
    tracer_provider = TracerProvider(resource=resource)

    if settings.otlp_endpoint:
        otlp_exporter = OTLPSpanExporter(endpoint=f"{settings.otlp_endpoint}/v1/traces")
        tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

    trace.set_tracer_provider(tracer_provider)


def _configure_metrics(resource: Resource) -> None:
    """Configure metrics with Prometheus and optional OTLP exporters."""
    readers: list[MetricReader] = [
        PrometheusMetricReader(registry=_prometheus_registry)
    ]

    if settings.otlp_endpoint:
        otlp_metric_exporter = OTLPMetricExporter(
            endpoint=f"{settings.otlp_endpoint}/v1/metrics"
        )
        readers.append(PeriodicExportingMetricReader(otlp_metric_exporter))

    meter_provider = MeterProvider(resource=resource, metric_readers=readers)
    metrics.set_meter_provider(meter_provider)


def get_tracer(name: str) -> trace.Tracer:
    """Return a tracer for the named instrumentation scope."""
    return trace.get_tracer(name)


def get_meter(name: str) -> metrics.Meter:
    """Return a meter for the named instrumentation scope."""
    return metrics.get_meter(name)
