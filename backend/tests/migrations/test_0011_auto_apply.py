"""Migration 0011 up and down on a throwaway PostgreSQL database."""

from sqlalchemy import text

from alembic import command
from tests.migrations.test_0007_interview_prep import alembic_cfg, scratch_db  # noqa: F401 (fixtures)

TABLES = {"apply_profile", "apply_drafts", "extension_tokens"}


def _tables(conn) -> set[str]:
    return set(conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).scalars())


def test_upgrade_adds_the_tables_and_drafts_go_with_their_posting(scratch_db, alembic_cfg):  # noqa: F811
    command.upgrade(alembic_cfg, "0011")
    with scratch_db.begin() as conn:
        assert TABLES <= _tables(conn)
        conn.execute(text("INSERT INTO apply_profile (id) VALUES (1)"))
        row = conn.execute(text("SELECT fields, saved_answers, llm_url FROM apply_profile")).one()
        assert tuple(row) == ({}, [], "")
        posting_id = conn.execute(
            text(
                "INSERT INTO postings (source, source_key, company, title, url, url_key)"
                " VALUES ('greenhouse', '1', 'Acme', 'Intern', 'https://x', 'x') RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            text("INSERT INTO apply_drafts (posting_id, ats, apply_url) VALUES (:p, 'greenhouse', 'https://x')"),
            {"p": posting_id},
        )
        conn.execute(text("DELETE FROM postings"))
        assert conn.execute(text("SELECT count(*) FROM apply_drafts")).scalar_one() == 0


def test_downgrade_drops_the_tables_and_upgrades_again(scratch_db, alembic_cfg):  # noqa: F811
    command.upgrade(alembic_cfg, "0011")
    command.downgrade(alembic_cfg, "0010")
    with scratch_db.connect() as conn:
        assert not TABLES & _tables(conn)
    command.upgrade(alembic_cfg, "0011")
    with scratch_db.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0011"
