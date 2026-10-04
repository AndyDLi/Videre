import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from videre.database.tables import SCHEMA_NAME, Base
from videre.models import GpuHealthState, JobState, NodeHealthState, SchedulerEventType


def test_every_table_lives_in_the_videre_schema() -> None:
    """Every table is namespaced under the dedicated videre schema rather than public."""

    assert Base.metadata.schema == SCHEMA_NAME
    assert all(table.schema == SCHEMA_NAME for table in Base.metadata.tables.values())


def test_expected_tables_are_defined() -> None:
    """The schema defines exactly the seven tables the pipeline persists to."""

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
    """Each enum column's CHECK constraint admits every Python enum member and nothing beyond them."""

    table = Base.metadata.tables[f"{SCHEMA_NAME}.{table_name}"]
    constraint = next(c for c in table.constraints if c.name == f"ck_{table_name}_{column_name}_valid")
    expression = str(constraint.sqltext)
    for member in enum_type:
        assert f"'{member.value}'" in expression
    assert expression.count("'") == 2 * len(list(enum_type))


@pytest.mark.parametrize(
    ("table_name", "column_name"),
    [
        ("jobs", "updated_at"),
        ("failure_records", "detected_at"),
        ("scheduler_events", "timestamp"),
    ],
)
def test_every_column_retention_prunes_by_is_indexed(table_name, column_name) -> None:
    """Each column the retention sweep filters on carries an index, so the hourly pass stays cheap."""

    table = Base.metadata.tables[f"{SCHEMA_NAME}.{table_name}"]
    indexed = {column.name for index in table.indexes for column in index.columns}
    assert column_name in indexed


@pytest.mark.parametrize("table_name", ["scheduler_events", "failure_records"])
def test_append_only_tables_deduplicate_on_event_id(table_name) -> None:
    """Append-only tables carry a unique event_id, so Kafka redelivery cannot duplicate a row."""

    table = Base.metadata.tables[f"{SCHEMA_NAME}.{table_name}"]
    assert any(
        set(constraint.columns.keys()) == {"event_id"} for constraint in table.constraints
    ), "reprocessing a Kafka message must not create a duplicate row"

def test_cluster_has_a_paired_nullable_run_boundary():
    table = Base.metadata.tables[f"{SCHEMA_NAME}.clusters"]
    assert {"simulation_run_id", "simulation_run_started_at"} <= set(table.columns.keys())
    assert table.c.simulation_run_id.nullable and table.c.simulation_run_started_at.nullable
    assert any(c.name == "ck_clusters_simulation_run_paired" for c in table.constraints)


@pytest.mark.parametrize("has_id,has_start", [(False, False), (True, True), (True, False), (False, True)])
async def test_database_enforces_paired_run_boundary(session, has_id, has_start):
    from datetime import UTC, datetime

    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    values = {
        "run_id": "00000000-0000-4000-8000-000000000001" if has_id else None,
        "started_at": datetime.now(UTC) if has_start else None,
    }
    statement = text(
        "INSERT INTO videre.clusters (id, name, simulation_run_id, simulation_run_started_at) "
        "VALUES ('constraint-test', 'constraint-test', :run_id, :started_at)"
    )
    if has_id != has_start:
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await session.execute(statement, values)
    else:
        await session.execute(statement, values)


def test_required_database_cannot_silently_skip():
    env = dict(os.environ, VIDERE_REQUIRE_DATABASE_TESTS="1")
    env.pop("VIDERE_TEST_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=short",
         "tests/test_database_schema.py::test_database_enforces_paired_run_boundary[False-False]"],
        cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0, result.stdout
    assert "VIDERE_TEST_DATABASE_URL is required" in result.stdout, result.stdout


async def test_database_session_uses_application_privileges(session):
    role = (await session.execute(text(
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
        "FROM pg_roles WHERE rolname = current_user"
    ))).one()
    assert not any(role)
    schema = (await session.execute(text(
        "SELECT has_schema_privilege(current_user, 'videre', 'USAGE'), "
        "has_schema_privilege(current_user, 'videre', 'CREATE'), "
        "pg_get_userbyid(nspowner) = current_user FROM pg_namespace WHERE nspname = 'videre'"
    ))).one()
    assert tuple(schema) == (True, False, False)
    for table in Base.metadata.sorted_tables:
        owner = await session.scalar(text(
            "SELECT pg_get_userbyid(relowner) = current_user FROM pg_class "
            "WHERE oid = CAST(:table AS regclass)"
        ), {"table": table.fullname})
        assert owner is False, table.fullname
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            allowed = await session.scalar(text(
                "SELECT has_table_privilege(current_user, :table, :privilege)"
            ), {"table": table.fullname, "privilege": privilege})
            assert allowed, (table.fullname, privilege)
