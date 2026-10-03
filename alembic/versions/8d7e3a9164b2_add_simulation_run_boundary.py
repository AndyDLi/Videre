"""Add a durable simulation run boundary to clusters.

Revision ID: 8d7e3a9164b2
Revises: c41f8a7d2b95
"""
from alembic import op
import sqlalchemy as sa

revision = "8d7e3a9164b2"
down_revision = "c41f8a7d2b95"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clusters", sa.Column("simulation_run_id", sa.String(36), nullable=True), schema="videre")
    op.add_column(
        "clusters", sa.Column("simulation_run_started_at", sa.DateTime(timezone=True), nullable=True), schema="videre",
    )
    op.create_check_constraint(
        op.f("ck_clusters_simulation_run_paired"), "clusters",
        "(simulation_run_id IS NULL) = (simulation_run_started_at IS NULL)", schema="videre",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_clusters_simulation_run_paired"), "clusters", type_="check", schema="videre")
    op.drop_column("clusters", "simulation_run_started_at", schema="videre")
    op.drop_column("clusters", "simulation_run_id", schema="videre")
