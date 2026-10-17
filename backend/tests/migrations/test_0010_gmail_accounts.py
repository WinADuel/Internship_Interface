"""Migration 0010 up and down on a real, throwaway PostgreSQL database
(created next to the test database and dropped afterwards), with and
without a Phase 6 Gmail connection."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import exc as sqlalchemy_exc
from sqlalchemy import text

from alembic import command
from tests.migrations.test_0007_interview_prep import alembic_cfg, scratch_db  # noqa: F401 (fixtures)

GMAIL = "https://www.googleapis.com/auth/gmail.readonly"
DRIVE = "https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file"
SYNCED = datetime(2026, 10, 15, 9, tzinfo=timezone.utc)
CIPHER = b"\x00fernet-ciphertext"


def _columns(conn, table: str) -> set[str]:
    return set(
        conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"), {"t": table}
        ).scalars()
    )


def _seed_phase6(engine, scopes: str | None) -> None:
    """Phase 6 data: settings with a cursor, an application and two
    suggestions, and (unless `scopes` is None) the `google` connection."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO app_settings (id, gmail_sync_enabled, gmail_history_cursor, gmail_last_sync_at, gmail_last_error)"
                " VALUES (1, true, '1760000000000', :synced, 'gmail list rejected (status 500)')"
            ),
            {"synced": SYNCED},
        )
        app_id = conn.execute(
            text(
                "INSERT INTO applications (company, role_title, status, priority)"
                " VALUES ('Acme', 'Intern', 'applied', 'medium') RETURNING id"
            )
        ).scalar_one()
        for mid in ("m1", "m2"):
            conn.execute(
                text(
                    "INSERT INTO email_suggestions (gmail_message_id, gmail_thread_id, received_at, direction, kind, application_id)"
                    " VALUES (:m, 't', now(), 'inbound', 'rejection', :a)"
                ),
                {"m": mid, "a": app_id},
            )
        if scopes is not None:
            conn.execute(
                text("INSERT INTO oauth_tokens (provider, encrypted_refresh_token, scopes) VALUES ('google', :t, :s)"),
                {"t": CIPHER, "s": scopes},
            )


def test_upgrade_carries_a_phase_6_gmail_connection_over(scratch_db, alembic_cfg):  # noqa: F811
    command.upgrade(alembic_cfg, "0009")
    _seed_phase6(scratch_db, f"{DRIVE} {GMAIL}")

    command.upgrade(alembic_cfg, "0010")

    with scratch_db.begin() as conn:
        assert "gmail_history_cursor" not in _columns(conn, "app_settings")
        (account,) = conn.execute(text("SELECT * FROM gmail_accounts")).mappings().all()
        assert account["email"] is None
        assert bytes(account["encrypted_refresh_token"]) == CIPHER
        assert account["scopes"] == f"{DRIVE} {GMAIL}"
        assert account["history_cursor"] == "1760000000000"
        assert account["last_sync_at"] == SYNCED
        assert account["last_error"] == "gmail list rejected (status 500)"
        assert account["created_at"] is not None and account["updated_at"] is not None
        owners = conn.execute(text("SELECT DISTINCT gmail_account_id FROM email_suggestions")).scalars().all()
        assert owners == [account["id"]]
        # The run summary stays on app_settings; the Drive row is untouched.
        settings = conn.execute(text("SELECT gmail_last_sync_at, gmail_last_error FROM app_settings")).one()
        assert tuple(settings) == (SYNCED, "gmail list rejected (status 500)")
        drive = conn.execute(text("SELECT scopes FROM oauth_tokens WHERE provider = 'google'")).scalar_one()
        assert drive == f"{DRIVE} {GMAIL}"

        # A message id is unique per inbox, not overall.
        other = conn.execute(
            text("INSERT INTO gmail_accounts (email, encrypted_refresh_token, scopes) VALUES ('b@x.com', 'x', :s) RETURNING id"),
            {"s": GMAIL},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO email_suggestions (gmail_account_id, gmail_message_id, gmail_thread_id, received_at, direction, kind)"
                " VALUES (:a, 'm1', 't', now(), 'inbound', 'offer')"
            ),
            {"a": other},
        )
        # Removing an inbox removes its suggestions.
        conn.execute(text("DELETE FROM gmail_accounts WHERE id = :a"), {"a": account["id"]})
        assert conn.execute(text("SELECT gmail_message_id FROM email_suggestions")).scalars().all() == ["m1"]

    with pytest.raises(sqlalchemy_exc.IntegrityError):
        with scratch_db.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO email_suggestions (gmail_account_id, gmail_message_id, gmail_thread_id, received_at, direction, kind)"
                    " VALUES (:a, 'm1', 't', now(), 'inbound', 'offer')"
                ),
                {"a": other},
            )
    with pytest.raises(sqlalchemy_exc.IntegrityError):
        with scratch_db.begin() as conn:
            conn.execute(
                text("INSERT INTO gmail_accounts (email, encrypted_refresh_token, scopes) VALUES ('b@x.com', 'y', 's')")
            )


