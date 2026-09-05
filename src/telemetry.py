"""Logging and OpenTelemetry wiring for the monitoring stack.

The deployment scrapes Prometheus metrics from :9464 (pod annotations),
receives traces over OTLP HTTP (Tempo), and ships stdout logs to Loki via
Vector. Vector JSON-parses each log line and lifts the "trace_id", "span_id"
and "level" keys into Loki labels/structured metadata, which is what powers
trace<->log correlation in Grafana — the JSON formatter here must keep
emitting those exact keys.

Environment variables:
    LOG_FORMAT: "json" for one-object-per-line stdout logs, anything else
        for human-readable text (default: text; the Docker image sets json)
    LOG_LEVEL: Python log level name (default: INFO)
    OTEL_ENABLED: "true" to enable OpenTelemetry (default: false)
    OTEL_SERVICE_NAME: service name for telemetry (default: ll-bluebird)
    OTEL_EXPORTER_OTLP_ENDPOINT: OTLP HTTP endpoint (default: http://localhost:4318)
    OTEL_RESOURCE_ATTRIBUTES: extra resource attributes, picked up by the
        SDK automatically (the deployment sets k8s.namespace.name, the join
        key for Grafana's traces->logs link)
    PROMETHEUS_METRICS_PORT: metrics endpoint port (default: 9464)
"""

import json
import logging
import os
import sys
from datetime import UTC, datetime

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider, sampling
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import start_http_server

logger = logging.getLogger(__name__)

_otel_enabled = False

TEXT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

tracer = trace.get_tracer("ll-bluebird")
_meter = metrics.get_meter("ll-bluebird")

tweets_fetched = _meter.create_counter(
    "ll_bluebird_tweets_fetched_total",
    description="Tweets returned by the search API, before and after author filtering",
)
tweets_forwarded = _meter.create_counter(
    "ll_bluebird_tweets_forwarded_total",
    description="Tweets forwarded to Telegram, by character and outcome",
)
translations = _meter.create_counter(
    "ll_bluebird_translations_total",
    description="Translation attempts, by provider and outcome",
)
translation_duration = _meter.create_histogram(
    "ll_bluebird_translation_duration_seconds",
    unit="s",
    description="Wall time of a successful translation, by provider",
)
poll_cycle_duration = _meter.create_histogram(
    "ll_bluebird_poll_cycle_duration_seconds",
    unit="s",
    description="Wall time of one fetch/translate/forward cycle",
)

# The SDK's default buckets top out where a millisecond-scale metric would;
# against seconds they put every observation in the same bucket and any
# quantile drawn from them is a straight line.
_HISTOGRAM_VIEWS = (
    View(
        instrument_name="ll_bluebird_translation_duration_seconds",
        aggregation=ExplicitBucketHistogramAggregation(
            (0.5, 1, 2, 3, 5, 8, 13, 21, 34, 60)
        ),
    ),
    View(
        instrument_name="ll_bluebird_poll_cycle_duration_seconds",
        aggregation=ExplicitBucketHistogramAggregation(
            (1, 2, 5, 10, 20, 30, 60, 120, 300)
        ),
    ),
)

_is_leader = False


def _observe_leader(_options):
    yield metrics.Observation(1 if _is_leader else 0)


_meter.create_observable_gauge(
    "ll_bluebird_leader",
    callbacks=[_observe_leader],
    description="1 while this replica holds the leader lease",
)


def set_leader(is_leader: bool) -> None:
    """Drives the ll_bluebird_leader gauge; exactly one replica should report 1."""
    global _is_leader
    _is_leader = is_leader


class _RootedInUnitOfWork(sampling.Sampler):
    """Drop client spans that would otherwise begin a trace of their own.

    Liveness probes and connection-pool warm-up issue queries outside any span
    of ours, and the asyncpg instrumentor has no suppression hook, so without
    this every SET/BEGIN/COMMIT they run is exported as a separate root trace
    and buries the poll cycles.
    """

    def __init__(self, delegate: sampling.Sampler):
        self._delegate = delegate

    def should_sample(
        self,
        parent_context=None,
        trace_id=0,
        name="",
        kind=None,
        attributes=None,
        links=None,
        trace_state=None,
    ) -> sampling.SamplingResult:
        parent = trace.get_current_span(parent_context).get_span_context()
        if not parent.is_valid and kind is trace.SpanKind.CLIENT:
            return sampling.SamplingResult(
                sampling.Decision.DROP, attributes, trace_state
            )
        return self._delegate.should_sample(
            parent_context, trace_id, name, kind, attributes, links, trace_state
        )

    def get_description(self) -> str:
        return f"RootedInUnitOfWork({self._delegate.get_description()})"


class JsonLogFormatter(logging.Formatter):
    """One JSON object per line, with the current span's IDs when inside one."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            entry["trace_id"] = trace.format_trace_id(span_context.trace_id)
            entry["span_id"] = trace.format_span_id(span_context.span_id)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            entry["stack"] = self.formatStack(record.stack_info)
        return json.dumps(entry, default=str, ensure_ascii=False)


def setup_logging() -> None:
    """Configure the root logger from LOG_FORMAT / LOG_LEVEL."""
    handler = logging.StreamHandler(sys.stdout)
    if os.environ.get("LOG_FORMAT", "text").lower() == "json":
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(logging.Formatter(TEXT_LOG_FORMAT))

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = logging.getLevelNamesMapping().get(level_name)
    logging.basicConfig(level=level or logging.INFO, handlers=[handler], force=True)
    if level is None:
        logger.warning("Unknown LOG_LEVEL %r, defaulting to INFO", level_name)


def setup_opentelemetry() -> None:
    """Initialize tracing (OTLP), the Prometheus metrics endpoint, and
    auto-instrumentation for asyncpg and httpx."""
    global _otel_enabled

    if os.environ.get("OTEL_ENABLED", "false").lower() != "true":
        logger.info("OpenTelemetry disabled (set OTEL_ENABLED=true to enable)")
        return
    _otel_enabled = True

    service_name = os.environ.get("OTEL_SERVICE_NAME", "ll-bluebird")
    otlp_endpoint = os.environ.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"
    )
    prometheus_port = int(os.environ.get("PROMETHEUS_METRICS_PORT", "9464"))

    # Also merges OTEL_RESOURCE_ATTRIBUTES from the environment.
    resource = Resource.create({SERVICE_NAME: service_name})

    tracer_provider = TracerProvider(
        resource=resource,
        sampler=_RootedInUnitOfWork(sampling.ParentBased(sampling.ALWAYS_ON)),
    )
    # No endpoint argument: the exporter reads OTEL_EXPORTER_OTLP_ENDPOINT and
    # appends the /v1/traces path itself.
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    start_http_server(port=prometheus_port, addr="0.0.0.0")
    metrics.set_meter_provider(
        MeterProvider(
            resource=resource,
            metric_readers=[PrometheusMetricReader()],
            views=_HISTOGRAM_VIEWS,
        )
    )

    from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    AsyncPGInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()

    logger.info(
        "OpenTelemetry initialized: service=%s, traces=%s, metrics=:%d/metrics",
        service_name,
        otlp_endpoint,
        prometheus_port,
    )


def instrument_fastapi_app(app) -> None:
    """Trace HTTP handlers, minus /health: kubelet probes it every few seconds
    and the spans say nothing."""
    if not _otel_enabled:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls="health")
