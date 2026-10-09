"""gmail sync (Phase 6): email_suggestions and the Gmail settings

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-09 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SUGGESTION_KIND_VALUES = (
    'confirmation', 'rejection', 'interview', 'assessment', 'offer',
    'contact_reply', 'contact_sent', 'new_application',
)
DIRECTION_VALUES = ('inbound', 'sent')
STATE_VALUES = ('pending', 'accepted', 'dismissed', 'stale', 'auto_applied')

# create_type=False: the types are created and dropped explicitly below.
email_suggestion_kind = postgresql.ENUM(*SUGGESTION_KIND_VALUES, name='email_suggestion_kind', create_type=False)
email_direction = postgresql.ENUM(*DIRECTION_VALUES, name='email_direction', create_type=False)
email_suggestion_state = postgresql.ENUM(*STATE_VALUES, name='email_suggestion_state', create_type=False)

NEW_ENUMS = (email_suggestion_kind, email_direction, email_suggestion_state)


def upgrade() -> None:
    """Upgrade schema."""
    for enum_type in NEW_ENUMS:
        enum_type.create(op.get_bind(), checkfirst=True)

    op.create_table('email_suggestions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('gmail_message_id', sa.Text(), nullable=False),
    sa.Column('gmail_thread_id', sa.Text(), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('direction', email_direction, nullable=False),
    sa.Column('from_name', sa.Text(), server_default='', nullable=False),
    sa.Column('from_email', sa.Text(), server_default='', nullable=False),
    sa.Column('subject', sa.Text(), server_default='', nullable=False),
    sa.Column('snippet', sa.Text(), server_default='', nullable=False),
    sa.Column('kind', email_suggestion_kind, nullable=False),
    sa.Column('application_id', sa.Integer(), nullable=True),
    sa.Column('contact_id', sa.Integer(), nullable=True),
    sa.Column('proposed_company', sa.Text(), nullable=True),
    sa.Column('proposed_role', sa.Text(), nullable=True),
    sa.Column('state', email_suggestion_state, server_default='pending', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('gmail_message_id')
    )
    op.create_index(op.f('ix_email_suggestions_application_id'), 'email_suggestions', ['application_id'], unique=False)
    op.create_index(op.f('ix_email_suggestions_contact_id'), 'email_suggestions', ['contact_id'], unique=False)
    op.create_index('ix_email_suggestions_state_received_at', 'email_suggestions', ['state', 'received_at'], unique=False)

    op.add_column('app_settings', sa.Column('gmail_sync_enabled', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('app_settings', sa.Column('gmail_sync_minutes', sa.Integer(), server_default='30', nullable=False))
    op.add_column('app_settings', sa.Column('gmail_lookback_days', sa.Integer(), server_default='30', nullable=False))
    op.add_column('app_settings', sa.Column('gmail_auto_apply', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('app_settings', sa.Column('gmail_last_sync_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('app_settings', sa.Column('gmail_last_error', sa.Text(), nullable=True))
    op.add_column('app_settings', sa.Column('gmail_history_cursor', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('app_settings', 'gmail_history_cursor')
    op.drop_column('app_settings', 'gmail_last_error')
    op.drop_column('app_settings', 'gmail_last_sync_at')
    op.drop_column('app_settings', 'gmail_auto_apply')
    op.drop_column('app_settings', 'gmail_lookback_days')
    op.drop_column('app_settings', 'gmail_sync_minutes')
    op.drop_column('app_settings', 'gmail_sync_enabled')

    op.drop_index('ix_email_suggestions_state_received_at', table_name='email_suggestions')
    op.drop_index(op.f('ix_email_suggestions_contact_id'), table_name='email_suggestions')
    op.drop_index(op.f('ix_email_suggestions_application_id'), table_name='email_suggestions')
    op.drop_table('email_suggestions')
    for enum_type in reversed(NEW_ENUMS):
        enum_type.drop(op.get_bind(), checkfirst=True)
