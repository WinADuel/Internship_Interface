import subprocess
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.services.backup import restore
from app.services.backup.crypto import BackupCryptoError
from app.services.backup.dump import BackupError
from app.services.backup.restore import apply_command, check_backup, restore_backup, script_command

URL = "postgresql+psycopg://app:s3cret-pw@db.internal:5433/tracker"
KEY = Fernet.generate_key().decode()
LISTING = """;
; Archive created at 2026-10-08 02:30:05 UTC
;     Dumped from database version: 16.4
;
215; 1259 16390 TABLE public applications app
216; 1259 16400 TABLE public contacts app
3401; 0 16390 TABLE DATA public applications app
"""


def _step(argv):
    return argv[0] + (" --list" if "--list" in argv else "")


class FakeRun:
    """Stands in for subprocess.run: records each call (and whether its
    --file existed at the time) and answers by step: "pg_restore --list",
    "pg_restore" (writing the SQL script) or "psql"."""

    def __init__(self, results=None, raises=None):
        self.calls = []
        self.results = results or {}
        self.raises = raises or {}

    def __call__(self, argv, **kwargs):
        step = _step(argv)
        files = [arg[len("--file="):] for arg in argv if arg.startswith("--file=")]
        self.calls.append((argv, kwargs, {f: Path(f).exists() for f in files}))
        if step in self.raises:
            raise self.raises[step]
        if step == "pg_restore":
            Path(files[0]).write_text("-- SQL script\n")
        default = (0, LISTING.encode() if step == "pg_restore --list" else b"", b"")
        returncode, stdout, stderr = self.results.get(step, default)
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    def programs(self):
        return [_step(argv) for argv, _, _ in self.calls]


@pytest.fixture()
def dump_file(tmp_path):
    path = tmp_path / "tracker-20261008T023005Z.dump"
    path.write_bytes(b"PGDMP fake dump")
    return path


@pytest.fixture()
def enc_file(tmp_path):
    path = tmp_path / "tracker-20261008T023005Z.dump.enc"
    path.write_bytes(Fernet(KEY).encrypt(b"PGDMP fake dump"))
    return path


def test_script_command_writes_sql_without_owners_or_grants(tmp_path):
    assert script_command(Path("in.dump"), tmp_path / "restore.sql") == [
        "pg_restore",
        "--no-owner",
        "--no-privileges",
        f"--file={tmp_path / 'restore.sql'}",
        str(Path("in.dump").resolve()),
    ]


def test_apply_command_runs_everything_in_one_transaction(tmp_path):
    argv = apply_command(tmp_path / "restore.sql")
    assert argv[0] == "psql"
    assert "--single-transaction" in argv
    assert "--set=ON_ERROR_STOP=1" in argv
    assert "--no-psqlrc" in argv
    assert "--no-password" in argv
    # The schema is replaced first, inside the same transaction as the restore.
    command = next(arg for arg in argv if arg.startswith("--command="))
    assert "DROP SCHEMA IF EXISTS public CASCADE" in command
    assert "CREATE SCHEMA public" in command
    assert "lock_timeout" in command
    assert argv.index(command) < argv.index(f"--file={tmp_path / 'restore.sql'}")


def test_restore_checks_converts_then_applies(dump_file):
    run = FakeRun()
    listing = restore_backup(dump_file, URL, None, run=run)
    assert run.programs() == ["pg_restore --list", "pg_restore", "psql"]
    assert listing.tables == ["public.applications", "public.contacts"]

    list_argv, _, _ = run.calls[0]
    assert list_argv[-1] == str(dump_file)

    script_argv, script_kwargs, script_files = run.calls[1]
    assert script_argv[-1] == str(dump_file)
    assert "env" not in script_kwargs  # writing a script needs no connection
    assert script_kwargs["stdin"] is subprocess.DEVNULL

    apply_argv, apply_kwargs, apply_files = run.calls[2]
    sql = next(iter(apply_files))
    assert apply_files[sql] is True  # psql read the script pg_restore wrote
    assert sql == next(iter(script_files))
    assert apply_kwargs["env"]["PGHOST"] == "db.internal"
    assert apply_kwargs["env"]["PGDATABASE"] == "tracker"
    assert apply_kwargs["env"]["PGPASSWORD"] == "s3cret-pw"
    assert apply_kwargs["stdin"] is subprocess.DEVNULL
    assert all("s3cret-pw" not in arg for argv, _, _ in run.calls for arg in argv)

    # The SQL script (the whole database in plain text) is deleted afterwards.
    assert not Path(sql).exists()
    assert not Path(sql).parent.exists()


