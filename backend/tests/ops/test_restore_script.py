"""ops/server/restore.sh against fake docker/curl (Phase 3 spec §4.4, §6).
See conftest.py for the fakes."""

import pytest

SERVICES = "backend sheet-sync job-scan db-backup caddy"
SAFETY = "docker compose run --rm -T db-backup python -m app.jobs.db_backup --once --label manual"


def _restore(server, fakes, *args, input="", cwd=None, **env):
    return fakes.run([server.restore, *args], cwd=cwd or server.path, input=input, **env)


def _cli(path, flag):
    return f"python -m app.cli restore {path} {flag}"


def _ran(fakes, text):
    return [c for c in fakes.commands("docker") if text in c]


def test_help_explains_usage(server, deploy_fakes):
    result = _restore(server, deploy_fakes, "--help")
    assert result.returncode == 0
    assert "Usage: ops/server/restore.sh [--yes] [--no-safety-backup] FILE" in result.stdout
    assert deploy_fakes.calls() == []


def test_confirmed_restore_runs_every_step_in_order(server, deploy_fakes):
    dump = "backups/nightly/tracker-20261007T073000Z.dump"
    result = _restore(server, deploy_fakes, dump, input="internship_tracker\n")
    assert result.returncode == 0, result.stderr
    container = "/backups/nightly/tracker-20261007T073000Z.dump"
    assert deploy_fakes.commands("docker") == [
        "docker info",
        f"docker compose run --rm -T db-backup {_cli(container, '--check')}",
        SAFETY,
        f"docker compose stop {SERVICES}",
        f"docker compose run --rm -T db-backup {_cli(container, '--yes')}",
        "docker compose up -d",
    ]
    assert 'REPLACES ALL DATA in the database "internship_tracker"' in result.stdout
    assert "Type the database name (internship_tracker) to continue:" in result.stdout
    assert len(deploy_fakes.calls("curl")) == 1
    assert "ops/server/restore.sh /backups/manual/tracker-20261008T120000Z.dump" in result.stdout


@pytest.mark.parametrize("answer", ["", "yes", "Internship_Tracker", "internship_tracker extra"])
def test_wrong_confirmation_changes_nothing(server, deploy_fakes, answer):
    result = _restore(server, deploy_fakes, "backups/manual/tracker-20261007T073000Z.dump", input=answer + "\n")
    assert result.returncode == 1
    assert "not confirmed; nothing was changed" in result.stderr
    assert [c for c in deploy_fakes.commands("docker") if "--check" not in c] == ["docker info"]


def test_no_input_at_all_changes_nothing(server, deploy_fakes):
    result = _restore(server, deploy_fakes, "backups/manual/tracker-20261007T073000Z.dump", input="")
    assert result.returncode == 1
    assert _ran(deploy_fakes, "--yes") == []


def test_yes_skips_the_question(server, deploy_fakes):
    result = _restore(server, deploy_fakes, "--yes", "backups/manual/tracker-20261007T073000Z.dump")
    assert result.returncode == 0, result.stderr
    assert "Type the database name" not in result.stdout
    assert len(_ran(deploy_fakes, "--yes")) == 1


@pytest.mark.parametrize(
    ("arg", "cwd", "container"),
    [
        ("backups/pre-deploy/tracker-20261008T120000Z.dump", "repo", "/backups/pre-deploy/tracker-20261008T120000Z.dump"),
        ("/backups/pre-deploy/tracker-20261008T120000Z.dump", "home", "/backups/pre-deploy/tracker-20261008T120000Z.dump"),
        ("server/backups/manual/tracker-20261008T120000Z.dump", "tmp", "/backups/manual/tracker-20261008T120000Z.dump"),
    ],
)  # fmt: skip
def test_server_dumps_are_read_where_they_are(server, deploy_fakes, arg, cwd, container):
    # Host files under ./backups belong to root (mode 0600), so the script never
    # reads them itself: the db-backup container sees them at /backups.
    workdir = {"repo": server.path, "home": deploy_fakes.home, "tmp": server.path.parent}[cwd]
    result = _restore(server, deploy_fakes, "--yes", arg, cwd=workdir)
    assert result.returncode == 0, result.stderr
    restore = _ran(deploy_fakes, "--yes")[0]
    assert restore == f"docker compose run --rm -T db-backup {_cli(container, '--yes')}"
    assert all(c["cwd"] == str(server.path) for c in deploy_fakes.calls("docker"))


def test_an_encrypted_drive_copy_is_mounted_read_only(server, deploy_fakes, tmp_path):
    downloads = tmp_path / "Downloads dir"
    downloads.mkdir()
    enc = downloads / "tracker-20261007T073000Z.dump.enc"
    enc.write_bytes(b"gAAAA-ciphertext")
    result = _restore(server, deploy_fakes, "--yes", "tracker-20261007T073000Z.dump.enc", cwd=downloads)
    assert result.returncode == 0, result.stderr
    mount = f"-v {enc}:/restore/backup.dump.enc:ro"
    assert _ran(deploy_fakes, "--check") == [
        f"docker compose run --rm -T {mount} db-backup {_cli('/restore/backup.dump.enc', '--check')}"
    ]
    assert _ran(deploy_fakes, "--yes") == [
        f"docker compose run --rm -T {mount} db-backup {_cli('/restore/backup.dump.enc', '--yes')}"
    ]
    # The mount is one argument, even with a space in the path.
    restore = next(c for c in deploy_fakes.calls("docker") if "--yes" in c["args"])
    assert restore["args"][restore["args"].index("-v") + 1] == f"{enc}:/restore/backup.dump.enc:ro"


