"""The latest migration matches the models (`alembic check`), on a real,
throwaway PostgreSQL database. Checked at head rather than in each
revision's own test, so a later migration doesn't break an earlier test."""

from alembic import command
from tests.migrations.test_0007_interview_prep import alembic_cfg, scratch_db  # noqa: F401 (fixtures)


def test_head_matches_the_models(scratch_db, alembic_cfg):  # noqa: F811
    command.upgrade(alembic_cfg, "head")
    command.check(alembic_cfg)
