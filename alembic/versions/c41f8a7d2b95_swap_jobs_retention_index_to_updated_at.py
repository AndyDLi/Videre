"""swap jobs retention index to updated_at

Revision ID: c41f8a7d2b95
Revises: f902a47f1533
Create Date: 2026-08-05 19:40:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c41f8a7d2b95'
down_revision: Union[str, Sequence[str], None] = 'f902a47f1533'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Retention prunes jobs by updated_at, so index that instead of completed_at."""
    op.create_index('ix_jobs_updated_at', 'jobs', ['updated_at'], unique=False, schema='videre')
    op.drop_index('ix_jobs_completed_at', table_name='jobs', schema='videre')


def downgrade() -> None:
    """Restore the completed_at index."""
    op.create_index('ix_jobs_completed_at', 'jobs', ['completed_at'], unique=False, schema='videre')
    op.drop_index('ix_jobs_updated_at', table_name='jobs', schema='videre')
