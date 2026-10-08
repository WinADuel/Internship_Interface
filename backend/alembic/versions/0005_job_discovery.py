"""job discovery (Phase 2): postings, watch companies, discovery settings

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08 10:47:04.033456

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


POSTING_SOURCE_VALUES = (
    'simplify', 'vanshb03', 'list', 'greenhouse', 'lever', 'ashby', 'workday', 'pasted',
)
POSTING_STATE_VALUES = ('new', 'saved', 'dismissed', 'applied')
WATCH_ATS_VALUES = ('greenhouse', 'lever', 'ashby', 'workday')

# create_type=False: the types are created and dropped explicitly below.
posting_source = postgresql.ENUM(*POSTING_SOURCE_VALUES, name='posting_source', create_type=False)
posting_state = postgresql.ENUM(*POSTING_STATE_VALUES, name='posting_state', create_type=False)
watch_ats = postgresql.ENUM(*WATCH_ATS_VALUES, name='watch_ats', create_type=False)

NEW_ENUMS = (posting_source, posting_state, watch_ats)

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    for enum_type in NEW_ENUMS:
        enum_type.create(op.get_bind(), checkfirst=True)

    op.create_table('watch_companies',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('ats', watch_ats, nullable=False),
    sa.Column('board_token', sa.Text(), nullable=False),
    sa.Column('careers_url', sa.Text(), nullable=False),
    sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ats', 'board_token', name='uq_watch_companies_ats_board_token')
    )
    op.create_table('postings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', posting_source, nullable=False),
    sa.Column('source_key', sa.Text(), nullable=False),
    sa.Column('company', sa.Text(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('locations', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('url_key', sa.Text(), nullable=False),
    sa.Column('terms', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
    sa.Column('category', sa.Text(), nullable=True),
    sa.Column('sponsorship', sa.Text(), nullable=True),
    sa.Column('date_posted', sa.DateTime(timezone=True), nullable=True),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('closed', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('state', posting_state, server_default='new', nullable=False),
    sa.Column('state_changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('application_id', sa.Integer(), nullable=True),
    sa.Column('watch_company_id', sa.Integer(), nullable=True),
    sa.Column('claude_score', sa.Integer(), nullable=True),
    sa.Column('claude_note', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['watch_company_id'], ['watch_companies.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'source_key', name='uq_postings_source_source_key')
    )
    op.create_index(op.f('ix_postings_application_id'), 'postings', ['application_id'], unique=False)
    # Functional index for case-insensitive company + title de-duplication.
    op.create_index('ix_postings_lower_company_lower_title', 'postings', [sa.literal_column('lower(company)'), sa.literal_column('lower(title)')], unique=False)
    op.create_index(op.f('ix_postings_state'), 'postings', ['state'], unique=False)
    op.create_index(op.f('ix_postings_url_key'), 'postings', ['url_key'], unique=False)
    op.create_index(op.f('ix_postings_watch_company_id'), 'postings', ['watch_company_id'], unique=False)
    op.add_column('app_settings', sa.Column('discovery_list_urls', postgresql.ARRAY(sa.Text()), server_default=sa.text('\'{"https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json","https://raw.githubusercontent.com/vanshb03/Summer2027-Internships/dev/.github/scripts/listings.json"}\'::text[]'), nullable=False))
    op.add_column('app_settings', sa.Column('discovery_terms', postgresql.ARRAY(sa.Text()), server_default=sa.text('\'{"Summer 2027"}\'::text[]'), nullable=False))
    op.add_column('app_settings', sa.Column('discovery_categories', postgresql.ARRAY(sa.Text()), server_default=sa.text('\'{"Software","AI/ML/Data"}\'::text[]'), nullable=False))
    op.add_column('app_settings', sa.Column('discovery_include_keywords', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False))
    op.add_column('app_settings', sa.Column('discovery_watchlist_keywords', postgresql.ARRAY(sa.Text()), server_default=sa.text('\'{"intern","internship","co-op"}\'::text[]'), nullable=False))
    op.add_column('app_settings', sa.Column('discovery_exclude_keywords', postgresql.ARRAY(sa.Text()), server_default=sa.text('\'{"senior","staff","principal","phd"}\'::text[]'), nullable=False))
    op.add_column('app_settings', sa.Column('discovery_locations', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False))
    op.add_column('app_settings', sa.Column('discovery_hide_no_sponsorship', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('app_settings', sa.Column('discovery_scan_hours', sa.Integer(), server_default='6', nullable=False))
    op.add_column('app_settings', sa.Column('discovery_list_etags', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column('app_settings', sa.Column('last_scan_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('app_settings', sa.Column('last_scan_error', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('app_settings', 'last_scan_error')
    op.drop_column('app_settings', 'last_scan_at')
    op.drop_column('app_settings', 'discovery_list_etags')
    op.drop_column('app_settings', 'discovery_scan_hours')
    op.drop_column('app_settings', 'discovery_hide_no_sponsorship')
    op.drop_column('app_settings', 'discovery_locations')
    op.drop_column('app_settings', 'discovery_exclude_keywords')
    op.drop_column('app_settings', 'discovery_watchlist_keywords')
    op.drop_column('app_settings', 'discovery_include_keywords')
    op.drop_column('app_settings', 'discovery_categories')
    op.drop_column('app_settings', 'discovery_terms')
    op.drop_column('app_settings', 'discovery_list_urls')
    op.drop_index(op.f('ix_postings_watch_company_id'), table_name='postings')
    op.drop_index(op.f('ix_postings_url_key'), table_name='postings')
    op.drop_index(op.f('ix_postings_state'), table_name='postings')
    op.drop_index('ix_postings_lower_company_lower_title', table_name='postings')
    op.drop_index(op.f('ix_postings_application_id'), table_name='postings')
    op.drop_table('postings')
    op.drop_table('watch_companies')
    for enum_type in reversed(NEW_ENUMS):
        enum_type.drop(op.get_bind(), checkfirst=True)
