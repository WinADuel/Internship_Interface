"""Session-level Postgres advisory locks on a dedicated connection.

The lock lives on a connection of its own, opened from the engine in
autocommit mode, not on a Session: a Session bound to an Engine hands its
connection back to the pool at every commit, so a lock taken through it could
be left on a pooled connection and an unlock could run on a different one,
which would leak the lock. If the unlock fails the connection is invalidated,
which ends its database session and so releases the lock.

Used by the discovery scan, the backups and the Gmail sync, each with its own
fixed key."""

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine, text

logger = logging.getLogger(__name__)

POLL_SECONDS = 2.0


def _try_lock(conn: Connection, key: int) -> bool:
    return bool(conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar_one())


def _unlock(conn: Connection, key: int) -> None:
    try:
        released = conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key}).scalar_one()
    except Exception:  # noqa: BLE001 - the lock must not outlive this call
        logger.exception("could not release the advisory lock %d", key)
        released = False
    if not released:
        # Closing the database session is what finally releases the lock.
        conn.invalidate()


@contextmanager
def advisory_lock(
    engine: Engine,
    key: int,
    *,
    wait: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Iterator[bool]:
    """Take the session-level advisory lock `key`, trying for up to `wait`
    seconds. Yields whether it was taken; when it was, it is released on exit."""
    conn = engine.connect()
    acquired = False
    try:
        conn.execution_options(isolation_level="AUTOCOMMIT")
        deadline = clock() + wait
        acquired = _try_lock(conn, key)
        while not acquired and clock() < deadline:
            sleep(POLL_SECONDS)
            acquired = _try_lock(conn, key)
        yield acquired
    finally:
        if acquired:
            _unlock(conn, key)
        conn.close()
