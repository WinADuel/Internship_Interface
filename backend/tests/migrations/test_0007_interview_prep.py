"""Migration 0007 up and down on a real, throwaway PostgreSQL database
(created next to the test database and dropped afterwards)."""

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url, text

from app.core.config import settings
from tests.scratch_db import drop_database

BACKEND = Path(__file__).resolve().parents[2]
NOW = datetime.now(timezone.utc).replace(microsecond=0)
FUTURE = NOW + timedelta(days=5)
PAST = NOW - timedelta(days=2)
DEFAULT_LABELS = [
    "Research the company and team",
    "Re-read the job description",
    "Pick 2–3 stories",
    "Prepare 3 questions to ask",
    "Test the call link / plan the route",
    "Send thank-you notes within 24 hours",
]


@pytest.fixture()
def scratch_db(monkeypatch):
    """An empty database; Alembic's env.py reads its URL from settings."""
    base = make_url(os.environ["TEST_DATABASE_URL"])
    name = f"{base.database}_mig_{uuid.uuid4().hex[:8]}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.exec_driver_sql(f'CREATE DATABASE "{name}"')
    url = base.set(database=name)
    monkeypatch.setattr(settings, "database_url", url.render_as_string(hide_password=False))
    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()
        drop_database(admin, name)
        admin.dispose()


@pytest.fixture()
def alembic_cfg():
    # No ini file: env.py then leaves the test run's logging alone.
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def _seed_applications(engine) -> dict[str, int]:
    ids = {}
    with engine.begin() as conn:
        for key, when in (("future", FUTURE), ("past", PAST), ("none", None)):
            ids[key] = conn.execute(
                text(
                    "INSERT INTO applications (company, role_title, status, priority, interview_datetime)"
                    " VALUES (:company, 'Intern', 'applied', 'medium', :when) RETURNING id"
                ),
                {"company": key, "when": when},
            ).scalar_one()
    return ids


def _rounds(conn) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for row in conn.execute(
        text("SELECT application_id, kind::text, scheduled_at, state::text, checklist FROM interview_rounds")
    ).mappings():
        out.setdefault(row["application_id"], []).append(dict(row))
    return out


def _interview_datetimes(conn) -> dict[int, datetime | None]:
    return dict(conn.execute(text("SELECT id, interview_datetime FROM applications")).all())


def _tables(conn) -> set[str]:
    return set(
        conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).scalars()
    )


def _enum_values(conn, name: str) -> list[str]:
    return list(
        conn.execute(
            text(
                "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid"
                " WHERE t.typname = :name ORDER BY e.enumsortorder"
            ),
            {"name": name},
        ).scalars()
    )


def test_upgrade_turns_interview_dates_into_rounds(scratch_db, alembic_cfg):
    command.upgrade(alembic_cfg, "0006")
    ids = _seed_applications(scratch_db)

    command.upgrade(alembic_cfg, "0007")
    command.check(alembic_cfg)  # the models match the migrated schema

    with scratch_db.connect() as conn:
        assert {"interview_rounds", "interview_round_contacts", "interview_round_stories", "stories",
                "prep_briefs"} <= _tables(conn)
        assert _enum_values(conn, "queue_kind")[-1] == "interview_brief"
        rounds = _rounds(conn)
        dates = _interview_datetimes(conn)

    assert set(rounds) == {ids["future"], ids["past"]}
    (future,) = rounds[ids["future"]]
    assert (future["kind"], future["scheduled_at"], future["state"]) == ("other", FUTURE, "scheduled")
    (past,) = rounds[ids["past"]]
    assert (past["scheduled_at"], past["state"]) == (PAST, "done")
    for r in (future, past):
        assert [item["label"] for item in r["checklist"]] == DEFAULT_LABELS
        assert all(item["done"] is False and item["id"] for item in r["checklist"])
    # interview_datetime is now derived: the earliest scheduled round.
    assert dates == {ids["future"]: FUTURE, ids["past"]: None, ids["none"]: None}

    with scratch_db.begin() as conn:  # the new queue kind is usable
        conn.execute(
            text(
                "INSERT INTO research_queue (kind, request_text, application_id, state)"
                " VALUES ('interview_brief', 'past — Intern', :id, 'pending')"
            ),
            {"id": ids["past"]},
        )


def test_downgrade_drops_the_new_tables_and_restores_past_dates(scratch_db, alembic_cfg):
    command.upgrade(alembic_cfg, "0006")
    ids = _seed_applications(scratch_db)
    command.upgrade(alembic_cfg, "0007")
    with scratch_db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO research_queue (kind, request_text, application_id, state)"
                " VALUES ('interview_brief', 'x', :id, 'pending'), ('interview_brief', 'z', :id, 'done'),"
                " ('company_contacts', 'y', :id, 'pending')"
            ),
            {"id": ids["future"]},
        )
        conn.execute(
            text("INSERT INTO stories (title) VALUES ('kept only until downgrade')")
        )

    command.downgrade(alembic_cfg, "0006")

    with scratch_db.connect() as conn:
        tables = _tables(conn)
        assert not {"interview_rounds", "interview_round_contacts", "interview_round_stories", "stories",
                    "prep_briefs"} & tables
        for name in ("interview_kind", "interview_format", "interview_state", "interview_outcome"):
            assert _enum_values(conn, name) == []
        assert "interview_brief" in _enum_values(conn, "queue_kind")  # left in place
        assert _interview_datetimes(conn) == {ids["future"]: FUTURE, ids["past"]: PAST, ids["none"]: None}
        # Brief requests of any state go: Phase 3's QueueKind can't load them.
        queue = conn.execute(text("SELECT kind::text, state::text FROM research_queue")).all()
        assert [tuple(row) for row in queue] == [("company_contacts", "pending")]
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0006"

    # Upgrading again works with the enum value already present.
    command.upgrade(alembic_cfg, "head")
    with scratch_db.connect() as conn:
        rounds = _rounds(conn)
    assert {k: [r["state"] for r in v] for k, v in rounds.items()} == {
        ids["future"]: ["scheduled"],
        ids["past"]: ["done"],
    }
