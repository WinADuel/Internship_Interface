"""Once-a-day timing for the nightly jobs (db_backup at 02:30, the sheet sync
at 03:00), in the container's local time zone: the TZ environment variable,
e.g. America/Chicago (docker-compose.yml passes it from .env).

Times are worked out with time-zone-aware datetimes, so a job keeps its local
clock time across daylight-saving changes and runs exactly once on those days:

- Fall back (a local hour happens twice): the job runs at the first of the
  two, and not again at the second.
- Spring forward (the local time doesn't exist that day, e.g. 02:30 when the
  clocks jump from 02:00 to 03:00): the job runs as long after the jump as the
  missing time was after its start, so 02:30 becomes 03:30.

The wait is re-checked on waking, so a sleep that ends early (or a clock that
was changed meanwhile) waits again instead of running at the wrong time."""

import logging
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, tzinfo
from datetime import time as clock_time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


def local_zone() -> tzinfo:
    """The zone named by TZ. Without TZ, the system's current UTC offset (the
    containers always set TZ; this is for running a job by hand). An unknown
    name falls back to UTC, as the C library does."""
    name = os.environ.get("TZ", "").removeprefix(":")
    if not name:
        return datetime.now().astimezone().tzinfo or UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("unknown time zone TZ=%r; using UTC", name)
        return UTC


def next_daily_run(now: datetime, hour: int, minute: int, zone: tzinfo) -> datetime:
    """The first hour:minute local time in `zone` strictly after `now` (an
    aware datetime), in UTC. Only the first of two repeated local times is
    ever returned (fold=0), so a fall-back night runs once; a local time in a
    spring-forward gap maps to the same distance after the jump."""
    # In UTC: Python never counts a repeated local time as equal to one in another zone.
    now = now.astimezone(UTC)
    day = now.astimezone(zone).date()
    while True:
        candidate = datetime.combine(day, clock_time(hour, minute), tzinfo=zone).astimezone(UTC)
        if candidate > now:
            return candidate
        day += timedelta(days=1)


def wait_for_daily_run(
    hour: int,
    minute: int,
    *,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = utc_now,
    zone: tzinfo | None = None,
) -> datetime:
    """Sleeps until the next hour:minute local time and returns it (UTC)."""
    target = next_daily_run(now(), hour, minute, zone or local_zone())
    while (remaining := (target - now()).total_seconds()) > 0:
        sleep(remaining)
    return target
