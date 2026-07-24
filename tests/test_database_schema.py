import pytest

from videre.database.tables import SCHEMA_NAME, Base
from videre.models import GpuHealthState, JobState, NodeHealthState, SchedulerEventType


def test_every_table_lives_in_the_videre_schema() -> None:
    assert Base.metadata.schema == SCHEMA_NAME
    assert all(table.schema == SCHEMA_NAME for table in Base.metadata.tables.values())


def test_expected_tables_are_defined() -> None:
    assert {table.name for table in Base.metadata.tables.values()} == {
        "clusters", "nodes", "gpus", "jobs",
        "job_node_assignments", "scheduler_events", "failure_records",
    }


@pytest.mark.parametrize(
    ("table_name", "column_name", "enum_type"),
    [
        ("nodes", "health_state", NodeHealthState),
        ("gpus", "health_state", GpuHealthState),
        ("jobs", "lifecycle_state", JobState),
        ("scheduler_events", "type", SchedulerEventType),
    ],
)
def test_enum_columns_allow_exactly_their_python_enum(table_name, column_name, enum_type) -> None:
    table = Base.metadata.tables[f"{SCHEMA_NAME}.{table_name}"]
    constraint = next(c for c in table.constraints if c.name == f"ck_{table_name}_{column_name}_valid")
    expression = str(constraint.sqltext)
    for member in enum_type:
        assert f"'{member.value}'" in expression
    assert expression.count("'") == 2 * len(list(enum_type))


@pytest.mark.parametrize("table_name", ["scheduler_events", "failure_records"])
def test_append_only_tables_deduplicate_on_event_id(table_name) -> None:
    table = Base.metadata.tables[f"{SCHEMA_NAME}.{table_name}"]
    assert any(
        set(constraint.columns.keys()) == {"event_id"} for constraint in table.constraints
    ), "reprocessing a Kafka message must not create a duplicate row"
