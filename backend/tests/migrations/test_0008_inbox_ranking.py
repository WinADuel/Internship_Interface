"""Migration 0008 up and down on a real, throwaway PostgreSQL database
(created next to the test database and dropped afterwards)."""

from sqlalchemy import text

from alembic import command
from tests.migrations.test_0007_interview_prep import alembic_cfg, scratch_db  # noqa: F401 (fixtures)

RANKING_COLUMNS = {
    "ranking_role_keywords",
    "ranking_skill_keywords",
    "ranking_preferred_locations",
    "ranking_preferred_companies",
    "ranking_avoid_companies",
    "ranking_dealbreaker_keywords",
    "ranking_claude_daily_limit",
    "ranking_updated_at",
    "last_rescore_at",
}
POSTING_COLUMNS = {"local_score", "local_reasons", "claude_scored_at"}


def _columns(conn, table: str) -> set[str]:
    return set(
        conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"), {"t": table}
        ).scalars()
    )


def _indexes(conn) -> set[str]:
    return set(conn.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'postings'")).scalars())


def _seed(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO app_settings (id) VALUES (1)"))
        for n, state in enumerate(("new", "saved", "dismissed")):
            conn.execute(
                text(
                    "INSERT INTO postings (source, source_key, company, title, url, url_key, state)"
                    " VALUES ('simplify', :key, 'Acme', 'Intern', :url, :url, :state)"
                ),
                {"key": f"k{n}", "url": f"https://jobs.example.com/{n}", "state": state},
            )


def test_upgrade_adds_ranking_fields_and_scores_existing_postings_neutral(scratch_db, alembic_cfg):  # noqa: F811
    command.upgrade(alembic_cfg, "0007")
    _seed(scratch_db)

    command.upgrade(alembic_cfg, "0008")

    with scratch_db.connect() as conn:
        assert RANKING_COLUMNS <= _columns(conn, "app_settings")
        assert POSTING_COLUMNS <= _columns(conn, "postings")
        assert "ix_postings_inbox_best" in _indexes(conn)
        settings = conn.execute(
            text(
                "SELECT ranking_role_keywords, ranking_claude_daily_limit, ranking_updated_at, last_rescore_at"
                " FROM app_settings"
            )
        ).one()
        assert tuple(settings) == ([], 40, None, None)
        rows = conn.execute(text("SELECT local_score, local_reasons, claude_scored_at FROM postings")).all()
        assert [tuple(r) for r in rows] == [(50, [], None)] * 3


def test_downgrade_drops_the_ranking_fields(scratch_db, alembic_cfg):  # noqa: F811
    command.upgrade(alembic_cfg, "0007")
    _seed(scratch_db)
    command.upgrade(alembic_cfg, "0008")

    command.downgrade(alembic_cfg, "0007")
    with scratch_db.connect() as conn:
        assert not RANKING_COLUMNS & _columns(conn, "app_settings")
        assert not POSTING_COLUMNS & _columns(conn, "postings")
        assert "ix_postings_inbox_best" not in _indexes(conn)
        assert conn.execute(text("SELECT count(*) FROM postings")).scalar_one() == 3

    command.upgrade(alembic_cfg, "0008")
    with scratch_db.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0008"