def test_a_plain_dump_from_elsewhere_is_mounted_too(server, deploy_fakes, tmp_path):
    dump = tmp_path / "copy.dump"
    dump.write_bytes(b"PGDMP")
    result = _restore(server, deploy_fakes, "--yes", dump)
    assert result.returncode == 0, result.stderr
    assert _ran(deploy_fakes, "--yes") == [
        f"docker compose run --rm -T -v {dump}:/restore/backup.dump:ro db-backup {_cli('/restore/backup.dump', '--yes')}"
    ]


def test_a_missing_outside_file_is_refused(server, deploy_fakes, tmp_path):
    result = _restore(server, deploy_fakes, "--yes", tmp_path / "nope.dump.enc")
    assert result.returncode == 1
    assert "cannot read" in result.stderr
    assert deploy_fakes.calls() == []


def test_a_path_docker_cannot_mount_is_refused(server, deploy_fakes, tmp_path):
    odd = tmp_path / "a:b.dump"
    odd.write_bytes(b"PGDMP")
    result = _restore(server, deploy_fakes, "--yes", odd)
    assert result.returncode == 1
    assert "can't mount a path with ':'" in result.stderr
    assert deploy_fakes.calls() == []


@pytest.mark.parametrize("name", ["backup.sql", "tracker.dump.gz", ".env"])
def test_other_file_types_are_refused(server, deploy_fakes, tmp_path, name):
    (tmp_path / name).write_text("x")
    result = _restore(server, deploy_fakes, "--yes", tmp_path / name)
    assert result.returncode == 1
    assert "must end in .dump or .dump.enc" in result.stderr
    assert deploy_fakes.calls() == []


def test_an_unreadable_backup_stops_before_anything_changes(server, deploy_fakes):
    result = _restore(server, deploy_fakes, "--yes", "backups/manual/x.dump", FAKE_CHECK_EXIT="1")
    assert result.returncode == 1
    assert "can't be restored" in result.stderr
    assert deploy_fakes.commands("docker")[-1].endswith("--check")
    assert SAFETY not in deploy_fakes.commands()


def test_safety_backup_failure_stops_before_anything_changes(server, deploy_fakes):
    result = _restore(server, deploy_fakes, "--yes", "backups/manual/x.dump", FAKE_BACKUP_EXIT="1")
    assert result.returncode == 1
    assert "the safety backup failed; nothing was changed" in result.stderr
    assert "--no-safety-backup" in result.stderr
    assert deploy_fakes.commands("docker")[-1] == SAFETY


def test_no_safety_backup_skips_it(server, deploy_fakes):
    result = _restore(server, deploy_fakes, "--yes", "--no-safety-backup", "backups/manual/x.dump")
    assert result.returncode == 0, result.stderr
    assert SAFETY not in deploy_fakes.commands()
    assert "WARNING: --no-safety-backup" in result.stderr
    assert "to undo" not in result.stdout


def test_failed_restore_starts_the_app_again(server, deploy_fakes):
    result = _restore(server, deploy_fakes, "--yes", "backups/manual/x.dump", FAKE_RESTORE_EXIT="1")
    assert result.returncode == 1
    assert "the restore failed (see the error above); the database was not changed" in result.stderr
    assert deploy_fakes.commands("docker")[-1] == "docker compose up -d"
    assert deploy_fakes.calls("curl") == []


def test_health_timeout_after_restore_fails(server, deploy_fakes):
    result = _restore(server, deploy_fakes, "--yes", "backups/manual/x.dump", FAKE_CURL_FAILS="always",
                      TRACKER_HEALTH_TIMEOUT="0")  # fmt: skip
    assert result.returncode == 1
    assert "did not answer within 0s" in result.stderr


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda env: env.unlink(), ".env is missing"),
        (lambda env: env.chmod(0o644), "chmod 600 .env"),
        (lambda env: env.write_text(env.read_text() + "JWT_SECRET=change-me\n"), "change-me placeholders: JWT_SECRET"),
        (lambda env: env.write_text(env.read_text().replace("POSTGRES_DB=internship_tracker", "")), "POSTGRES_DB is not set"),
    ],
)  # fmt: skip
def test_env_problems_are_refused(server, deploy_fakes, change, message):
    change(server.env_file)
    result = _restore(server, deploy_fakes, "--yes", "backups/manual/x.dump")
    assert result.returncode == 1
    assert message in result.stderr
    assert not any(c.startswith("docker compose") for c in deploy_fakes.commands("docker"))


def test_needs_a_file(server, deploy_fakes):
    result = _restore(server, deploy_fakes, "--yes")
    assert result.returncode == 1
    assert "which backup?" in result.stderr