@pytest.mark.parametrize("scopes", [None, DRIVE])
def test_upgrade_without_a_phase_6_gmail_connection_adds_no_inbox(scratch_db, alembic_cfg, scopes):  # noqa: F811
    command.upgrade(alembic_cfg, "0009")
    _seed_phase6(scratch_db, scopes)

    command.upgrade(alembic_cfg, "0010")

    with scratch_db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM gmail_accounts")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM email_suggestions WHERE gmail_account_id IS NULL")).scalar_one() == 2


def test_downgrade_keeps_the_oldest_inbox_and_upgrades_again(scratch_db, alembic_cfg):  # noqa: F811
    command.upgrade(alembic_cfg, "0009")
    _seed_phase6(scratch_db, f"{DRIVE} {GMAIL}")
    command.upgrade(alembic_cfg, "0010")
    with scratch_db.begin() as conn:
        oldest = conn.execute(text("SELECT id FROM gmail_accounts")).scalar_one()
        conn.execute(text("UPDATE gmail_accounts SET history_cursor = '1760500000000'"))
        newer = conn.execute(
            text("INSERT INTO gmail_accounts (email, encrypted_refresh_token, scopes) VALUES ('b@x.com', 'x', :s) RETURNING id"),
            {"s": GMAIL},
        ).scalar_one()
        for account, mid in ((newer, "m1"), (newer, "m3"), (None, "m4"), (None, "m2")):
            conn.execute(
                text(
                    "INSERT INTO email_suggestions (gmail_account_id, gmail_message_id, gmail_thread_id, received_at, direction, kind)"
                    " VALUES (:a, :m, 't', now(), 'inbound', 'offer')"
                ),
                {"a": account, "m": mid},
            )

    command.downgrade(alembic_cfg, "0009")

    with scratch_db.connect() as conn:
        assert not _columns(conn, "gmail_accounts")
        assert "gmail_account_id" not in _columns(conn, "email_suggestions")
        cursor = conn.execute(text("SELECT gmail_history_cursor FROM app_settings")).scalar_one()
        assert cursor == "1760500000000"
        # The oldest inbox's suggestions, plus those without an inbox that
        # don't repeat one of them: one row per message id.
        rows = conn.execute(text("SELECT gmail_message_id, kind FROM email_suggestions ORDER BY gmail_message_id")).all()
        assert [tuple(r) for r in rows] == [("m1", "rejection"), ("m2", "rejection"), ("m4", "offer")]
        assert oldest

    command.upgrade(alembic_cfg, "0010")
    with scratch_db.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0010"
        (account,) = conn.execute(text("SELECT history_cursor, email FROM gmail_accounts")).all()
        assert tuple(account) == ("1760500000000", None)
        assert conn.execute(text("SELECT count(*) FROM email_suggestions WHERE gmail_account_id IS NULL")).scalar_one() == 0


def test_downgrade_without_inboxes(scratch_db, alembic_cfg):  # noqa: F811
    command.upgrade(alembic_cfg, "0009")
    _seed_phase6(scratch_db, None)
    command.upgrade(alembic_cfg, "0010")
    command.downgrade(alembic_cfg, "0009")
    with scratch_db.connect() as conn:
        assert conn.execute(text("SELECT gmail_history_cursor FROM app_settings")).scalar_one() is None
        assert conn.execute(text("SELECT count(*) FROM email_suggestions")).scalar_one() == 2
    command.upgrade(alembic_cfg, "0010")
