from collections import Counter
from random import Random

import pytest
from pydantic import ValidationError

from videre.simulator.correlation import (
    CorrelationEngine,
    CorrelationRule,
    EventTarget,
    ScheduledEvent,
)
from videre.simulator.event_types import EventType


def make_engine(**overrides) -> CorrelationEngine:
    defaults = {"random_generator": Random(42), "baseline_failure_probability": 1.0}
    return CorrelationEngine(**{**defaults, **overrides})


# --- Weighted baseline ---


def test_baseline_weights_produce_expected_skew() -> None:
    engine = make_engine(rules=[])  # isolate weighting from correlation
    target = EventTarget(node_id="node-01")
    counts: Counter[EventType] = Counter()
    for _ in range(20000):
        event = engine.maybe_emit_baseline(target, now=0.0)
        assert event is not None
        counts[event.event_type] += 1
        engine.fire_due(0.0)
    assert counts[EventType.GPU_THERMAL_THROTTLING] > counts[EventType.GPU_ECC_UNCORRECTABLE] * 5


# --- Baseline injection is occasional and uncorrelated ---


def test_baseline_injection_is_occasional_and_uncorrelated() -> None:
    engine = CorrelationEngine(rules=[], baseline_failure_probability=0.1, random_generator=Random(1))
    target = EventTarget(node_id="node-01")
    emitted = [engine.maybe_emit_baseline(target, now=0.0) for _ in range(1000)]
    events = [event for event in emitted if event is not None]
    assert 0 < len(events) < 1000
    assert all(event.depth == 0 for event in events)
    assert len({event.correlation_id for event in events}) == len(events)


# --- Triggered correlated event is within configured window ---


def test_correlated_event_scheduled_within_delay_window() -> None:
    rule = CorrelationRule(
        trigger=EventType.GPU_THERMAL_THROTTLING,
        downstream=EventType.JOB_NCCL_TIMEOUT,
        probability=1.0,
        min_delay_seconds=30.0,
        max_delay_seconds=90.0,
    )
    engine = CorrelationEngine(rules=[rule], random_generator=Random(0))
    engine.schedule(
        ScheduledEvent(
            event_type=EventType.GPU_THERMAL_THROTTLING,
            target=EventTarget(node_id="node-01"),
            fire_at=100.0,
            correlation_id="cascade-1",
            depth=0,
        )
    )
    engine.fire_due(now=100.0)
    downstream = engine.fire_due(now=1000.0)
    assert len(downstream) == 1
    event = downstream[0]
    assert event.event_type is EventType.JOB_NCCL_TIMEOUT
    assert event.correlation_id == "cascade-1"  # inherited correlation ID
    assert event.depth == 1
    assert 100.0 + 30.0 <= event.fire_at <= 100.0 + 90.0
    assert event.target.node_id == "node-01"    # same node ID as the trigger event


# --- Cascade and fanout limits ---


def test_cascade_depth_is_capped() -> None:
    rule = CorrelationRule(
        trigger=EventType.GPU_THERMAL_THROTTLING,
        downstream=EventType.GPU_THERMAL_THROTTLING,
        probability=1.0,
        min_delay_seconds=1.0,
        max_delay_seconds=1.0,
    )
    engine = CorrelationEngine(
        rules=[rule], max_cascade_depth=3, max_fanout_per_event=1, random_generator=Random(0)
    )
    engine.schedule(
        ScheduledEvent(EventType.GPU_THERMAL_THROTTLING, EventTarget(node_id="node-01"), 0.0, "c", 0)
    )
    fired: list[ScheduledEvent] = []
    for now in range(100):
        fired.extend(engine.fire_due(float(now)))
    assert max(event.depth for event in fired) <= 3
    assert engine.pending_count == 0


def test_fanout_per_event_is_capped() -> None:
    trigger = EventType.GPU_THERMAL_THROTTLING
    downstreams = [EventType.JOB_NCCL_TIMEOUT, EventType.JOB_OOM_KILL, EventType.JOB_STRAGGLER]
    rules = [
        CorrelationRule(
            trigger=trigger, downstream=downstream, probability=1.0,
            min_delay_seconds=1.0, max_delay_seconds=1.0,
        )
        for downstream in downstreams
    ]
    engine = CorrelationEngine(rules=rules, max_fanout_per_event=2, random_generator=Random(0))
    engine.schedule(ScheduledEvent(trigger, EventTarget(node_id="node-01"), 0.0, "c", 0))
    engine.fire_due(now=0.0)
    assert len(engine.fire_due(now=10.0)) == 2


# --- Validate rule config ---


def test_correlation_rule_rejects_invalid_config() -> None:
    with pytest.raises(ValidationError):
        CorrelationRule(
            trigger=EventType.GPU_XID_ERROR, downstream=EventType.JOB_OOM_KILL,
            probability=1.5, min_delay_seconds=1.0, max_delay_seconds=1.0,
        )
    with pytest.raises(ValidationError):
        CorrelationRule(
            trigger=EventType.GPU_XID_ERROR, downstream=EventType.JOB_OOM_KILL,
            probability=0.5, min_delay_seconds=90.0, max_delay_seconds=30.0,
        )
