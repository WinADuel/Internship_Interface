"""inbox ranking (Phase 5): ranking preferences and the last re-score time on
app_settings; local score, reasons and Claude-scored time on postings; the
Best-match index

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RANKING_LISTS = (
    'ranking_role_keywords',
    'ranking_skill_keywords',
    'ranking_preferred_locations',
    'ranking_preferred_companies',
    'ranking_avoid_companies',
    'ranking_dealbreaker_keywords',
)

# A copy, not an import (app/services/discovery/ranking.py NEUTRAL_SCORE):
# with no preferences set yet, every posting's local score is this.
NEUTRAL_SCORE = 50


def upgrade() -> None:
    """Upgrade schema."""
    for name in RANKING_LISTS:
        op.add_column(
            'app_settings',
            sa.Column(name, postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
        )
    op.add_column(
        'app_settings',
        sa.Column('ranking_claude_daily_limit', sa.Integer(), server_default='40', nullable=False),
    )
    op.add_column('app_settings', sa.Column('ranking_updated_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('app_settings', sa.Column('last_rescore_at', sa.DateTime(timezone=True), nullable=True))

    op.add_column('postings', sa.Column('local_score', sa.Integer(), nullable=True))
    op.add_column(
        'postings',
        sa.Column('local_reasons', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.add_column('postings', sa.Column('claude_scored_at', sa.DateTime(timezone=True), nullable=True))
    # Existing postings: no preferences exist yet, so they all score neutral.
    op.execute(f"UPDATE postings SET local_score = {NEUTRAL_SCORE}")
    op.create_index(
        'ix_postings_inbox_best',
        'postings',
        [
            sa.text('coalesce(claude_score, local_score) DESC NULLS LAST'),
            sa.text('coalesce(date_posted, first_seen_at) DESC'),
            sa.text('id DESC'),
        ],
        unique=False,
        postgresql_where=sa.text("state = 'new'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_postings_inbox_best', table_name='postings', postgresql_where=sa.text("state = 'new'"))
    op.drop_column('postings', 'claude_scored_at')
    op.drop_column('postings', 'local_reasons')
    op.drop_column('postings', 'local_score')
    op.drop_column('app_settings', 'last_rescore_at')
    op.drop_column('app_settings', 'ranking_updated_at')
    op.drop_column('app_settings', 'ranking_claude_daily_limit')
    for name in reversed(RANKING_LISTS):
        op.drop_column('app_settings', name)
