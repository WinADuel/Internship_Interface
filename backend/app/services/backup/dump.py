"""Run `pg_dump` / `pg_restore --list` for the backup job and the CLI.

The connection comes from `DATABASE_URL` and reaches the client tools through
the libpq environment (PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE), so the
password is never on a command line, where `ps` would show it. Commands are
argument lists run without a shell."""

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

LABELS = ("nightly", "pre-deploy", "manual")
DUMP_TIMEOUT = 15 * 60  # seconds
LIST_TIMEOUT = 2 * 60  # seconds
TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
# tracker-20261008T023000Z.dump: the only names retention will ever delete.
DUMP_NAME_RE = re.compile(r"^tracker-\d{8}T\d{6}Z\.dump$")
PARTIAL_SUFFIX = ".partial"
DIR_MODE = 0o700  # a dump holds the whole database
FILE_MODE = 0o600
ERROR_DETAIL_LIMIT = 300

Runner = Callable[..., subprocess.CompletedProcess]

# libpq variables taken from DATABASE_URL; any inherited value is dropped when
# the URL leaves one out, so a stray PGHOST in the environment can't redirect the dump.
_PG_ENV_KEYS = ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE")


class BackupError(Exception):
    """A dump or listing failed. The message is one line, safe to log and to
    show in Settings: no password, no control characters."""


def pg_env(database_url: str, base: dict[str, str] | None = None) -> dict[str, str]:
    """A copy of `base` (default: os.environ) plus the libpq connection
    variables for `database_url`."""
    url = make_url(database_url)
    env = dict(os.environ if base is None else base)
    values = {
        "PGHOST": url.host,
        "PGPORT": str(url.port) if url.port is not None else None,
        "PGUSER": url.username,
        "PGPASSWORD": url.password,
        "PGDATABASE": url.database,
    }
    for key in _PG_ENV_KEYS:
        value = values[key]
        if value:
            env[key] = value
        else:
            env.pop(key, None)
    return env


def dump_command(path: Path) -> list[str]:
    # --no-password: fail at once instead of waiting for a prompt nobody can answer.
    return ["pg_dump", "--format=custom", "--no-password", f"--file={path}"]


def list_command(path: Path) -> list[str]:
    # An absolute path can't be mistaken for an option.
    return ["pg_restore", "--list", os.path.abspath(path)]


def dump_path(backup_dir: str | Path, label: str, now: datetime) -> Path:
    stamp = now.astimezone(timezone.utc).strftime(TIMESTAMP_FORMAT)
    return Path(backup_dir) / label / f"tracker-{stamp}.dump"


def clean_detail(text: str) -> str:
    """Printable characters only, one line, capped."""
    cleaned = "".join(ch if ch.isprintable() else " " for ch in text)
    return " ".join(cleaned.split())[:ERROR_DETAIL_LIMIT]


def _first_line(stderr: bytes | str | None) -> str:
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    for line in (stderr or "").splitlines():
        if line.strip():
            return clean_detail(line)
    return "no error output"


def _make_private_dir(path: Path) -> None:
    path.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    # mkdir's mode is filtered by the umask and skipped if the folder existed.
    # Best effort: a folder someone else owns but lets us write to still works.
    try:
        path.chmod(DIR_MODE)
    except PermissionError:
        pass


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def run_dump(
    database_url: str,
    backup_dir: str | Path,
    label: str,
    now: datetime | None = None,
    *,
    run: Runner = subprocess.run,
    timeout: float = DUMP_TIMEOUT,
) -> Path:
    """Dump the database to `<backup_dir>/<label>/tracker-<UTC time>.dump` and
    return the path. The dump is written to a `.partial` file in the same
    directory and renamed into place only once pg_dump succeeds, so a
    `.dump` file is always complete. Raises BackupError."""
    if label not in LABELS:
        raise BackupError(f"unknown backup label {label!r}; use one of {', '.join(LABELS)}")
    final = dump_path(backup_dir, label, now or datetime.now(timezone.utc))
    partial = final.with_name(final.name + PARTIAL_SUFFIX)
    try:
        _make_private_dir(Path(backup_dir))
        _make_private_dir(final.parent)
        # Create the file 0600 before pg_dump opens it (it keeps the mode).
        os.close(os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE))
        os.chmod(partial, FILE_MODE)
    except OSError as exc:
        raise BackupError(f"cannot write to the backup folder: {clean_detail(exc.strerror or str(exc))}") from None

    try:
        try:
            result = run(
                dump_command(partial),
                env=pg_env(database_url),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise BackupError(f"pg_dump timed out after {timeout / 60:.0f} minutes") from None
        except FileNotFoundError:
            raise BackupError("pg_dump is not installed (PostgreSQL 16 client tools needed)") from None
        if result.returncode != 0:
            raise BackupError(f"pg_dump failed (exit {result.returncode}): {_first_line(result.stderr)}")
        try:
            if partial.stat().st_size == 0:
                raise BackupError("pg_dump wrote an empty file")
            fd = os.open(partial, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(partial, final)
            _fsync_dir(final.parent)
        except OSError as exc:
            raise BackupError(f"cannot save the dump: {clean_detail(exc.strerror or str(exc))}") from None
    finally:
        partial.unlink(missing_ok=True)
    return final


@dataclass(frozen=True)
class DumpListing:
    entries: int  # TOC entries
    tables: list[str]  # schema.table, in archive order
    database_version: str | None
    created_at: str | None


_TOC_TABLE_RE = re.compile(r"^\d+; \d+ \d+ TABLE (?!DATA )(\S+) (\S+) ")
_HEADER_RE = {
    "database_version": re.compile(r"^;\s+Dumped from database version: (.+)$"),
    "created_at": re.compile(r"^;\s+Archive created at (.+)$"),
}


def parse_listing(text: str) -> DumpListing:
    entries = 0
    tables: list[str] = []
    header: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith(";"):
            for key, pattern in _HEADER_RE.items():
                match = pattern.match(line)
                if match and key not in header:
                    header[key] = clean_detail(match.group(1))
            continue
        if not line.strip():
            continue
        entries += 1
        match = _TOC_TABLE_RE.match(line)
        if match:
            tables.append(f"{match.group(1)}.{match.group(2)}")
    return DumpListing(entries, tables, header.get("database_version"), header.get("created_at"))


def list_dump(path: str | Path, *, run: Runner = subprocess.run, timeout: float = LIST_TIMEOUT) -> DumpListing:
    """`pg_restore --list` a dump to check it is readable. Raises BackupError."""
    try:
        result = run(
            list_command(Path(path)),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise BackupError(f"pg_restore --list timed out after {timeout / 60:.0f} minutes") from None
    except FileNotFoundError:
        raise BackupError("pg_restore is not installed (PostgreSQL 16 client tools needed)") from None
    if result.returncode != 0:
        raise BackupError(f"not a readable dump: {_first_line(result.stderr)}")
    stdout = result.stdout.decode("utf-8", "replace") if isinstance(result.stdout, bytes) else result.stdout
    listing = parse_listing(stdout or "")
    if listing.entries == 0:
        raise BackupError("not a readable dump: pg_restore listed no entries")
    return listing
