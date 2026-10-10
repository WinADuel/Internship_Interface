"""Job discovery scans (Phase 2 spec §5), run as their own Docker Compose
service: `python -m app.jobs.job_scan`. Scans once a minute after start-up,
then every `discovery_scan_hours` hours (re-read before each wait). A scan
that crashed is retried in ten minutes instead, since the cause is usually
passing (the database restarting, say) and the full interval would leave
discovery idle for hours. Scan now uses the same `run_scan`; the advisory
lock keeps the two from overlapping.

The daily re-score of local scores (Phase 5 spec §4) is checked at start-up
and then at least once an hour (`CHECK_EVERY`): waits are slept in steps of
at most an hour with a check after each. The check is one small query until
the last re-score is 20 hours old, so the freshness points never go much
more than a day without a refresh, however long the scan interval, and a
re-score that failed is tried again within the hour."""

import logging
import time
from collections.abc import Callable

from app.db.session import SessionLocal
from app.jobs import configure_job_logging
from app.services.discovery.http import DiscoveryHttp, HttpxDiscoveryHttp
from app.services.discovery.scanner import ScanReport, rescore_if_due, run_scan
from app.services.settings_service import get_settings

logger = logging.getLogger(__name__)

STARTUP_DELAY = 60.0  # seconds: let the database come up first
DEFAULT_SCAN_HOURS = 6  # used when the settings cannot be read
MIN_SCAN_HOURS = 1
RETRY_DELAY = 600.0  # seconds to wait after a scan that crashed
CHECK_EVERY = 3600.0  # seconds: the longest wait between two re-score checks


def run_once(http: DiscoveryHttp) -> ScanReport | None:
    db = SessionLocal()
    try:
        return run_scan(db, http)
    finally:
        db.close()


def rescore_once() -> bool | None:
    db = SessionLocal()
    try:
        return rescore_if_due(db)
    finally:
        db.close()


def check_rescore() -> None:
    """The daily re-score, if it is due. Never raises: a failure is logged
    and the next check tries again."""
    try:
        if rescore_once():
            logger.info("daily re-score done")
    except Exception:  # noqa: BLE001 - keep the loop alive
        logger.exception("daily re-score failed; trying again at the next check")


def wait(seconds: float, sleep: Callable[[float], None]) -> None:
    """Sleep `seconds` in steps of at most CHECK_EVERY, checking the daily
    re-score after each step."""
    remaining = seconds
    while remaining > 0:
        step = min(remaining, CHECK_EVERY)
        sleep(step)
        remaining -= step
        check_rescore()


def scan_interval_seconds() -> float:
    db = SessionLocal()
    try:
        hours = get_settings(db).discovery_scan_hours
    finally:
        db.close()
    return max(MIN_SCAN_HOURS, hours) * 3600.0


def run_forever(http: DiscoveryHttp, sleep: Callable[[float], None] = time.sleep) -> None:
    sleep(STARTUP_DELAY)
    check_rescore()
    while True:
        try:
            report = run_once(http)
            if report is None:
                logger.info("job scan skipped: another scan is running")
            else:
                logger.info(
                    "job scan done: %d added, %d closed, %d removed, %d source error(s)",
                    report.added,
                    report.closed,
                    report.removed,
                    len(report.errors),
                )
        except Exception:  # noqa: BLE001 - keep the loop alive (e.g. DB briefly down)
            logger.exception("job scan crashed; retrying in %.0f seconds", RETRY_DELAY)
            # Not even the settings are read: whatever broke the scan (the
            # database being down, say) would break reading them too.
            wait(RETRY_DELAY, sleep)
            continue
        try:
            interval = scan_interval_seconds()
        except Exception:  # noqa: BLE001
            logger.exception("could not read the scan interval; using the default")
            interval = DEFAULT_SCAN_HOURS * 3600.0
        wait(interval, sleep)


def main() -> None:
    configure_job_logging()
    run_forever(HttpxDiscoveryHttp())


if __name__ == "__main__":
    main()
