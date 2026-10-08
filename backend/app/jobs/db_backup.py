"""Database backups (Phase 3 spec §4.4), run as their own Docker Compose
service: `python -m app.jobs.db_backup` dumps the database nightly at 02:30
local time (the container's TZ). `python -m app.jobs.db_backup --once --label
pre-deploy` takes one backup and exits 0 on success, 1 on failure; deploy.sh
uses it before every deploy.

Dumps go to `<BACKUP_DIR>/<label>/`; see app/services/backup."""

import argparse
import logging
import sys
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.backup.dump import LABELS
from app.services.backup.service import AfterBackup, BackupResult, run_backup

logger = logging.getLogger(__name__)

RUN_HOUR = 2  # local time (the container's TZ)
RUN_MINUTE = 30

# Steps run after a successful backup, by label. The off-site copy hooks in
# here for "nightly" (spec §4.4 part 2); pre-deploy and manual dumps stay local.
AFTER_BACKUP: dict[str, AfterBackup] = {}


def seconds_until_next_run(now: datetime, hour: int = RUN_HOUR, minute: int = RUN_MINUTE) -> float:
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return (next_run - now).total_seconds()


def run_once(label: str) -> BackupResult:
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
    now: Callable[[], datetime] = datetime.now,
) -> None:
    while True:
        sleep(seconds_until_next_run(now()))
        try:
            result = run_once("nightly")
            logger.info("nightly backup %s", "succeeded" if result.ok else "failed (see Settings)")
        except Exception:  # noqa: BLE001 - keep the loop alive (e.g. DB briefly down)
            logger.exception("nightly backup crashed")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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
