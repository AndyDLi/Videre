"""
Recent log lines for one entity, read through Loki's HTTP query API.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from httpx2 import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from videre.database.tables import FailureEntityTable, Gpu, Job

from .context import LogLineContext, LokiContext
from .label_syntax import escape_label_value

APPLICATION_STREAMS = '{namespace="videre", app=~"simulator|backend"}'
MAXIMUM_LINE_LENGTH = 500
NANOSECONDS_PER_SECOND = 1_000_000_000


def build_entity_query(entity_id: str) -> str:
    return f'{APPLICATION_STREAMS} |= "{escape_label_value(entity_id)}"'


def build_pod_query(pod_name: str) -> str:
    return f'{{namespace="videre", pod="{escape_label_value(pod_name)}"}}'


async def resolve_queries(
    session: AsyncSession,
    entity_type: FailureEntityTable,
    entity_id: str
) -> list[str]:
    if entity_type is FailureEntityTable.NODE:
        return [build_entity_query(entity_id)]
    
    if entity_type is FailureEntityTable.GPU:
        node_id = (
            await session.execute(
                select(Gpu.node_id)
                .where(Gpu.id == entity_id)
            )
        ).scalar_one_or_none()
        return [build_entity_query(node_id if node_id is not None else entity_id)]
    
    pod_name = (
        await session.execute(
            select(Job.pod_name)
            .where(Job.id == entity_id)
        )
    ).scalar_one_or_none()
    queries = [build_entity_query(entity_id)]
    if pod_name:
        queries.append(build_pod_query(pod_name))
    return queries


def parse_streams(payload: dict[str, Any]) -> list[LogLineContext]:
    if payload.get("status") != "success":
        return []
    
    lines: list[LogLineContext] = []
    for stream in payload.get("data", {}).get("result", []):
        labels = stream.get("stream", {})
        for nanoseconds, line in stream.get("values", []):
            lines.append(
                LogLineContext(
                    timestamp=datetime.fromtimestamp(int(nanoseconds) / NANOSECONDS_PER_SECOND, UTC),
                    labels=labels,
                    line=line[:MAXIMUM_LINE_LENGTH]
                )
            )
    return lines


async def query_logs(
    client: AsyncClient,
    base_url: str,
    queries: list[str],
    *,
    window_minutes: int,
    line_limit: int,
) -> LokiContext:
    end = datetime.now(UTC)
    start = end - timedelta(minutes=window_minutes)
    lines: list[LogLineContext] = []
    
    for query in queries:
        response = await client.get(
            f"{base_url}/loki/api/v1/query_range",
            params={
                "query": query,
                "start": str(int(start.timestamp() * NANOSECONDS_PER_SECOND)),
                "end": str(int(end.timestamp() * NANOSECONDS_PER_SECOND)),
                "limit": str(line_limit),
                "direction": "backward"
            }
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        lines.extend(parse_streams(payload))
    
    lines.sort(key=lambda entry: entry.timestamp, reverse=True)
    return LokiContext(queries=queries, window_minutes=window_minutes, lines=lines[:line_limit])
