"""Job discovery scans (Phase 2 spec §5), run as their own Docker Compose
service: `python -m app.jobs.job_scan`. Scans once a minute after start-up,
then every `discovery_scan_hours` hours (re-read before each wait). Scan now
uses the same `run_scan`; the advisory lock keeps the two from overlapping."""

import logging
import time
from collections.abc import Callable

from app.db.session import SessionLocal
from app.services.discovery.http import DiscoveryHttp, HttpxDiscoveryHttp
from app.services.discovery.scanner import ScanReport, run_scan
from app.services.settings_service import get_settings

logger = logging.getLogger(__name__)

STARTUP_DELAY = 60.0  # seconds: let the database come up first
DEFAULT_SCAN_HOURS = 6  # used when the settings cannot be read
MIN_SCAN_HOURS = 1


def run_once(http: DiscoveryHttp) -> ScanReport | None:
    db = SessionLocal()
    try:
        return run_scan(db, http)
    finally:
        db.close()


def scan_interval_seconds() -> float:
    db = SessionLocal()
    try:
        hours = get_settings(db).discovery_scan_hours
    finally:
        db.close()
    return max(MIN_SCAN_HOURS, hours) * 3600.0


def run_forever(http: DiscoveryHttp, sleep: Callable[[float], None] = time.sleep) -> None:
    sleep(STARTUP_DELAY)
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
            logger.exception("job scan crashed")
        try:
            interval = scan_interval_seconds()
        except Exception:  # noqa: BLE001
            logger.exception("could not read the scan interval; using the default")
            interval = DEFAULT_SCAN_HOURS * 3600.0
        sleep(interval)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run_forever(HttpxDiscoveryHttp())


if __name__ == "__main__":
    main()
