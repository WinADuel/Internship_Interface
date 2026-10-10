"""Nightly full re-sync of the backup sheet (spec §13.7), run as its own
Docker Compose service: `python -m app.jobs.nightly_sheet_sync`.
Repairs anything a failed on-change sync missed."""

import logging
import time
from collections.abc import Callable
from datetime import datetime

from app.db.session import SessionLocal
from app.jobs import configure_job_logging
from app.jobs.schedule import utc_now, wait_for_daily_run
from app.services.sheet_sync_service import ALL_TABS, google_sheets_client, safe_sync

logger = logging.getLogger(__name__)

RUN_HOUR = 3  # local time (the container's TZ; see app/jobs/schedule)
RUN_MINUTE = 0


def run_once() -> bool:
    db = SessionLocal()
    try:
        return safe_sync(db, google_sheets_client, ALL_TABS)
    finally:
        db.close()


def run_forever(
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = utc_now,
) -> None:
    while True:
        wait_for_daily_run(RUN_HOUR, RUN_MINUTE, sleep=sleep, now=now)
        try:
            ok = run_once()
            logger.info("nightly sheet sync %s", "succeeded" if ok else "failed (see Settings)")
        except Exception:  # noqa: BLE001 - keep the loop alive (e.g. DB briefly down)
            logger.exception("nightly sheet sync crashed")


def main() -> None:
    configure_job_logging()
    run_forever()


if __name__ == "__main__":
    main()
