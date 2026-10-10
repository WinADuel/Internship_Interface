"""Restore a backup over the live database, for ops/server/restore.sh (Phase 3
spec §4.4), through `python -m app.cli restore <file> --check` (is it
readable?) and then `--yes`, inside the db-backup container with the app
services stopped.

The restore replaces everything in the `public` schema, in one transaction:
pg_restore turns the dump into a SQL script (no connection needed), then psql
runs `DROP SCHEMA public CASCADE; CREATE SCHEMA public` followed by that script
with --single-transaction and ON_ERROR_STOP, so a failure part-way leaves the
database exactly as it was. Dropping the whole schema, rather than
`pg_restore --clean` (which drops only the objects the dump holds), also
removes tables a newer migration added: rolling back to a pre-deploy dump
leaves nothing behind that would trip that migration on the next deploy.

The connection comes from `DATABASE_URL` through the libpq environment, as for
pg_dump (see dump.py), so the password is never on a command line. An
encrypted off-site copy (`.dump.enc`) is decrypted first. The decrypted dump
and the SQL script (the whole database in plain text) live in a private
temporary folder that is always deleted."""

import os
import subprocess
import tempfile
from pathlib import Path

from app.services.backup.crypto import ENC_SUFFIX, decrypt_file
from app.services.backup.dump import BackupError, DumpListing, Runner, _first_line, list_dump, pg_env

RESTORE_TIMEOUT = 30 * 60  # seconds, for each of the two steps

# Run by psql before the script, in the same transaction. client_min_messages
# hides the long "drop cascades to ..." notice; lock_timeout makes a restore
# that something still holds a lock against fail instead of hanging.
PRELUDE = (
    "SET client_min_messages = warning; "
    "SET lock_timeout = '30s'; "
    "DROP SCHEMA IF EXISTS public CASCADE; "
    "CREATE SCHEMA public;"
)


def script_command(dump: Path, sql: Path) -> list[str]:
    # Owners and grants are left out: the restored objects belong to the app's
    # database user, whatever the user was called on the server that made the dump.
    return ["pg_restore", "--no-owner", "--no-privileges", f"--file={sql}", os.path.abspath(dump)]


def apply_command(sql: Path) -> list[str]:
    return [
        "psql",
        "--no-psqlrc",
        "--quiet",
        "--no-password",
        "--single-transaction",
        "--set=ON_ERROR_STOP=1",
        f"--command={PRELUDE}",
        f"--file={sql}",
    ]


def _run_step(run: Runner, argv: list[str], timeout: float, **kwargs) -> subprocess.CompletedProcess:
    program = argv[0]
    try:
        return run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, check=False, **kwargs)
    except subprocess.TimeoutExpired:
        raise BackupError(f"{program} timed out after {timeout / 60:.0f} minutes") from None
    except FileNotFoundError:
        raise BackupError(f"{program} is not installed (PostgreSQL 16 client tools needed)") from None


def _readable_dump(path: Path, encryption_key: str | None, workdir: Path, run: Runner) -> tuple[Path, DumpListing]:
    """The plain dump to use for `path` (decrypted into `workdir` when it is
    a `.dump.enc`) and its listing, which proves pg_restore can read it."""
    if not path.is_file():
        raise BackupError(f"no such file: {path}")
    dump = path
    if path.name.endswith(ENC_SUFFIX):
        dump = workdir / path.name[: -len(ENC_SUFFIX)]
        decrypt_file(path, dump, encryption_key)
    return dump, list_dump(dump, run=run)


def check_backup(path: str | Path, encryption_key: str | None, *, run: Runner = subprocess.run) -> DumpListing:
    """Check that the backup at `path` can be restored (decrypting a
    `.dump.enc` first), without touching the database. Raises BackupError or
    BackupCryptoError."""
    with tempfile.TemporaryDirectory(prefix="tracker-restore-") as workdir:
        return _readable_dump(Path(path), encryption_key, Path(workdir), run)[1]


def restore_backup(
    path: str | Path,
    database_url: str,
    encryption_key: str | None,
    *,
    run: Runner = subprocess.run,
    timeout: float = RESTORE_TIMEOUT,
) -> DumpListing:
    """Replace the database's contents with the backup at `path` (a `.dump`,
    or a `.dump.enc` decrypted with `encryption_key`) and return the dump's
    listing. Raises BackupError (or BackupCryptoError for a `.enc` file);
    nothing in the database changes unless the whole restore succeeds."""
    with tempfile.TemporaryDirectory(prefix="tracker-restore-") as workdir:
        dump, listing = _readable_dump(Path(path), encryption_key, Path(workdir), run)
        sql = Path(workdir) / "restore.sql"
        result = _run_step(run, script_command(dump, sql), timeout)
        if result.returncode != 0:
            raise BackupError(f"pg_restore failed (exit {result.returncode}): {_first_line(result.stderr)}")

        result = _run_step(run, apply_command(sql), timeout, env=pg_env(database_url))
        if result.returncode != 0:
            raise BackupError(
                f"restore failed (exit {result.returncode}); the database was not changed: "
                f"{_first_line(result.stderr)}"
            )
    return listing
