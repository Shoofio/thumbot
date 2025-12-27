"""
OpenTelemetry tracing for ThumbBot
"""
import os
from functools import wraps
from typing import Optional, Callable, Any
from contextlib import asynccontextmanager

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import Status, StatusCode
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor

from thumbot.utils.logger import get_logger

logger = get_logger("tracing")

# Global tracer
_tracer: Optional[trace.Tracer] = None
_initialized = False


def init_tracing(
    service_name: str = "thumbot",
    otel_endpoint: Optional[str] = None,
    enabled: bool = True
) -> Optional[trace.Tracer]:
    """
    Initialize OpenTelemetry tracing
    
    Args:
        service_name: Name of the service for traces
        otel_endpoint: OTLP endpoint (e.g., "http://jaeger:4317")
        enabled: Whether tracing is enabled
    
    Returns:
        Tracer instance or None if disabled
    """
    global _tracer, _initialized
    
    if _initialized:
        return _tracer
    
    if not enabled or not otel_endpoint:
        logger.info("Tracing disabled (no OTEL_ENDPOINT configured)")
        _initialized = True
        return None
    
    try:
        # Create resource with service info
        resource = Resource.create({
            "service.name": service_name,
            "service.version": "2.0.0",
        })
        
        # Create tracer provider
        provider = TracerProvider(resource=resource)
        
        # Create OTLP exporter
        exporter = OTLPSpanExporter(
            endpoint=otel_endpoint,
            insecure=True  # For local dev; in prod use TLS
        )
        
        # Add batch processor for efficient export
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
        
        # Set as global provider
        trace.set_tracer_provider(provider)
        
        # Instrument aiohttp client
        AioHttpClientInstrumentor().instrument()
        
        # Get tracer
        _tracer = trace.get_tracer(service_name)
        _initialized = True
        
        logger.success(f"Tracing initialized: {otel_endpoint}")
        return _tracer
        
    except Exception as e:
        logger.error(f"Failed to initialize tracing: {e}")
        _initialized = True
        return None


def get_tracer() -> Optional[trace.Tracer]:
    """Get the global tracer instance"""
    return _tracer


@asynccontextmanager
async def trace_span(
    name: str,
    attributes: Optional[dict] = None
):
    """
    Async context manager for creating trace spans
    
    Usage:
        async with trace_span("download_video", {"url": url}) as span:
            # do work
            span.set_attribute("file_size", size)
    """
    if _tracer is None:
        # Tracing disabled, yield a dummy span
        yield DummySpan()
        return
    
    with _tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        try:
            yield span
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


def trace_async(name: Optional[str] = None, attributes: Optional[dict] = None):
    """
    Decorator for tracing async functions
    
    Usage:
        @trace_async("my_operation")
        async def my_function(arg1, arg2):
            ...
    """
    def decorator(func: Callable) -> Callable:
        span_name = name or func.__name__
        
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            if _tracer is None:
                return await func(*args, **kwargs)
            
            with _tracer.start_as_current_span(span_name) as span:
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.record_exception(e)
                    raise
        
        return wrapper
    return decorator


class DummySpan:
    """Dummy span for when tracing is disabled"""
    
    def set_attribute(self, key: str, value: Any):
        pass
    
    def set_status(self, status: Any):
        pass
    
    def record_exception(self, exception: Exception):
        pass
    
    def add_event(self, name: str, attributes: Optional[dict] = None):
        pass


def add_span_attributes(**attributes):
    """Add attributes to the current span"""
    span = trace.get_current_span()
    if span:
        for key, value in attributes.items():
            span.set_attribute(key, value)


def add_span_event(name: str, attributes: Optional[dict] = None):
    """Add an event to the current span"""
    span = trace.get_current_span()
    if span:
        span.add_event(name, attributes or {})

