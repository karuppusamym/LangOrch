import logging
import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

logger = logging.getLogger(__name__)

def setup_tracing(app=None, otlp_endpoint: str | None = None):
    """Initialize OpenTelemetry tracing."""
    
    # Only setup if endpoint is provided or OTLP_ENDPOINT env var is set
    endpoint = otlp_endpoint or os.getenv("OTLP_ENDPOINT")
    
    if not endpoint:
        logger.info("OpenTelemetry tracing disabled (no OTLP_ENDPOINT provided).")
        return None

    logger.info(f"Configuring OpenTelemetry tracing with endpoint: {endpoint}")
    
    resource = Resource.create({
        "service.name": "langorch-backend",
        "service.version": "0.1.0",
        "deployment.environment": os.getenv("ENVIRONMENT", "development")
    })

    provider = TracerProvider(resource=resource)
    
    # Using HTTP exporter by default
    # If endpoint doesn't end with v1/traces, the exporter appends it
    exporter = OTLPSpanExporter(endpoint=endpoint)
    processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(processor)

    # Set global tracer provider
    trace.set_tracer_provider(provider)
    
    # Instrument FastAPI if provided
    if app:
        FastAPIInstrumentor.instrument_app(app)
        
    return provider

def get_tracer(name: str):
    """Helper to get a tracer instance."""
    return trace.get_tracer(name)
