"""Database backups (Phase 3 spec §4.4), run as their own Docker Compose
service: `python -m app.jobs.db_backup` dumps the database nightly at 02:30
local time (the container's TZ). `python -m app.jobs.db_backup --once --label
pre-deploy` takes one backup and exits 0 on success, 1 on failure; deploy.sh
uses it before every deploy.

Dumps go to `<BACKUP_DIR>/<label>/`; see app/services/backup. Each nightly
dump is then encrypted and copied to Google Drive (app/services/backup/offsite).

One backup runs at a time: the job shares an advisory lock with Back up now
(app/services/backup/lock). A manual backup is quick, so the job waits up to
LOCK_WAIT seconds for it rather than skipping; if the lock is still held
after that, this run fails (exit 1 for --once) and records nothing, since the
other backup records its own outcome."""

import argparse
import logging
import sys
import time
from collections.abc import Callable
from datetime import datetime

from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.jobs import configure_job_logging
from app.jobs.schedule import utc_now, wait_for_daily_run
from app.services.backup.dump import DUMP_TIMEOUT, LABELS
from app.services.backup.lock import backup_lock
from app.services.backup.offsite import after_nightly_backup
from app.services.backup.service import AfterBackup, BackupResult, run_backup

logger = logging.getLogger(__name__)

RUN_HOUR = 2  # local time (the container's TZ; see app/jobs/schedule)
RUN_MINUTE = 30
# Longer than any one dump can take, so a running backup always finishes first.
LOCK_WAIT = DUMP_TIMEOUT + 5 * 60
LOCK_BUSY = "another backup is still running"

# Steps run after a successful backup, by label: the off-site copy for
# "nightly" (spec §4.4 part 2); pre-deploy and manual dumps stay local.
AFTER_BACKUP: dict[str, AfterBackup] = {"nightly": after_nightly_backup}


def run_once(label: str) -> BackupResult:
    with backup_lock(engine, wait=LOCK_WAIT) as locked:
        if not locked:
            logger.error("%s backup skipped: %s", label, LOCK_BUSY)
            return BackupResult(label=label, error=LOCK_BUSY)
        db = SessionLocal()
        try:
            result = run_backup(
                db,
                label,
                database_url=settings.database_url,
                backup_dir=settings.backup_dir,
                after=AFTER_BACKUP.get(label),
            )
        finally:
            db.close()
    if not result.status_recorded:
        outcome = "succeeded" if result.ok else "failed"
        logger.warning("%s backup %s, but Settings could not be updated", label, outcome)
    return result


def run_forever(
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = utc_now,
) -> None:
    while True:
        wait_for_daily_run(RUN_HOUR, RUN_MINUTE, sleep=sleep, now=now)
        try:
            result = run_once("nightly")
            logger.info("nightly backup %s", "succeeded" if result.ok else "failed (see Settings)")
        except Exception:  # noqa: BLE001 - keep the loop alive (e.g. DB briefly down)
            logger.exception("nightly backup crashed")


def main(argv: list[str] | None = None) -> int:
    configure_job_logging()
    parser = argparse.ArgumentParser(prog="python -m app.jobs.db_backup")
    parser.add_argument("--once", action="store_true", help="take one backup now and exit (0 = success)")
    parser.add_argument("--label", choices=LABELS, help="folder for --once (default: manual)")
    args = parser.parse_args(argv)
    if args.label and not args.once:
        parser.error("--label needs --once (the nightly loop always uses nightly)")
    if not args.once:
        run_forever()
        return 0  # not reached
    label = args.label or "manual"
    try:
        return 0 if run_once(label).ok else 1
    except Exception:  # noqa: BLE001 - report as a failed backup, not a traceback exit code
        logger.exception("%s backup crashed", label)
        return 1


if __name__ == "__main__":
    sys.exit(main())
