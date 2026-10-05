"""
The bounded lookup done before the response cache is consulted to
determine if the cached response is still valid.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from videre.database.tables import FailureEntityTable

from .postgres_source import load_postgres_context


class EntityFingerprint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_type: FailureEntityTable
    entity_id: str
    health_state: str
    unresolved_failure_ids: tuple[str, ...]
    stable_evidence: str = ""

    @property
    def cache_fingerprint(self) -> str:
        return ":".join(
            (
                "evidence-v2",
                self.entity_type.value,
                self.entity_id,
                self.health_state,
                ",".join(self.unresolved_failure_ids),
                self.stable_evidence,
            )
        )


async def load_fingerprint(
    session: AsyncSession,
    entity_type: FailureEntityTable,
    entity_id: str
) -> EntityFingerprint | None:
    context = await load_postgres_context(session, entity_type, entity_id)
    if context is None:
        return None

    nodes = ([context.node] if context.node is not None else context.assigned_nodes)
    if entity_type == FailureEntityTable.JOB:
        assert context.job is not None
        health_state = context.job.lifecycle_state
    elif entity_type == FailureEntityTable.GPU:
        health_state = context.gpus[0].health_state
    else:
        assert context.node is not None
        health_state = context.node.health_state
    failures = context.unresolved_failures + context.recently_resolved_failures + context.correlated_failures
    
    # Health, placement and failure changes invalidate the cache; noisy telemetry and scheduler events use its TTL
    evidence = {
        "nodes": sorted((node.id, node.cluster_id, node.health_state) for node in nodes),
        "gpus": sorted((gpu.id, gpu.node_id, gpu.health_state) for gpu in context.gpus),
        "job": None if context.job is None else (
            context.job.id, context.job.cluster_id, context.job.lifecycle_state,
            context.job.failure_reason, sorted(context.job.assigned_node_ids),
        ),
        "failures": sorted((
            row.id, row.entity_type, row.entity_id, row.category, row.root_cause_tag,
            row.correlation_id, row.resolved_at is not None,
        ) for row in failures),
        "truncated_sections": sorted(
            section for section in context.truncated_sections if section != "scheduler_events"
        ),
    }
    return EntityFingerprint(
        entity_type=entity_type,
        entity_id=entity_id,
        health_state=health_state,
        unresolved_failure_ids=tuple(sorted(row.id for row in failures if row.resolved_at is None)),
        stable_evidence=json.dumps(evidence, sort_keys=True, separators=(",", ":")),
    )
