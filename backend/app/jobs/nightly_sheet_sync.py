"""Nightly full re-sync of the backup sheet (spec §13.7), run as its own
Docker Compose service: `python -m app.jobs.nightly_sheet_sync`.
Repairs anything a failed on-change sync missed."""

import logging
import time
from datetime import datetime, timedelta

from app.db.session import SessionLocal
from app.services.sheet_sync_service import ALL_TABS, google_sheets_client, safe_sync

logger = logging.getLogger(__name__)

RUN_HOUR = 3  # local time (the container's TZ)


def seconds_until_next_run(now: datetime, hour: int = RUN_HOUR) -> float:
    next_run = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return (next_run - now).total_seconds()


def run_once() -> bool:
    db = SessionLocal()
    try:
        return safe_sync(db, google_sheets_client, ALL_TABS)
    finally:
        db.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    while True:
        time.sleep(seconds_until_next_run(datetime.now()))
        try:
            ok = run_once()
            logger.info("nightly sheet sync %s", "succeeded" if ok else "failed (see Settings)")
        except Exception:  # noqa: BLE001 - keep the loop alive (e.g. DB briefly down)
            logger.exception("nightly sheet sync crashed")


if __name__ == "__main__":
    main()
