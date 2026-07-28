"""
Recent metric trends for one entity, read through Prometheus's HTTP query API.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from httpx2 import AsyncClient

from videre.database.tables import FailureEntityTable

from .context import MetricSeriesContext, PrometheusContext
from .label_syntax import escape_label_value

QUERY_STEP_SECONDS = 60
MAXIMUM_SERIES = 24


def build_queries(entity_type: FailureEntityTable, entity_id: str, window_minutes: int) -> list[str]:
    selector_value = escape_label_value(entity_id)
    
    if entity_type is FailureEntityTable.NODE:
        selector = f'{{node_id="{selector_value}"}}'
        return [
            f"videre_gpu_utilization_percent{selector}",
            f"videre_gpu_temperature_celsius{selector}",
            f"max(videre_gpu_temperature_celsius{selector})",
            f"increase(videre_node_failure_events_total{selector}[{window_minutes}m])",
        ]
        
    if entity_type is FailureEntityTable.GPU:
        selector = f'{{gpu_id="{selector_value}"}}'
        return [
            f"videre_gpu_utilization_percent{selector}",
            f"videre_gpu_temperature_celsius{selector}",
            f"videre_gpu_memory_used_bytes{selector}",
            f"increase(videre_gpu_error_events_total{selector}[{window_minutes}m])",
        ]
    
    return [
        "videre_jobs_by_state",
        f"increase(videre_job_failures_total[{window_minutes}m])",
        "videre_unresolved_failures",
    ]


def summarize(fallback_name: str, payload: dict[str, Any]) -> list[MetricSeriesContext]:
    if payload.get("status") != "success":
        return []
    
    summaries: list[MetricSeriesContext] = []
    for entry in payload.get("data", {}).get("result", []):
        values = [float(sample[1]) for sample in entry.get("values", [])]
        if not values:
            continue
        
        metric_labels = entry.get("metric", {})
        summaries.append(
            MetricSeriesContext(
                metric=metric_labels.get("__name__", fallback_name),
                labels={key: value for key, value in metric_labels.items() if key != "__name__"},
                latest=round(values[-1], 2),
                minimum=round(min(values), 2),
                maximum=round(max(values), 2),
                average=round(sum(values) / len(values), 2),
                sample_count=len(values)
            )
        )
    return summaries


async def query_metrics(
    client: AsyncClient,
    base_url: str,
    entity_type: FailureEntityTable,
    entity_id: str,
    *,
    window_minutes: int,
) -> PrometheusContext:
    end = datetime.now(UTC)
    start = end - timedelta(minutes=window_minutes)
    series: list[MetricSeriesContext] = []
    
    for query in build_queries(entity_type, entity_id, window_minutes):
        response = await client.get(
            f"{base_url}/api/v1/query_range",
            params={
                "query": query,
                "start": str(start.timestamp()),
                "end": str(end.timestamp()),
                "step": str(QUERY_STEP_SECONDS)
            }
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        series.extend(summarize(query, payload))
    
    return PrometheusContext(window_minutes=window_minutes, series=series[:MAXIMUM_SERIES])
