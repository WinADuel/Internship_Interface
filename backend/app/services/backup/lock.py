"""One backup at a time (Phase 3 spec §4.4): the db-backup job (nightly and
pre-deploy) and the Back up now route share a session-level Postgres
advisory lock. The route gives up at once (409); the job waits for a manual
backup to finish.

As with the scan lock (app/services/discovery/scanner.py), the lock lives on
a dedicated autocommit connection, not on a Session, which hands its
connection back to the pool at every commit. If the unlock fails the
connection is invalidated, which ends its database session and so releases
the lock."""

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine, text

logger = logging.getLogger(__name__)

# Fixed key for pg_(try_)advisory_lock: "DBBACKUP" in ASCII, inside bigint
# and distinct from the scan lock ("JOBSCAN").
BACKUP_LOCK_KEY = int.from_bytes(b"DBBACKUP", "big")
POLL_SECONDS = 2.0


def _try_lock(conn: Connection) -> bool:
    return bool(
        conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": BACKUP_LOCK_KEY}).scalar_one()
    )


def _unlock(conn: Connection) -> None:
    try:
        released = conn.execute(
            text("SELECT pg_advisory_unlock(:key)"), {"key": BACKUP_LOCK_KEY}
        ).scalar_one()
    except Exception:  # noqa: BLE001 - the lock must not outlive this call
        logger.exception("could not release the backup lock")
        released = False
    if not released:
        conn.invalidate()


@contextmanager
def backup_lock(
    engine: Engine,
    *,
    wait: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Iterator[bool]:
    """Take the backup lock, trying for up to `wait` seconds. Yields whether
    it was taken; when it was, it is released on exit."""
    conn = engine.connect()
    acquired = False
    try:
        conn.execution_options(isolation_level="AUTOCOMMIT")
        deadline = clock() + wait
        acquired = _try_lock(conn)
        while not acquired and clock() < deadline:
            sleep(POLL_SECONDS)
            acquired = _try_lock(conn)
        yield acquired
    finally:
        if acquired:
            _unlock(conn)
        conn.close()
