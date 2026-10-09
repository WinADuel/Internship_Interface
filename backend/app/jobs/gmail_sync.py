"""Gmail sync (Phase 6 spec §6), run as its own Docker Compose service:
`python -m app.jobs.gmail_sync`. Syncs once a minute after start-up, then
every `gmail_sync_minutes` minutes (re-read before each wait). While sync is
off or Gmail isn't granted a run does nothing but the retention cleanup. A
run that crashed is retried in ten minutes. Sync now uses the same
`run_sync`; the advisory lock keeps the two from overlapping. Changes made
by auto-apply are copied to the backup sheet right after the run, as a
click in the app would."""

import logging
import time
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.jobs import configure_job_logging
from app.services.gmail.sync import (
    GMAIL_PERMISSION_MISSING,
    GmailClientFactory,
    SyncReport,
    google_gmail_client,
    run_sync,
)
from app.services.settings_service import get_settings
from app.services.sheet_sync_service import ALL_TABS, google_sheets_client, safe_sync
from app.services.sheets_client import SheetsClient

logger = logging.getLogger(__name__)

STARTUP_DELAY = 60.0  # seconds: let the database come up first
DEFAULT_MINUTES = 30  # used when the settings cannot be read
MIN_MINUTES = 15
RETRY_DELAY = 600.0  # seconds to wait after a run that crashed


def run_once(
    client_factory: GmailClientFactory = google_gmail_client,
    sheets_factory: Callable[[Session], SheetsClient] = google_sheets_client,
) -> SyncReport:
    db = SessionLocal()
    try:
        report = run_sync(db, client_factory)
        if report.sheet_tabs:
            safe_sync(db, sheets_factory, [t for t in ALL_TABS if t in report.sheet_tabs])
        return report
    finally:
        db.close()


def sync_interval_seconds() -> float:
    db = SessionLocal()
    try:
        minutes = get_settings(db).gmail_sync_minutes
    finally:
        db.close()
    return max(MIN_MINUTES, minutes) * 60.0


def _log(report: SyncReport) -> None:
    if report.status == "busy":
        logger.info("gmail sync skipped: another sync is running")
    elif report.status == "ok":
        logger.info(
            "gmail sync done: %d new, %d fetched, %d suggestion(s), %d auto-applied, %d skipped%s",
            report.listed,
            report.fetched,
            report.suggested,
            report.auto_applied,
            report.skipped,
            "; more next run" if report.more else "",
        )
    elif report.status == "error":
        logger.warning("gmail sync failed: %s", report.error)
    elif report.status == "not_granted":
        logger.warning("gmail sync is on but cannot run: %s", GMAIL_PERMISSION_MISSING)
    # "disabled" is the normal state of an install that never turned Gmail
    # sync on: nothing is logged.
    if report.deleted:
        logger.info("gmail retention: deleted %d old suggestion(s)", report.deleted)


def run_forever(
    client_factory: GmailClientFactory = google_gmail_client,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    sleep(STARTUP_DELAY)
    while True:
        try:
            _log(run_once(client_factory))
        except Exception:  # noqa: BLE001 - keep the loop alive (e.g. DB briefly down)
            logger.exception("gmail sync crashed; retrying in %.0f seconds", RETRY_DELAY)
            sleep(RETRY_DELAY)
            continue
        try:
            interval = sync_interval_seconds()
        except Exception:  # noqa: BLE001
            logger.exception("could not read the gmail sync interval; using the default")
            interval = DEFAULT_MINUTES * 60.0
        sleep(interval)


def main() -> None:
    configure_job_logging()
    run_forever()


if __name__ == "__main__":
    main()
