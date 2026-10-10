"""The backup lock on real Postgres. "Another backup" holds the lock on a
separate connection."""

import pytest
from sqlalchemy import text

from app.services.backup.lock import BACKUP_LOCK_KEY, backup_lock
from app.services.discovery.scanner import SCAN_LOCK_KEY


@pytest.fixture()
def other_connection(_engine):
    conn = _engine.connect()
    yield conn
    conn.execute(text("SELECT pg_advisory_unlock_all()"))
    conn.rollback()
    conn.close()


def try_lock(conn) -> bool:
    return conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": BACKUP_LOCK_KEY}).scalar_one()


def unlock(conn) -> bool:
    return conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": BACKUP_LOCK_KEY}).scalar_one()


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_key_is_its_own():
    assert BACKUP_LOCK_KEY != SCAN_LOCK_KEY
    assert 0 < BACKUP_LOCK_KEY < 2**63


def test_held_for_the_block_and_released_after(_engine, other_connection):
    with backup_lock(_engine) as locked:
        assert locked
        assert not try_lock(other_connection)
    assert try_lock(other_connection)
    assert unlock(other_connection)


def test_released_when_the_block_raises(_engine, other_connection):
    with pytest.raises(RuntimeError), backup_lock(_engine) as locked:
        assert locked
        raise RuntimeError("dump crashed")
    assert try_lock(other_connection)


def test_busy_without_waiting(_engine, other_connection):
    assert try_lock(other_connection)
    clock = Clock()
    with backup_lock(_engine, sleep=clock.sleep, clock=clock) as locked:
        assert not locked
    assert clock.sleeps == []
    # Not taking it never releases the other holder's lock.
    assert unlock(other_connection) is True


def test_waits_until_the_other_backup_finishes(_engine, other_connection):
    assert try_lock(other_connection)
    clock = Clock()

    def sleep(seconds):
        clock.sleep(seconds)
        if len(clock.sleeps) == 3:
            unlock(other_connection)

    with backup_lock(_engine, wait=60, sleep=sleep, clock=clock) as locked:
        assert locked
        assert not try_lock(other_connection)
    assert clock.sleeps == [2.0, 2.0, 2.0]


def test_gives_up_after_the_wait(_engine, other_connection):
    assert try_lock(other_connection)
    clock = Clock()
    with backup_lock(_engine, wait=10, sleep=clock.sleep, clock=clock) as locked:
        assert not locked
    assert clock.sleeps == [2.0] * 5
