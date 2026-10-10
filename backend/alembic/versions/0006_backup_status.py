"""backup status (Phase 3): last local and off-site backup on app_settings

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('app_settings', sa.Column('last_backup_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('app_settings', sa.Column('last_backup_error', sa.Text(), nullable=True))
    op.add_column('app_settings', sa.Column('last_offsite_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('app_settings', sa.Column('last_offsite_error', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('app_settings', 'last_offsite_error')
    op.drop_column('app_settings', 'last_offsite_at')
    op.drop_column('app_settings', 'last_backup_error')
    op.drop_column('app_settings', 'last_backup_at')