def test_an_unreadable_dump_is_refused_before_anything_changes(dump_file):
    run = FakeRun(results={"pg_restore --list": (1, b"", b"pg_restore: error: input file is too short\n")})
    with pytest.raises(BackupError, match="not a readable dump: pg_restore: error: input file is too short"):
        restore_backup(dump_file, URL, None, run=run)
    assert run.programs() == ["pg_restore --list"]


def test_psql_failure_reports_its_first_error_line(dump_file):
    stderr = b"psql:/tmp/x/restore.sql:12: ERROR:  relation \"x\" already exists\nmore\n"
    run = FakeRun(results={"psql": (3, b"", stderr)})
    with pytest.raises(BackupError) as excinfo:
        restore_backup(dump_file, URL, None, run=run)
    message = str(excinfo.value)
    assert message.startswith("restore failed (exit 3); the database was not changed: psql:")
    assert 'relation "x" already exists' in message
    sql = next(iter(run.calls[2][2]))
    assert not Path(sql).exists()


def test_script_failure_is_reported(dump_file):
    run = FakeRun(results={"pg_restore": (1, b"", b"pg_restore: error: out of disk\n")})
    with pytest.raises(BackupError, match=r"pg_restore failed \(exit 1\): pg_restore: error: out of disk"):
        restore_backup(dump_file, URL, None, run=run)
    assert run.programs() == ["pg_restore --list", "pg_restore"]


def test_timeouts_and_missing_tools_are_clean_errors(dump_file):
    with pytest.raises(BackupError, match="psql timed out after 30 minutes"):
        restore_backup(dump_file, URL, None, run=FakeRun(raises={"psql": subprocess.TimeoutExpired(["psql"], 1800)}))
    with pytest.raises(BackupError, match="psql is not installed"):
        restore_backup(dump_file, URL, None, run=FakeRun(raises={"psql": FileNotFoundError("psql")}))


def test_a_missing_file_is_a_clean_error(tmp_path):
    run = FakeRun()
    with pytest.raises(BackupError, match="no such file"):
        restore_backup(tmp_path / "nope.dump", URL, None, run=run)
    assert run.calls == []


def test_an_encrypted_copy_is_decrypted_into_the_temp_folder_first(enc_file):
    run = FakeRun()
    seen = {}
    real = run.__call__

    def spy(argv, **kwargs):
        if "--list" in argv:
            seen["path"] = Path(argv[-1])
            seen["bytes"] = seen["path"].read_bytes()
            seen["mode"] = seen["path"].stat().st_mode & 0o777
        return real(argv, **kwargs)

    restore_backup(enc_file, URL, KEY, run=spy)
    assert seen["bytes"] == b"PGDMP fake dump"
    assert seen["mode"] == 0o600
    assert seen["path"].parent != enc_file.parent
    assert run.calls[1][0][-1] == str(seen["path"])  # the decrypted copy is restored
    assert not seen["path"].exists()  # and deleted afterwards
    assert enc_file.exists()


def test_an_encrypted_copy_with_the_wrong_key_fails_before_restoring(enc_file):
    run = FakeRun()
    with pytest.raises(BackupCryptoError, match="wrong BACKUP_ENCRYPTION_KEY"):
        restore_backup(enc_file, URL, Fernet.generate_key().decode(), run=run)
    assert run.calls == []


def test_an_encrypted_copy_needs_the_key(enc_file):
    with pytest.raises(BackupCryptoError, match="BACKUP_ENCRYPTION_KEY is not set"):
        restore_backup(enc_file, URL, None, run=FakeRun())


def test_restore_timeout_constant_is_generous():
    assert restore.RESTORE_TIMEOUT >= 15 * 60


def test_check_reads_the_file_without_connecting(dump_file):
    run = FakeRun()
    listing = check_backup(dump_file, None, run=run)
    assert run.programs() == ["pg_restore --list"]
    assert "env" not in run.calls[0][1]
    assert listing.created_at == "2026-10-08 02:30:05 UTC"


def test_check_decrypts_an_encrypted_copy_and_cleans_up(enc_file):
    run = FakeRun()
    check_backup(enc_file, KEY, run=run)
    listed = Path(run.calls[0][0][-1])
    assert listed.name == "tracker-20261008T023005Z.dump"
    assert not listed.exists()
    with pytest.raises(BackupCryptoError, match="wrong BACKUP_ENCRYPTION_KEY"):
        check_backup(enc_file, Fernet.generate_key().decode(), run=run)


def test_check_of_a_missing_file(tmp_path):
    with pytest.raises(BackupError, match="no such file"):
        check_backup(tmp_path / "nope.dump.enc", KEY, run=FakeRun())
