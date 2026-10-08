"""outreach contacts (Phase 1b): contacts, contact history, research queue,
app settings, claude tokens

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-07 23:54:42.084614

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


CONTACT_KIND_VALUES = ('professor', 'company')
EMAIL_CONFIDENCE_VALUES = ('found', 'pattern_guess', 'not_found')
CONTACT_STATUS_VALUES = (
    'to_contact', 'sent', 'followed_up', 'replied', 'meeting', 'accepted', 'declined',
)
CONTACT_ORIGIN_VALUES = ('claude', 'manual')
QUEUE_KIND_VALUES = ('professor_person', 'professor_search', 'company_contacts')
QUEUE_STATE_VALUES = ('pending', 'done', 'failed')

# create_type=False everywhere: the new types are created/dropped explicitly
# below (contact_status is shared by two tables), and application_priority
# already exists from 0002 and is reused, never created or dropped here.
contact_kind = postgresql.ENUM(*CONTACT_KIND_VALUES, name='contact_kind', create_type=False)
email_confidence = postgresql.ENUM(*EMAIL_CONFIDENCE_VALUES, name='email_confidence', create_type=False)
contact_status = postgresql.ENUM(*CONTACT_STATUS_VALUES, name='contact_status', create_type=False)
contact_origin = postgresql.ENUM(*CONTACT_ORIGIN_VALUES, name='contact_origin', create_type=False)
queue_kind = postgresql.ENUM(*QUEUE_KIND_VALUES, name='queue_kind', create_type=False)
queue_state = postgresql.ENUM(*QUEUE_STATE_VALUES, name='queue_state', create_type=False)
application_priority = postgresql.ENUM('low', 'medium', 'high', name='application_priority', create_type=False)

NEW_ENUMS = (contact_kind, email_confidence, contact_status, contact_origin, queue_kind, queue_state)

# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    for enum_type in NEW_ENUMS:
        enum_type.create(op.get_bind(), checkfirst=True)

    op.create_table('app_settings',
    sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('outreach_profile', sa.Text(), server_default='', nullable=False),
    sa.Column('nudge_unsent_days', sa.Integer(), server_default='5', nullable=False),
    sa.Column('nudge_followup_days', sa.Integer(), server_default='10', nullable=False),
    sa.Column('nudge_gone_quiet_days', sa.Integer(), server_default='10', nullable=False),
    sa.Column('nudge_replied_stale_days', sa.Integer(), server_default='14', nullable=False),
    sa.Column('claude_job_max_items', sa.Integer(), server_default='8', nullable=False),
    sa.Column('backup_sheet_id', sa.Text(), nullable=True),
    sa.Column('last_sheet_sync_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_sheet_sync_error', sa.Text(), nullable=True),
    sa.CheckConstraint('id = 1', name='app_settings_single_row'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('claude_tokens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.Text(), nullable=False),
    sa.Column('token_prefix', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_table('contacts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', contact_kind, nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('organization', sa.Text(), nullable=False),
    sa.Column('department', sa.Text(), nullable=True),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('lab_name', sa.Text(), nullable=True),
    sa.Column('email', sa.Text(), nullable=True),
    sa.Column('email_confidence', email_confidence, nullable=False),
    sa.Column('website_url', sa.Text(), nullable=True),
    sa.Column('profile_url', sa.Text(), nullable=True),
    sa.Column('application_id', sa.Integer(), nullable=True),
    sa.Column('relevance_note', sa.Text(), nullable=True),
    sa.Column('research_summary', sa.Text(), nullable=True),
    sa.Column('recent_work', sa.Text(), nullable=True),
    sa.Column('sources', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('draft_subject', sa.Text(), nullable=True),
    sa.Column('draft_body', sa.Text(), nullable=True),
    sa.Column('draft_edited', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('followup_subject', sa.Text(), nullable=True),
    sa.Column('followup_body', sa.Text(), nullable=True),
    sa.Column('followup_edited', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('draft_ready_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', contact_status, nullable=False),
    sa.Column('closed_reason', sa.Text(), nullable=True),
    sa.Column('priority', application_priority, nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('followed_up_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('replied_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('meeting_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('nudge_snoozed_until', sa.Date(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('origin', contact_origin, nullable=False),
    sa.Column('archived', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_contacts_application_id'), 'contacts', ['application_id'], unique=False)
    op.create_table('research_queue',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', queue_kind, nullable=False),
    sa.Column('request_text', sa.Text(), nullable=False),
    sa.Column('application_id', sa.Integer(), nullable=True),
    sa.Column('target_count', sa.Integer(), server_default='1', nullable=False),
    sa.Column('state', queue_state, nullable=False),
    sa.Column('result_note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_research_queue_application_id'), 'research_queue', ['application_id'], unique=False)
    op.create_table('contact_status_history',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('contact_id', sa.Integer(), nullable=False),
    sa.Column('old_status', contact_status, nullable=True),
    sa.Column('new_status', contact_status, nullable=False),
    sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_contact_status_history_contact_id'), 'contact_status_history', ['contact_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_contact_status_history_contact_id'), table_name='contact_status_history')
    op.drop_table('contact_status_history')
    op.drop_index(op.f('ix_research_queue_application_id'), table_name='research_queue')
    op.drop_table('research_queue')
    op.drop_index(op.f('ix_contacts_application_id'), table_name='contacts')
    op.drop_table('contacts')
    op.drop_table('claude_tokens')
    op.drop_table('app_settings')
    # application_priority belongs to 0002 and is left in place.
    for enum_type in reversed(NEW_ENUMS):
        enum_type.drop(op.get_bind(), checkfirst=True)
