import os
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.backup import dump
from app.services.backup.dump import (
    BackupError,
    list_dump,
    parse_listing,
    pg_env,
    run_dump,
)

URL = "postgresql+psycopg://app:s3cret-pw@db.internal:5433/tracker"
NOW = datetime(2026, 10, 8, 2, 30, 5, tzinfo=timezone.utc)


class FakeRun:
    """Stands in for subprocess.run: records each call and, by default,
    writes some bytes to the --file path like pg_dump would."""

    def __init__(self, returncode=0, stderr=b"", stdout=b"", write=b"PGDMP fake", raises=None):
        self.calls = []
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout
        self.write = write
        self.raises = raises

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.raises is not None:
            raise self.raises
        for arg in argv:
            if arg.startswith("--file=") and self.write is not None:
                Path(arg[len("--file="):]).write_bytes(self.write)
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


def test_pg_env_takes_the_connection_from_the_url():
    env = pg_env(URL, base={"PATH": "/usr/bin"})
    assert env == {
        "PATH": "/usr/bin",
        "PGHOST": "db.internal",
        "PGPORT": "5433",
        "PGUSER": "app",
        "PGPASSWORD": "s3cret-pw",
        "PGDATABASE": "tracker",
    }


def test_pg_env_decodes_a_percent_encoded_password():
    env = pg_env("postgresql+psycopg://app:p%40ss%3Aw%2Fd@db/tracker", base={})
    assert env["PGPASSWORD"] == "p@ss:w/d"


def test_pg_env_drops_inherited_values_the_url_leaves_out():
    inherited = {"PGHOST": "elsewhere", "PGPASSWORD": "old", "PGPORT": "1"}
    env = pg_env("postgresql+psycopg://app@/tracker", base=inherited)
    assert "PGHOST" not in env and "PGPASSWORD" not in env and "PGPORT" not in env
    assert env["PGUSER"] == "app" and env["PGDATABASE"] == "tracker"


def test_pg_env_copies_os_environ_without_changing_it(monkeypatch):
    monkeypatch.setenv("KEEP_ME", "1")
    monkeypatch.delenv("PGPASSWORD", raising=False)
    env = pg_env(URL)
    assert env["KEEP_ME"] == "1"
    assert "PGPASSWORD" not in os.environ


def test_run_dump_command_line_and_env(tmp_path):
    run = FakeRun()
    path = run_dump(URL, tmp_path, "nightly", NOW, run=run)

    assert path == tmp_path / "nightly" / "tracker-20261008T023005Z.dump"
    assert path.read_bytes() == b"PGDMP fake"
    [(argv, kwargs)] = run.calls
    assert argv == [
        "pg_dump",
        "--format=custom",
        "--no-password",
        f"--file={tmp_path / 'nightly' / 'tracker-20261008T023005Z.dump.partial'}",
    ]
    assert isinstance(argv, list)
    assert "shell" not in kwargs
    assert kwargs["timeout"] == dump.DUMP_TIMEOUT
    assert kwargs["capture_output"] is True
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["env"]["PGPASSWORD"] == "s3cret-pw"
    assert kwargs["env"]["PGDATABASE"] == "tracker"


def test_password_never_appears_in_argv(tmp_path):
    run = FakeRun()
    run_dump(URL, tmp_path, "manual", NOW, run=run)
    argv = run.calls[0][0]
    assert not any("s3cret-pw" in arg for arg in argv)
    assert not any("postgresql" in arg for arg in argv)


def test_dump_name_uses_utc(tmp_path):
    chicago = timezone(timedelta(hours=-5))
    path = run_dump(URL, tmp_path, "manual", datetime(2026, 10, 7, 21, 30, tzinfo=chicago), run=FakeRun())
    assert path.name == "tracker-20261008T023000Z.dump"


