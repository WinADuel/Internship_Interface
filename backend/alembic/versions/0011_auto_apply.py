"""auto apply: the apply profile, prepared applications (one per posting) and
the Chrome extension's bearer tokens

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-05 22:42:46.463898

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('apply_profile',
    sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('fields', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('saved_answers', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('resume_filename', sa.Text(), nullable=True),
    sa.Column('resume_content_type', sa.Text(), nullable=True),
    sa.Column('resume_data', sa.LargeBinary(), nullable=True),
    sa.Column('resume_uploaded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('llm_url', sa.Text(), server_default='', nullable=False),
    sa.Column('llm_model', sa.Text(), server_default='', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('id = 1', name='apply_profile_single_row'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('extension_tokens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.Text(), nullable=False),
    sa.Column('token_prefix', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_table('apply_drafts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('posting_id', sa.Integer(), nullable=False),
    sa.Column('ats', sa.Text(), nullable=False),
    sa.Column('apply_url', sa.Text(), nullable=False),
    sa.Column('form', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('answers', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['posting_id'], ['postings.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('posting_id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('apply_drafts')
    op.drop_table('extension_tokens')
    op.drop_table('apply_profile')
