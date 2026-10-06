"""Proves the `db_session` fixture isolates commits (and rollbacks), not
just the outer rollback at teardown.

Later tasks' services will call `session.commit()` as their normal write
path (e.g. auth_service, application_service), and may also call
`session.rollback()` on an error path. With a plain connection+transaction
binding, a lone `commit()` happens to be absorbed harmlessly by
SQLAlchemy 2.0's default `join_transaction_mode` — but a `rollback()`
(even one that follows an earlier commit) ends the fixture's *outer*
transaction for real. Any later `commit()` in that same test then opens
and commits a brand new, real transaction, permanently persisting data
past the test — exactly the leak this fixture must prevent. This test
exercises that realistic commit/rollback/commit sequence and checks
visibility from an independent connection to prove no real commit escapes.
"""

import pytest
import sqlalchemy as sa

SCRATCH_TABLE = "_conftest_isolation_probe"


@pytest.fixture(scope="module")
def _scratch_table(_engine):
    """A real table, created and dropped on its own (committed) connection
    — outside any `db_session` transaction — so this module's tests get a
    clean "0 rows" from a cross-connection SELECT rather than a "table
    doesn't exist" error. Module-scoped so its teardown (the DROP) runs
    after every `db_session` in this module has already been rolled back
    and closed, avoiding a lock conflict with the fixture under test.
    """
    with _engine.begin() as connection:
        connection.execute(
            sa.text(
                f"CREATE TABLE {SCRATCH_TABLE} (id serial primary key, value text)"
            )
        )
    yield
    with _engine.begin() as connection:
        connection.execute(sa.text(f"DROP TABLE {SCRATCH_TABLE}"))


def _insert(session, value):
    session.execute(
        sa.text(f"INSERT INTO {SCRATCH_TABLE} (value) VALUES (:value)"),
        {"value": value},
    )


def test_commit_rollback_commit_sequence_never_leaks_to_another_connection(
    db_session, _engine, _scratch_table
):
    # Realistic service pattern: write + commit, then (e.g. on a later,
    # unrelated failure) rollback, then more writes + commit.
    _insert(db_session, "keep-1")
    db_session.commit()

    _insert(db_session, "discard")
    db_session.rollback()

    _insert(db_session, "keep-2")
    db_session.commit()

    # Within this session, the rolled-back row is gone and both committed
    # rows are visible — the fixture must still behave like a normal
    # session for the code under test.
    values_in_session = {
        row[0]
        for row in db_session.execute(
            sa.text(f"SELECT value FROM {SCRATCH_TABLE}")
        ).all()
    }
    assert values_in_session == {"keep-1", "keep-2"}

    # Crucially: a second, independent connection — outside db_session's
    # transaction tree — must see NONE of this. If it does, the fixture's
    # outer transaction (rolled back at this test's teardown) actually
    # committed for real at some point, and data would leak into later
    # tests.
    with _engine.connect() as other_connection:
        count = other_connection.execute(
            sa.text(f"SELECT count(*) FROM {SCRATCH_TABLE}")
        ).scalar()

    assert count == 0, (
        "rows committed via db_session are visible to another connection "
        "— a commit/rollback/commit sequence leaked a real commit past "
        "the fixture's SAVEPOINT isolation"
    )