def test_dump_and_folders_are_private(tmp_path):
    backup_dir = tmp_path / "backups"
    path = run_dump(URL, backup_dir, "pre-deploy", NOW, run=FakeRun())
    assert stat.S_IMODE(backup_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_existing_open_folder_is_tightened(tmp_path):
    (tmp_path / "manual").mkdir(mode=0o755)
    (tmp_path / "manual").chmod(0o755)
    run_dump(URL, tmp_path, "manual", NOW, run=FakeRun())
    assert stat.S_IMODE((tmp_path / "manual").stat().st_mode) == 0o700


def test_partial_file_is_private_before_pg_dump_runs(tmp_path):
    seen = {}

    def run(argv, **kwargs):
        partial = Path(argv[-1][len("--file="):])
        seen["mode"] = stat.S_IMODE(partial.stat().st_mode)
        partial.write_bytes(b"data")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    run_dump(URL, tmp_path, "manual", NOW, run=run)
    assert seen["mode"] == 0o600


def test_failure_leaves_no_files_and_reports_the_first_stderr_line(tmp_path):
    stderr = (
        b'pg_dump: error: connection to server at "db" (172.18.0.2), port 5432 failed: '
        b'FATAL:  password authentication failed for user "app"\nsecond line\n'
    )
    run = FakeRun(returncode=1, stderr=stderr)
    with pytest.raises(BackupError) as excinfo:
        run_dump(URL, tmp_path, "nightly", NOW, run=run)
    message = str(excinfo.value)
    assert message.startswith("pg_dump failed (exit 1): pg_dump: error: connection to server")
    assert "second line" not in message
    assert "s3cret-pw" not in message
    assert list((tmp_path / "nightly").iterdir()) == []


def test_error_detail_is_one_clean_capped_line(tmp_path):
    run = FakeRun(returncode=1, stderr=b"\n  \nbad\x1b[31m\ttext\x00" + b"x" * 1000 + b"\nmore")
    with pytest.raises(BackupError) as excinfo:
        run_dump(URL, tmp_path, "nightly", NOW, run=run)
    message = str(excinfo.value)
    assert "\x1b" not in message and "\x00" not in message and "\t" not in message
    assert "more" not in message
    assert len(message) <= len("pg_dump failed (exit 1): ") + dump.ERROR_DETAIL_LIMIT


def test_empty_stderr_still_gives_a_message(tmp_path):
    with pytest.raises(BackupError, match="no error output"):
        run_dump(URL, tmp_path, "nightly", NOW, run=FakeRun(returncode=2, stderr=b""))


def test_timeout_is_reported_and_cleaned_up(tmp_path):
    run = FakeRun(raises=subprocess.TimeoutExpired(["pg_dump"], 900))
    with pytest.raises(BackupError, match="timed out after 15 minutes"):
        run_dump(URL, tmp_path, "nightly", NOW, run=run)
    assert list((tmp_path / "nightly").iterdir()) == []


def test_missing_pg_dump_is_reported(tmp_path):
    with pytest.raises(BackupError, match="pg_dump is not installed"):
        run_dump(URL, tmp_path, "nightly", NOW, run=FakeRun(raises=FileNotFoundError("pg_dump")))


def test_empty_dump_is_a_failure(tmp_path):
    with pytest.raises(BackupError, match="empty file"):
        run_dump(URL, tmp_path, "nightly", NOW, run=FakeRun(write=b""))
    assert list((tmp_path / "nightly").iterdir()) == []


def test_unknown_label_is_refused_before_running_anything(tmp_path):
    run = FakeRun()
    with pytest.raises(BackupError, match="unknown backup label"):
        run_dump(URL, tmp_path, "../etc", NOW, run=run)
    assert run.calls == []
    assert list(tmp_path.iterdir()) == []


def test_unwritable_backup_folder_is_a_clean_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    run = FakeRun()
    with pytest.raises(BackupError, match="cannot write to the backup folder"):
        run_dump(URL, blocker, "nightly", NOW, run=run)
    assert run.calls == []


def test_failed_dump_keeps_an_earlier_dump_with_the_same_name(tmp_path):
    first = run_dump(URL, tmp_path, "manual", NOW, run=FakeRun(write=b"good"))
    with pytest.raises(BackupError):
        run_dump(URL, tmp_path, "manual", NOW, run=FakeRun(returncode=1, write=b"half"))
    assert first.read_bytes() == b"good"


LISTING = """;
; Archive created at 2026-10-08 02:30:05 UTC
;     dbname: tracker
;     TOC Entries: 9
;     Dumped from database version: 16.4 (Debian 16.4-1.pgdg120+2)
;     Dumped by pg_dump version: 16.4
;
; Selected TOC Entries:
;
215; 1259 16386 TABLE public applications app
214; 1259 16385 SEQUENCE public applications_id_seq app
3412; 0 16386 TABLE DATA public applications app
216; 1259 16390 TABLE public app_settings app
3413; 0 16390 TABLE DATA public app_settings app
3260; 2606 16392 CONSTRAINT public applications applications_pkey app
"""


def test_parse_listing_counts_entries_and_tables():
    listing = parse_listing(LISTING)
    assert listing.entries == 6
    assert listing.tables == ["public.applications", "public.app_settings"]
    assert listing.database_version == "16.4 (Debian 16.4-1.pgdg120+2)"
    assert listing.created_at == "2026-10-08 02:30:05 UTC"


def test_list_dump_runs_pg_restore_list(tmp_path):
    run = FakeRun(stdout=LISTING.encode())
    listing = list_dump(tmp_path / "x.dump", run=run)
    [(argv, kwargs)] = run.calls
    assert argv == ["pg_restore", "--list", str(tmp_path / "x.dump")]
    assert "shell" not in kwargs and kwargs["timeout"] == dump.LIST_TIMEOUT
    assert listing.entries == 6


def test_list_dump_makes_a_relative_path_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run = FakeRun(stdout=LISTING.encode())
    list_dump("-weird.dump", run=run)
    assert run.calls[0][0][-1] == str(tmp_path / "-weird.dump")


def test_list_dump_reports_an_unreadable_file(tmp_path):
    run = FakeRun(returncode=1, stderr=b'pg_restore: error: input file does not appear to be a valid archive\n')
    with pytest.raises(BackupError, match="not a readable dump: pg_restore: error: input file"):
        list_dump(tmp_path / "x.dump", run=run)


def test_list_dump_with_no_entries_is_unreadable(tmp_path):
    with pytest.raises(BackupError, match="listed no entries"):
        list_dump(tmp_path / "x.dump", run=FakeRun(stdout=b";\n; nothing\n"))
