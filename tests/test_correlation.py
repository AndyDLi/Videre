from collections import Counter
from random import Random

import pytest
from pydantic import ValidationError

from videre.event_types import EventType
from videre.simulator.correlation import (
    CORRELATION_RULES,
    CorrelationEngine,
    CorrelationRule,
    EventTarget,
    ScheduledEvent,
)


def make_engine(**overrides) -> CorrelationEngine:
    defaults = {"random_generator": Random(42), "baseline_failure_probability": 1.0}
    return CorrelationEngine(**{**defaults, **overrides})


def _domain(event_type: EventType) -> str:
    capacity = {
        EventType.CAPACITY_FRAGMENTATION,
        EventType.CAPACITY_RESERVED_IDLE,
        EventType.NODE_DRAINED,
        EventType.NODE_HEALTH_CHECK_REMOVED,
    }
    if event_type in capacity:
        return "capacity"
    return event_type.value.split(".", 1)[0]


def test_no_duplicate_trigger_downstream_pairs() -> None:
    """No trigger-downstream pair is declared twice, so no correlation is double-weighted."""

    pairs = [(rule.trigger, rule.downstream) for rule in CORRELATION_RULES]
    assert len(pairs) == len(set(pairs))


def test_no_rule_triggers_itself() -> None:
    """No rule points an event at itself, which would be a trivial infinite cascade."""

    assert all(rule.trigger is not rule.downstream for rule in CORRELATION_RULES)


def test_rules_span_every_source_domain() -> None:
    """Triggers originate from the GPU, node, and capacity domains alike."""

    trigger_domains = {_domain(rule.trigger) for rule in CORRELATION_RULES}
    assert trigger_domains == {"gpu", "node", "capacity"}


def test_rules_cover_the_intended_cross_domain_transitions() -> None:
    """Every intended cross-domain transition, such as GPU to job, has at least one rule."""

    transitions = {(_domain(rule.trigger), _domain(rule.downstream)) for rule in CORRELATION_RULES}
    for expected in [("gpu", "job"), ("gpu", "gpu"), ("node", "node"), ("node", "job"),
                     ("node", "capacity"), ("capacity", "job")]:
        assert expected in transitions


def test_multi_hop_cascade_is_possible() -> None:
    """Some downstream event is itself a trigger, so cascades can run more than one hop."""

    triggers = {rule.trigger for rule in CORRELATION_RULES}
    downstreams = {rule.downstream for rule in CORRELATION_RULES}
    assert triggers & downstreams


def test_baseline_weights_produce_expected_skew() -> None:
    """Weighted selection makes common failures far more frequent than rare ones over many draws."""

    engine = make_engine(rules=[])
    target = EventTarget(node_id="node-01")
    counts: Counter[EventType] = Counter()
    for _ in range(20000):
        event = engine.maybe_emit_baseline(target, now=0.0)
        assert event is not None
        counts[event.event_type] += 1
        engine.fire_due(0.0)
    assert counts[EventType.GPU_THERMAL_THROTTLING] > counts[EventType.GPU_ECC_UNCORRECTABLE] * 5


def test_baseline_injection_is_occasional_and_uncorrelated() -> None:
    """Baseline failures fire only sometimes, each at depth zero with its own correlation id."""

    engine = CorrelationEngine(rules=[], baseline_failure_probability=0.1, random_generator=Random(1))
    target = EventTarget(node_id="node-01")
    emitted = [engine.maybe_emit_baseline(target, now=0.0) for _ in range(1000)]
    events = [event for event in emitted if event is not None]
    assert 0 < len(events) < 1000
    assert all(event.depth == 0 for event in events)
    assert len({event.correlation_id for event in events}) == len(events)


def test_correlated_event_scheduled_within_delay_window() -> None:
    """A triggered event fires inside its configured delay window, inheriting the correlation id and node."""

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
    assert event.correlation_id == "cascade-1"
    assert event.depth == 1
    assert 100.0 + 30.0 <= event.fire_at <= 100.0 + 90.0
    assert event.target.node_id == "node-01"


def test_cascade_depth_is_capped() -> None:
    """A self-perpetuating rule still terminates at the configured cascade depth."""

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
    """One event spawns at most the configured number of downstream events, however many rules match."""

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


def test_correlation_rule_rejects_invalid_config() -> None:
    """A rule is rejected if its probability is out of range or its delay window is inverted."""

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
