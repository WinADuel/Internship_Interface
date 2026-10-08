"""End-to-end backup check on the real test Postgres (Phase 3 spec §4.4):
dump a scratch database with committed rows, restore the dump into a second
scratch database, and compare row counts per table.

The usual `db_session` fixture never commits (its writes sit in a rolled-back
transaction), so pg_dump could not see them; this test makes its own
databases instead and always drops them. It needs the PostgreSQL client tools
(pg_dump/pg_restore, version >= the server's) on PATH and a role that may
CREATE DATABASE: skipped locally without the tools, a failure in CI."""

import os
import secrets
import shutil
import subprocess
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.application import Application
from app.models.watch_company import WatchAts, WatchCompany
from app.services import settings_service
from app.services.backup.dump import BackupError, list_dump, pg_env, run_dump
from app.services.backup.service import run_backup

NOW = datetime(2026, 10, 8, 7, 30, tzinfo=timezone.utc)
TEST_DATABASE_URL = os.environ["TEST_DATABASE_URL"]  # loaded from backend/.env by conftest


def _require_client_tools():
    missing = [tool for tool in ("pg_dump", "pg_restore") if shutil.which(tool) is None]
    if missing:
        message = f"{', '.join(missing)} not on PATH"
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)


@pytest.fixture()
def scratch_databases():
    """Two empty scratch databases (source, restore target) as URLs; dropped afterwards."""
    _require_client_tools()
    base = make_url(TEST_DATABASE_URL)
    suffix = secrets.token_hex(4)
    names = [f"tracker_backup_it_{suffix}_src", f"tracker_backup_it_{suffix}_dst"]
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    created = []
    try:
        with admin.connect() as conn:
            for name in names:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
                created.append(name)
        yield [base.set(database=name).render_as_string(hide_password=False) for name in names]
    finally:
        with admin.connect() as conn:
            for name in created:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _row_counts(url: str) -> dict[str, int]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return {
                table.name: conn.scalar(select(func.count()).select_from(table))
                for table in Base.metadata.sorted_tables
            }
    finally:
        engine.dispose()


def test_dump_restores_into_an_empty_database_with_the_same_rows(scratch_databases, tmp_path):
    source_url, target_url = scratch_databases

    source = create_engine(source_url)
    try:
        Base.metadata.create_all(bind=source)
        with Session(source) as db:
            settings_service.get_settings(db)
            db.add_all(
                [
                    Application(company="Acme", role_title="SWE Intern"),
                    Application(company="Globex", role_title="ML Intern", notes="multi\nline"),
                    Application(company="Initech", role_title="Data Intern"),
                    WatchCompany(
                        name="Acme",
                        ats=WatchAts.GREENHOUSE,
                        board_token="acme",
                        careers_url="https://example.com/careers",
                    ),
                ]
            )
            db.commit()

            result = run_backup(db, "manual", database_url=source_url, backup_dir=tmp_path, now=NOW)
            assert result.ok, result.error
            assert result.status_recorded
            assert settings_service.get_settings(db).last_backup_at == NOW
            assert settings_service.get_settings(db).last_backup_error is None
    finally:
        source.dispose()

    dump_file = result.path
    assert dump_file == tmp_path / "manual" / "tracker-20261008T073000Z.dump"
    assert dump_file.stat().st_size > 0
    assert list(dump_file.parent.iterdir()) == [dump_file]  # no .partial left behind

    listing = list_dump(dump_file)
    assert "public.applications" in listing.tables
    assert "public.app_settings" in listing.tables

    target_name = make_url(target_url).database
    restore = subprocess.run(
        ["pg_restore", "--no-owner", "--exit-on-error", f"--dbname={target_name}", str(dump_file)],
        env=pg_env(target_url),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=300,
        check=False,
    )
    assert restore.returncode == 0, restore.stderr.decode(errors="replace")

    expected = _row_counts(source_url)
    assert expected["applications"] == 3
    assert expected["watch_companies"] == 1
    assert expected["app_settings"] == 1
    assert _row_counts(target_url) == expected


def test_wrong_password_fails_cleanly_without_leaking_it(scratch_databases, tmp_path):
    source_url, _ = scratch_databases
    bad_url = make_url(source_url).set(password="definitely-wrong-pw").render_as_string(hide_password=False)
    with pytest.raises(BackupError) as excinfo:
        run_dump(bad_url, tmp_path, "manual", NOW)
    message = str(excinfo.value)
    assert message.startswith("pg_dump failed (exit 1): pg_dump: error:")
    assert "definitely-wrong-pw" not in message
    assert list((tmp_path / "manual").iterdir()) == []
