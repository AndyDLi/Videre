"""
Turns FailureContext into a prompt.
"""

from __future__ import annotations

from .context import FailureContext

SYSTEM_INSTRUCTION = (
    "You are an operations assistant for a GPU training cluster. "
    "You are given the current state of one entity: its database records, recent metric trends, "
    "and recent log lines. Identify the most likely root cause of its current state and give "
    "concrete next debugging steps. Ground every claim in the supplied context and refer to entities "
    "by the ids given. If a data source is listed as unavailable, or the context is too thin to "
    "support a conclusion, say so plainly instead of inventing detail."
)

TRUNCATION_MARKER = "\n\n[context truncated to fit the prompt budget]"

# (log line limit, metric series limit)
_REDUCTION_STEPS: tuple[tuple[int | None, int | None], ...] = (
    (None, None),
    (10, None),
    (0, 10),
    (0, 0),
)


def _render(context: FailureContext, *, log_limit: int | None, series_limit: int | None) -> str:
    sections = [
        f"ENTITY: {context.entity_type.value} {context.entity_id}",
        f"CONTEXT GENERATED AT: {context.generated_at.isoformat()}",
    ]
    
    if context.degraded_sources:
        sections.append(
            "UNAVAILABLE DATA SOURCES (do not speculate about what they would have shown): "
            + ", ".join(context.degraded_sources)
        )
    
    if context.postgres is not None:
        sections.append("CLUSTER RECORDS:\n" + context.postgres.model_dump_json(exclude_none=True))
    
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
    for log_limit, series_limit in _REDUCTION_STEPS:
        prompt = _render(context, log_limit=log_limit, series_limit=series_limit)
        if len(prompt) <= maximum_characters:
            return prompt
    
    return prompt[: max(maximum_characters - len(TRUNCATION_MARKER), 0)] + TRUNCATION_MARKER
