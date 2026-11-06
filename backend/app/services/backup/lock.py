"""One backup at a time (Phase 3 spec §4.4): the db-backup job (nightly and
pre-deploy) and the Back up now route share a session-level Postgres
advisory lock. The route gives up at once (409); the job waits for a manual
backup to finish.

As with the scan lock (app/services/discovery/scanner.py), the lock lives on
a dedicated autocommit connection, not on a Session, which hands its
connection back to the pool at every commit. If the unlock fails the
connection is invalidated, which ends its database session and so releases
the lock. The generic `advisory_lock` lives in app/db/locks.py."""

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy import Engine

from app.db.locks import advisory_lock

# Fixed key for pg_(try_)advisory_lock: "DBBACKUP" in ASCII, inside bigint
# and distinct from the scan lock ("JOBSCAN").
BACKUP_LOCK_KEY = int.from_bytes(b"DBBACKUP", "big")


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
    with advisory_lock(engine, BACKUP_LOCK_KEY, wait=wait, sleep=sleep, clock=clock) as acquired:
        yield acquired
