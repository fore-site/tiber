from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from tiber.core.config import get_settings

settings = get_settings()


def configure_telemetry() -> None:
    """
    Initializes and configures OpenTelemetry for tracing and metrics collection.
    """
    resource = Resource.create(
        {
            "service.name": settings.app_name.lower(),
            "service.version": settings.app_version,
        }
    )
    _configure_tracing(resource)
    _configure_metrics(resource)


def _configure_tracing(resource: Resource) -> None:
    """
    Configures OpenTelemetry tracing with an OTLP exporter.

    Args:
        resource (Resource): The resource associated with the telemetry data.
    """
    tracer_provider = TracerProvider(resource=resource)

    if settings.otlp_endpoint:
        otlp_exporter = OTLPSpanExporter(endpoint=f"{settings.otlp_endpoint}/v1/traces")
        span_processor = BatchSpanProcessor(otlp_exporter)
        tracer_provider.add_span_processor(span_processor)

        trace.set_tracer_provider(tracer_provider)


def _configure_metrics(resource: Resource) -> None:
    """
    Configures OpenTelemetry metrics with an OTLP exporter.

    Args:
        resource (Resource): The resource associated with the telemetry data.
    """
    if settings.otlp_endpoint:
        otlp_metric_exporter = OTLPMetricExporter(endpoint=f"{settings.otlp_endpoint}/v1/metrics")
        metric_reader = PeriodicExportingMetricReader(otlp_metric_exporter)
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        metrics.set_meter_provider(meter_provider)


def get_tracer(name: str) -> trace.Tracer:
    """
    Retrieves a tracer instance for the specified name.

    Args:
        name (str): The name of the tracer.
    """
    return trace.get_tracer(name)


def get_meter(name: str) -> metrics.Meter:
    """
    Retrieves a meter instance for the specified name.

    Args:
        name (str): The name of the meter.
    """
    return metrics.get_meter(name)