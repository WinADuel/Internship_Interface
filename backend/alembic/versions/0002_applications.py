"""applications

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06 15:53:37.504589

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


STATUS_VALUES = ('wishlist', 'applied', 'phone_screen', 'interview', 'offer', 'rejected')
PRIORITY_VALUES = ('low', 'medium', 'high')

# create_type=False: the types are created/dropped explicitly below, because
# application_status is shared by two tables and create_table would otherwise
# try to create it twice.
application_status = postgresql.ENUM(*STATUS_VALUES, name='application_status', create_type=False)
application_priority = postgresql.ENUM(*PRIORITY_VALUES, name='application_priority', create_type=False)


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    application_status.create(op.get_bind(), checkfirst=True)
    application_priority.create(op.get_bind(), checkfirst=True)
    op.create_table('applications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company', sa.Text(), nullable=False),
    sa.Column('role_title', sa.Text(), nullable=False),
    sa.Column('date_applied', sa.Date(), nullable=True),
    sa.Column('status', application_status, nullable=False),
    sa.Column('job_link', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('resume_version', sa.Text(), nullable=True),
    sa.Column('contact_person', sa.Text(), nullable=True),
    sa.Column('salary_range', sa.Text(), nullable=True),
    sa.Column('location', sa.Text(), nullable=True),
    sa.Column('source', sa.Text(), nullable=True),
    sa.Column('priority', application_priority, nullable=False),
    sa.Column('follow_up_date', sa.Date(), nullable=True),
    sa.Column('interview_datetime', sa.DateTime(timezone=True), nullable=True),
    sa.Column('google_doc_link', sa.Text(), nullable=True),
    sa.Column('archived', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('oauth_tokens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(), nullable=False),
    sa.Column('encrypted_refresh_token', sa.LargeBinary(), nullable=False),
    sa.Column('scopes', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider')
    )
    op.create_table('status_history',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('application_id', sa.Integer(), nullable=False),
    sa.Column('old_status', application_status, nullable=True),
    sa.Column('new_status', application_status, nullable=False),
    sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_status_history_application_id'), 'status_history', ['application_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_status_history_application_id'), table_name='status_history')
    op.drop_table('status_history')
    op.drop_table('oauth_tokens')
    op.drop_table('applications')
    application_priority.drop(op.get_bind(), checkfirst=True)
    application_status.drop(op.get_bind(), checkfirst=True)
