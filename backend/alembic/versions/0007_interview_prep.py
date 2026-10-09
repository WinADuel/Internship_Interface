"""interview prep (Phase 4): interview rounds, story bank, prep briefs,
interview_brief research-queue kind; existing interview dates become rounds

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-09 09:00:00.000000

"""
import json
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


INTERVIEW_KIND_VALUES = (
    'recruiter_screen', 'technical', 'behavioral', 'case', 'onsite', 'final', 'other',
)
INTERVIEW_FORMAT_VALUES = ('video', 'phone', 'in_person')
INTERVIEW_STATE_VALUES = ('scheduled', 'done', 'cancelled')
INTERVIEW_OUTCOME_VALUES = ('waiting', 'passed', 'rejected')

# create_type=False: the types are created and dropped explicitly below.
interview_kind = postgresql.ENUM(*INTERVIEW_KIND_VALUES, name='interview_kind', create_type=False)
interview_format = postgresql.ENUM(*INTERVIEW_FORMAT_VALUES, name='interview_format', create_type=False)
interview_state = postgresql.ENUM(*INTERVIEW_STATE_VALUES, name='interview_state', create_type=False)
interview_outcome = postgresql.ENUM(*INTERVIEW_OUTCOME_VALUES, name='interview_outcome', create_type=False)

NEW_ENUMS = (interview_kind, interview_format, interview_state, interview_outcome)

# A copy, not an import: a migration must not change when the app's default
# checklist does (app/services/interview_service.py DEFAULT_CHECKLIST).
DEFAULT_CHECKLIST = (
    "Research the company and team",
    "Re-read the job description",
    "Pick 2–3 stories",
    "Prepare 3 questions to ask",
    "Test the call link / plan the route",
    "Send thank-you notes within 24 hours",
)

# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _default_checklist() -> str:
    return json.dumps(
        [{"id": uuid.uuid4().hex[:12], "label": label, "done": False} for label in DEFAULT_CHECKLIST]
    )


def upgrade() -> None:
    """Upgrade schema."""
    # PG 12+ allows this inside the migration's transaction as long as the new
    # value is not used in that same transaction (nothing below uses it).
    op.execute("ALTER TYPE queue_kind ADD VALUE IF NOT EXISTS 'interview_brief'")

    for enum_type in NEW_ENUMS:
        enum_type.create(op.get_bind(), checkfirst=True)

    op.create_table('stories',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('situation', sa.Text(), nullable=True),
    sa.Column('task', sa.Text(), nullable=True),
    sa.Column('action', sa.Text(), nullable=True),
    sa.Column('result', sa.Text(), nullable=True),
    sa.Column('tags', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
    sa.Column('archived', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('prep_briefs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('application_id', sa.Integer(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('sources', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('application_id')
    )
    op.create_table('interview_rounds',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('application_id', sa.Integer(), nullable=False),
    sa.Column('kind', interview_kind, server_default='other', nullable=False),
    sa.Column('title', sa.String(length=200), nullable=True),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('duration_minutes', sa.Integer(), nullable=True),
    sa.Column('format', interview_format, nullable=True),
    sa.Column('location', sa.String(length=500), nullable=True),
    sa.Column('interviewers', sa.String(length=500), nullable=True),
    sa.Column('state', interview_state, server_default='scheduled', nullable=False),
    sa.Column('outcome', interview_outcome, nullable=True),
    sa.Column('prep_notes', sa.Text(), nullable=True),
    sa.Column('questions_to_ask', sa.Text(), nullable=True),
    sa.Column('reflection', sa.Text(), nullable=True),
    sa.Column('checklist', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('thank_you_sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_interview_rounds_application_id'), 'interview_rounds', ['application_id'], unique=False)
    op.create_index('ix_interview_rounds_state_scheduled_at', 'interview_rounds', ['state', 'scheduled_at'], unique=False)
    op.create_table('interview_round_contacts',
    sa.Column('round_id', sa.Integer(), nullable=False),
    sa.Column('contact_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['round_id'], ['interview_rounds.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('round_id', 'contact_id')
    )
    op.create_table('interview_round_stories',
    sa.Column('round_id', sa.Integer(), nullable=False),
    sa.Column('story_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['round_id'], ['interview_rounds.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['story_id'], ['stories.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('round_id', 'story_id')
    )

    _interview_dates_to_rounds()


def _interview_dates_to_rounds() -> None:
    """Spec §3 data migration: each application's interview_datetime becomes
    one round, `scheduled` if still ahead and `done` if past. The column is
    then re-derived as the app now does (earliest scheduled round), so a past
    date moves to its done round; downgrade() puts it back."""
    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    rows = bind.execute(
        sa.text("SELECT id, interview_datetime FROM applications WHERE interview_datetime IS NOT NULL ORDER BY id")
    ).all()
    for application_id, when in rows:
        bind.execute(
            sa.text(
                "INSERT INTO interview_rounds (application_id, kind, scheduled_at, state, checklist)"
                " VALUES (:application_id, 'other', :when, CAST(:state AS interview_state),"
                " CAST(:checklist AS jsonb))"
            ),
            {
                "application_id": application_id,
                "when": when,
                "state": "scheduled" if when >= now else "done",
                "checklist": _default_checklist(),
            },
        )
    bind.execute(
        sa.text("UPDATE applications SET interview_datetime = NULL WHERE interview_datetime < :now"),
        {"now": now},
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Before the rounds go, give an application whose only rounds are past
    # its last done round's date back, so the pre-Phase-4 field keeps it.
    op.execute(
        "UPDATE applications AS a SET interview_datetime = ("
        " SELECT max(r.scheduled_at) FROM interview_rounds AS r"
        " WHERE r.application_id = a.id AND r.state = 'done')"
        " WHERE a.interview_datetime IS NULL AND EXISTS ("
        " SELECT 1 FROM interview_rounds AS r"
        " WHERE r.application_id = a.id AND r.state = 'done' AND r.scheduled_at IS NOT NULL)"
    )
    op.drop_table('interview_round_stories')
    op.drop_table('interview_round_contacts')
    op.drop_index('ix_interview_rounds_state_scheduled_at', table_name='interview_rounds')
    op.drop_index(op.f('ix_interview_rounds_application_id'), table_name='interview_rounds')
    op.drop_table('interview_rounds')
    op.drop_table('prep_briefs')
    op.drop_table('stories')
    for enum_type in reversed(NEW_ENUMS):
        enum_type.drop(op.get_bind(), checkfirst=True)
    # queue_kind keeps 'interview_brief': Postgres cannot drop an enum value
    # without rebuilding the type. Pending brief requests would be orphaned
    # work for a routine that no longer handles them, so they are failed.
    op.execute(
        "UPDATE research_queue SET state = 'failed', completed_at = now(),"
        " result_note = 'interview prep removed (downgrade)'"
        " WHERE kind::text = 'interview_brief' AND state = 'pending'"
    )
