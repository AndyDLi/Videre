"""
FastAPI wiring for Prometheus.
"""

from fastapi import FastAPI
from prometheus_client import CollectorRegistry
from prometheus_fastapi_instrumentator import Instrumentator

METRICS_ENDPOINT = "/metrics"
HEALTH_ENDPOINT = "/healthz"


def instrument_application(application: FastAPI, registry: CollectorRegistry | None = None) -> None:
    # create the instrumentator to automatically observe the application and record telemetry
    instrumentator = Instrumentator(
        should_group_status_codes=False,
        excluded_handlers=[METRICS_ENDPOINT, HEALTH_ENDPOINT],    # do not count calls to these endpoints in metrics
        registry=registry,    # container holding all Prometheus metrics for this application
    )
    
    # expose the metrics endpoint to Prometheus to scrape metrics stored in the registry
    instrumentator.instrument(application).expose(
        application, endpoint=METRICS_ENDPOINT, include_in_schema=False
    )
