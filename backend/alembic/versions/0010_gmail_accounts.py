"""gmail accounts (Phase 7): more than one Gmail inbox, each with its own
token and cursor; email suggestions belong to an inbox

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GMAIL_SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'
OLD_UNIQUE = 'email_suggestions_gmail_message_id_key'  # Postgres's name for 0009's unique key
NEW_UNIQUE = 'uq_email_suggestions_account_message'


def _carry_over_phase6_inbox(conn) -> None:
    """A Phase 6 Google connection that holds the Gmail permission becomes
    the first inbox (address unknown until its first sync), with the sync
    state from app_settings; every existing suggestion belongs to it. The
    encrypted token is copied as stored: no key is needed here, and the
    `google` row itself stays as it is for Drive and Docs."""
    token = conn.execute(
        sa.text("SELECT encrypted_refresh_token, scopes FROM oauth_tokens WHERE provider = 'google'")
    ).first()
    if token is None or GMAIL_SCOPE not in token.scopes.split():
        return
    settings = conn.execute(
        sa.text("SELECT gmail_history_cursor, gmail_last_sync_at, gmail_last_error FROM app_settings WHERE id = 1")
    ).first()
    account_id = conn.execute(
        sa.text(
            "INSERT INTO gmail_accounts (email, encrypted_refresh_token, scopes, history_cursor, last_sync_at, last_error)"
            " VALUES (NULL, :token, :scopes, :cursor, :synced, :error) RETURNING id"
        ),
        {
            "token": token.encrypted_refresh_token,
            "scopes": token.scopes,
            "cursor": settings.gmail_history_cursor if settings else None,
            "synced": settings.gmail_last_sync_at if settings else None,
            "error": settings.gmail_last_error if settings else None,
        },
    ).scalar_one()
    conn.execute(sa.text("UPDATE email_suggestions SET gmail_account_id = :a"), {"a": account_id})


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('gmail_accounts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.Text(), nullable=True),
    sa.Column('encrypted_refresh_token', sa.LargeBinary(), nullable=False),
    sa.Column('scopes', sa.Text(), nullable=False),
    sa.Column('history_cursor', sa.Text(), nullable=True),
    sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.add_column('email_suggestions', sa.Column('gmail_account_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_email_suggestions_gmail_account_id'), 'email_suggestions', ['gmail_account_id'], unique=False)
    op.create_foreign_key(
        'email_suggestions_gmail_account_id_fkey', 'email_suggestions', 'gmail_accounts',
        ['gmail_account_id'], ['id'], ondelete='CASCADE',
    )
    op.drop_constraint(OLD_UNIQUE, 'email_suggestions', type_='unique')
    op.create_unique_constraint(NEW_UNIQUE, 'email_suggestions', ['gmail_account_id', 'gmail_message_id'])

    _carry_over_phase6_inbox(op.get_bind())

    op.drop_column('app_settings', 'gmail_history_cursor')


def downgrade() -> None:
    """Downgrade schema. The cursor goes back from the oldest inbox, and only
    the oldest inbox's suggestions (and any without an inbox) are kept, one
    per Gmail message id. Tokens of the other inboxes are dropped with the
    table: Phase 6 reads Gmail through the `google` connection only."""
    op.add_column('app_settings', sa.Column('gmail_history_cursor', sa.Text(), nullable=True))
    conn = op.get_bind()
    oldest = conn.execute(sa.text("SELECT id, history_cursor FROM gmail_accounts ORDER BY id LIMIT 1")).first()
    if oldest is not None:
        conn.execute(
            sa.text("UPDATE app_settings SET gmail_history_cursor = :c WHERE id = 1"), {"c": oldest.history_cursor}
        )
        conn.execute(
            sa.text("DELETE FROM email_suggestions WHERE gmail_account_id IS NOT NULL AND gmail_account_id <> :a"),
            {"a": oldest.id},
        )
    # A message stored both with and without an inbox: keep the inbox's row.
    conn.execute(
        sa.text(
            "DELETE FROM email_suggestions s USING email_suggestions keep"
            " WHERE s.gmail_message_id = keep.gmail_message_id AND s.id <> keep.id"
            " AND (s.gmail_account_id IS NULL AND keep.gmail_account_id IS NOT NULL"
            "      OR (s.gmail_account_id IS NULL) = (keep.gmail_account_id IS NULL) AND s.id > keep.id)"
        )
    )

    op.drop_constraint(NEW_UNIQUE, 'email_suggestions', type_='unique')
    op.create_unique_constraint(OLD_UNIQUE, 'email_suggestions', ['gmail_message_id'])
    op.drop_constraint('email_suggestions_gmail_account_id_fkey', 'email_suggestions', type_='foreignkey')
    op.drop_index(op.f('ix_email_suggestions_gmail_account_id'), table_name='email_suggestions')
    op.drop_column('email_suggestions', 'gmail_account_id')
    op.drop_table('gmail_accounts')
