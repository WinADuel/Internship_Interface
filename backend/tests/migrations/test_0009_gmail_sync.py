"""Migration 0009 up and down on a real, throwaway PostgreSQL database
(created next to the test database and dropped afterwards)."""

from sqlalchemy import text

from alembic import command
from tests.migrations.test_0007_interview_prep import alembic_cfg, scratch_db  # noqa: F401 (fixtures)

GMAIL_SETTINGS = {
    "gmail_sync_enabled",
    "gmail_sync_minutes",
    "gmail_lookback_days",
    "gmail_auto_apply",
    "gmail_last_sync_at",
    "gmail_last_error",
    "gmail_history_cursor",
}
ENUMS = {"email_suggestion_kind", "email_direction", "email_suggestion_state"}


def _columns(conn, table: str) -> set[str]:
    return set(
        conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"), {"t": table}
        ).scalars()
    )


def _enums(conn) -> set[str]:
    return set(conn.execute(text("SELECT typname FROM pg_type WHERE typtype = 'e'")).scalars())


def _seed(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO app_settings (id) VALUES (1)"))
        conn.execute(
            text("INSERT INTO applications (company, role_title, status, priority) VALUES ('Acme', 'Intern', 'applied', 'medium')")
        )


def test_upgrade_adds_the_suggestions_table_and_gmail_settings_off(scratch_db, alembic_cfg):  # noqa: F811
    command.upgrade(alembic_cfg, "0008")
    _seed(scratch_db)

    command.upgrade(alembic_cfg, "0009")

    with scratch_db.begin() as conn:
        assert GMAIL_SETTINGS <= _columns(conn, "app_settings")
        assert ENUMS <= _enums(conn)
        row = conn.execute(
            text(
                "SELECT gmail_sync_enabled, gmail_sync_minutes, gmail_lookback_days, gmail_auto_apply,"
                " gmail_last_sync_at, gmail_last_error, gmail_history_cursor FROM app_settings"
            )
        ).one()
        assert tuple(row) == (False, 30, 30, False, None, None, None)
        app_id = conn.execute(text("SELECT id FROM applications")).scalar_one()
        conn.execute(
            text(
                "INSERT INTO email_suggestions (gmail_message_id, gmail_thread_id, received_at, direction, kind,"
                " application_id) VALUES ('m1', 't1', now(), 'inbound', 'rejection', :a)"
            ),
            {"a": app_id},
        )
        assert conn.execute(text("SELECT state FROM email_suggestions")).scalar_one() == "pending"
        # Deleting the application keeps the suggestion, unlinked.
        conn.execute(text("DELETE FROM applications"))
        assert conn.execute(text("SELECT application_id FROM email_suggestions")).scalar_one() is None


def test_downgrade_drops_everything_and_upgrades_again(scratch_db, alembic_cfg):  # noqa: F811
    command.upgrade(alembic_cfg, "0008")
    _seed(scratch_db)
    command.upgrade(alembic_cfg, "0009")

    command.downgrade(alembic_cfg, "0008")
    with scratch_db.connect() as conn:
        assert not GMAIL_SETTINGS & _columns(conn, "app_settings")
        assert not _columns(conn, "email_suggestions")
        assert not ENUMS & _enums(conn)
        assert conn.execute(text("SELECT count(*) FROM applications")).scalar_one() == 1

    command.upgrade(alembic_cfg, "0009")
    with scratch_db.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0009"
