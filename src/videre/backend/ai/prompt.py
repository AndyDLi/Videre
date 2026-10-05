"""
Turns FailureContext into a prompt.
"""

from __future__ import annotations

import json

from .context import FailureContext

SYSTEM_INSTRUCTION = (
    "You are an operations assistant for a GPU training cluster. "
    "You are given the current state of one entity: its database records, recent metric trends, "
    "and recent log lines. Identify the most likely root cause of its current state and give "
    "concrete next debugging steps. Ground every claim in the supplied context and refer to entities "
    "by the ids given. If a data source is listed as unavailable, or the context is too thin to "
    "support a conclusion, say so plainly instead of inventing detail. "
    "For jobs, GPUs on assigned nodes are surrounding evidence; exact GPU assignment is unknown. "
    "A shared correlation ID identifies a simulator incident; correlation and time ordering are "
    "not proof of causality or its direction. Distinguish observed facts from hypotheses, "
    "and state uncertainty when evidence is incomplete."
)

TRUNCATION_MARKER = "\n\n[context truncated to fit the prompt budget]"

# (log line limit, metric series limit, compact database evidence)
_REDUCTION_STEPS: tuple[tuple[int | None, int | None, bool], ...] = (
    (None, None, False),
    (10, None, False),
    (0, 10, False),
    (0, 0, False),
    (0, 0, True),
)


def _records(context: FailureContext, compact: bool) -> str:
    assert context.postgres is not None
    records = context.postgres.model_dump(mode="json", exclude_none=True)
    if compact:
        records["unresolved_failures"] = records["unresolved_failures"][:5]
        records["correlated_failures"] = records["correlated_failures"][:5]
        records["recently_resolved_failures"] = []
        records["scheduler_events"] = []
        gpus = sorted(records["gpus"], key=lambda gpu: (gpu["id"] != context.entity_id, gpu["id"]))
        records["gpus"] = gpus[:4]
        records["assigned_nodes"] = [
            {key: node[key] for key in ("id", "cluster_id", "health_state")}
            for node in records["assigned_nodes"]
        ]
        if "job" in records and "failure_reason" in records["job"]:
            records["job"]["failure_reason"] = records["job"]["failure_reason"][:500]

    prioritized = {key: records.pop(key) for key in
        ("unresolved_failures", "correlated_failures")}
    return json.dumps({**prioritized, **records}, ensure_ascii=False, separators=(",", ":"))


def _render(
    context: FailureContext, *, log_limit: int | None, series_limit: int | None, compact: bool,
) -> str:
    sections = [
        f"ENTITY: {context.entity_type.value} {context.entity_id}",
        f"CONTEXT GENERATED AT: {context.generated_at.isoformat()}",
    ]
    
    if context.degraded_sources:
        sections.append(
            "UNAVAILABLE DATA SOURCES (do not speculate about what they would have shown): "
            + ", ".join(context.degraded_sources)
        )
    
    if context.prometheus is not None and context.prometheus.scope == "deployment":
        sections.append(
            "METRIC SCOPE: deployment aggregates, including cluster-labelled series; "
            "not per-job measurements or proof about this job."
        )
    if context.postgres is not None:
        if context.postgres.truncated_sections:
            sections.append("INCOMPLETE EVIDENCE: capped sections: " + ", ".join(context.postgres.truncated_sections))
        if compact:
            sections.append("INCOMPLETE EVIDENCE: evidence reduced to fit the prompt budget.")
        sections.append("CLUSTER RECORDS:\n" + _records(context, compact))
    
    if context.prometheus is not None:
        series = context.prometheus.series if series_limit is None else context.prometheus.series[:series_limit]
        rendered = "\n".join(
            f"{summary.metric}{summary.labels} "
            f"latest={summary.latest} min={summary.minimum} max={summary.maximum} avg={summary.average}"
            for summary in series
        )
        sections.append(
            f"METRIC TRENDS OVER THE LAST {context.prometheus.window_minutes} MINUTES:\n"
            + (rendered or "(no series returned)")
        )
    
    if context.logs is not None:
        lines = context.logs.lines if log_limit is None else context.logs.lines[:log_limit]
        rendered = "\n".join(
            f"{line.timestamp.isoformat()} {line.labels.get('pod', '')} {line.line}" for line in lines
        )
        sections.append(
            f"RECENT LOG LINES (last {context.logs.window_minutes} minutes): \n"
            + (rendered or "(no matching log lines)")
        )
    
    return "\n\n".join(sections)


def build_prompt(context: FailureContext, *, maximum_characters: int) -> str:
    prompt = ""
    for log_limit, series_limit, compact in _REDUCTION_STEPS:
        prompt = _render(context, log_limit=log_limit, series_limit=series_limit, compact=compact)
        if len(prompt) <= maximum_characters:
            return prompt
    
    return prompt[: max(maximum_characters - len(TRUNCATION_MARKER), 0)] + TRUNCATION_MARKER
