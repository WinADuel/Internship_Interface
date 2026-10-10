"""Backup retention (Phase 3 spec §4.4): keep the newest dumps per label.

Only files named exactly like a dump (`tracker-<UTC time>.dump`) are ever
deleted, so anything else put in the folder by hand is left alone. The
timestamp in the name sorts in time order, so "newest" is the last name."""

import logging
import time
from pathlib import Path

from app.services.backup.dump import DUMP_NAME_RE, PARTIAL_SUFFIX

logger = logging.getLogger(__name__)

KEEP = {"nightly": 14, "pre-deploy": 5, "manual": 5}
# A `.partial` file older than this was left by a dump that was killed
# (the container stopped mid-dump); a running dump is never this old.
STALE_PARTIAL_SECONDS = 24 * 3600


def dumps(folder: Path) -> list[Path]:
    """The dump files in `folder`, oldest first."""
    if not folder.is_dir():
        return []
    return sorted(
        (p for p in folder.iterdir() if DUMP_NAME_RE.match(p.name) and p.is_file() and not p.is_symlink()),
        key=lambda p: p.name,
    )


def prune(backup_dir: str | Path, label: str, now: float | None = None) -> list[Path]:
    """Delete all but the newest KEEP[label] dumps (never the newest one) and
    stale `.partial` leftovers in `<backup_dir>/<label>`. Returns the deleted paths."""
    folder = Path(backup_dir) / label
    keep = max(1, KEEP[label])
    found = dumps(folder)
    doomed = found[:-keep]
    if folder.is_dir():
        cutoff = (time.time() if now is None else now) - STALE_PARTIAL_SECONDS
        for p in folder.iterdir():
            name = p.name
            if (
                name.endswith(PARTIAL_SUFFIX)
                and DUMP_NAME_RE.match(name[: -len(PARTIAL_SUFFIX)])
                and p.is_file()
                and not p.is_symlink()
                and p.stat().st_mtime < cutoff
            ):
                doomed.append(p)
    deleted = []
    for p in doomed:
        try:
            p.unlink()
            deleted.append(p)
        except FileNotFoundError:
            pass
    if deleted:
        logger.info("backup retention: deleted %d old %s file(s)", len(deleted), label)
    return deleted
