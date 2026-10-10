"""Dropping the throwaway databases that some tests create next to the test
database (backup round trips, migrations)."""

import time

from psycopg import errors as pg_errors
from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError


def drop_database(admin: Engine, name: str, attempts: int = 20, delay: float = 0.5) -> None:
    """`DROP DATABASE ... WITH (FORCE)`, retried. The autovacuum launcher
    visits a new database soon after it is created, and FORCE may not end
    that worker (it runs as a superuser), so the drop can fail with
    "permission denied to terminate process" until the worker is done."""
    for attempt in range(attempts):
        try:
            with admin.connect() as conn:
                conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            return
        except DBAPIError as exc:
            retryable = isinstance(exc.orig, (pg_errors.InsufficientPrivilege, pg_errors.ObjectInUse))
            if not retryable or attempt == attempts - 1:
                raise
            time.sleep(delay)
