"""ops/server/deploy.sh against fake docker/curl and a real throwaway git
origin (Phase 3 spec §4.2, §6). See conftest.py for the fakes."""

import pytest

BACKUP = "docker compose run --rm -T db-backup python -m app.jobs.db_backup --once --label pre-deploy"
UP = "docker compose up -d --build --remove-orphans"
# The path the fake db-backup prints for every backup it takes.
DUMP = "/backups/pre-deploy/tracker-20261008T120000Z.dump"


def _deploy(server, fakes, *args, **env):
    return fakes.run([server.deploy, *args], cwd=fakes.home, **env)


def _refused(result, fakes, server, start_head, message):
    assert result.returncode == 1, result.stdout + result.stderr
    assert message in result.stderr
    assert "To fix:" in result.stderr
    assert server.head() == start_head
    assert not any(c.startswith("docker compose") for c in fakes.commands("docker"))


def _rollback_lines(result) -> list[str]:
    """The rollback advice at the end of the output, without the indent."""
    lines = result.stdout.rstrip("\n").split("\n")
    start = max(i for i, line in enumerate(lines) if line.startswith("    To "))
    return [line.removeprefix("    ") for line in lines[start:]]


def test_help_explains_usage(server, deploy_fakes):
    result = _deploy(server, deploy_fakes, "--help")
    assert result.returncode == 0
    assert "Usage: ops/server/deploy.sh [--skip-backup] [--restore DUMP [--yes]] [REF]" in result.stdout
    assert "DANGEROUS" in result.stdout
    assert "a rollback in one" in result.stdout
    assert deploy_fakes.calls() == []


def test_refuses_without_env_file(server, deploy_fakes):
    server.env_file.unlink()
    start = server.head()
    result = _deploy(server, deploy_fakes)
    _refused(result, deploy_fakes, server, start, ".env is missing")
    assert "cp .env.example .env" in result.stderr


def test_refuses_change_me_placeholders_and_names_only_the_keys(server, deploy_fakes):
    server.env_file.write_text(
        server.env_file.read_text()
        + "GOOGLE_CLIENT_SECRET=change-me\n# comment mentioning change-me is fine\nAPI=xx-change-me-yy\n"
    )
    start = server.head()
    result = _deploy(server, deploy_fakes)
    _refused(result, deploy_fakes, server, start, "change-me placeholders: GOOGLE_CLIENT_SECRET API\n")
    assert "xx-change-me-yy" not in result.stderr


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o660])
def test_refuses_env_readable_by_others(server, deploy_fakes, mode):
    server.env_file.chmod(mode)
    start = server.head()
    result = _deploy(server, deploy_fakes)
    _refused(result, deploy_fakes, server, start, f"(mode {mode:o})")
    assert "chmod 600 .env" in result.stderr


def test_accepts_a_read_only_env(server, deploy_fakes):
    server.env_file.chmod(0o400)
    assert _deploy(server, deploy_fakes).returncode == 0


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("DOMAIN=", "DOMAIN is not set"),
        ("DOMAIN=tracker.example.com", "still the example"),
        ("DOMAIN=https://tracker.test/", "not a plain host name"),
        ("DOMAIN=tracker.test # mine", "not a plain host name"),
    ],
)
def test_refuses_a_bad_domain(server, deploy_fakes, line, message):
    server.env_file.write_text(server.env_file.read_text().replace("DOMAIN=tracker.test", line))
    start = server.head()
    _refused(_deploy(server, deploy_fakes), deploy_fakes, server, start, message)


def test_domain_may_be_quoted_and_the_last_line_wins(server, deploy_fakes):
    server.env_file.write_text(server.env_file.read_text() + 'DOMAIN="quoted.test"\r\n')
    result = _deploy(server, deploy_fakes)
    assert result.returncode == 0, result.stderr
    assert "https://quoted.test/api/health" in deploy_fakes.calls("curl")[0]["args"]


def test_refuses_when_docker_is_unreachable(server, deploy_fakes):
    start = server.head()
    result = _deploy(server, deploy_fakes, FAKE_DOCKER_INFO_EXIT="1")
    _refused(result, deploy_fakes, server, start, "cannot talk to Docker")
    assert "log out and back in" in result.stderr


def test_refuses_local_changes_to_tracked_files(server, deploy_fakes):
    (server.path / "docker-compose.yml").write_text("edited on the server\n")
    start = server.head()
    result = _deploy(server, deploy_fakes)
    _refused(result, deploy_fakes, server, start, "were changed on the server")
    assert "docker-compose.yml" in result.stderr


def test_untracked_files_do_not_block(server, deploy_fakes):
    (server.path / "notes.txt").write_text("scratch\n")
    assert _deploy(server, deploy_fakes).returncode == 0


@pytest.mark.parametrize("ref", ["no-such-ref", "origin/nope", "c3^{tree}x"])
def test_refuses_an_unknown_ref_before_backing_up(server, deploy_fakes, ref):
    start = server.head()
    result = _deploy(server, deploy_fakes, ref, FAKE_RUNNING="db")
    assert result.returncode == 1
    assert f"'{ref}' is not a commit, tag or branch" in result.stderr
    assert server.head() == start
    assert BACKUP not in deploy_fakes.commands()
    assert UP not in deploy_fakes.commands()


def test_option_like_ref_is_refused(server, deploy_fakes):
    start = server.head()
    result = _deploy(server, deploy_fakes, "--upload-pack=evil")
    assert result.returncode == 1
    assert "unknown option: --upload-pack=evil" in result.stderr
    assert server.head() == start


def test_first_deploy_skips_the_backup_and_deploys_origin_main(server, deploy_fakes):
    result = _deploy(server, deploy_fakes, FAKE_RUNNING="", FAKE_VOLUMES="")
    assert result.returncode == 0, result.stderr
    assert "first deploy: no database yet, skipping backup" in result.stdout
    # The fetch found c3, pushed after the clone was made.
    assert server.head() == server.commits["c3"]
    commands = deploy_fakes.commands("docker")
    assert BACKUP not in commands
    assert UP in commands
    up = next(c for c in deploy_fakes.calls("docker") if " ".join(c["args"]).startswith("compose up"))
    assert up["compose"] == "# c3"  # built from the new checkout
    assert up["cwd"] == str(server.path)
    assert f"ops/server/deploy.sh {server.commits['c1']}" in result.stdout
    assert "--restore" not in result.stdout  # no pre-deploy backup to point at
    assert "This deploy took no pre-deploy backup (first deploy, or --skip-backup)" in result.stdout
    assert "now running:" in result.stdout and "commit c3" in result.stdout


def test_redeploy_backs_up_on_the_old_code_first(server, deploy_fakes):
    result = _deploy(server, deploy_fakes, FAKE_RUNNING="backend\ndb\ncaddy")
    assert result.returncode == 0, result.stderr
    calls = deploy_fakes.calls("docker")
    commands = [" ".join(["docker", *c["args"]]) for c in calls]
    backup = commands.index(BACKUP)
    up = commands.index(UP)
    assert backup < up
    assert calls[backup]["compose"] == "# c1"  # before the checkout
    assert calls[up]["compose"] == "# c3"
    # The backup's log is shown, and the one-command rollback names it.
    assert "pre-deploy backup written" in result.stderr
    assert _rollback_lines(result) == [
        "To undo this deploy (the previous code, and the database as it was just before this deploy):",
        f"  ops/server/deploy.sh --restore {DUMP} {server.commits['c1']}",
        "Anything changed in the app since this deploy is lost by that.",
        "Shortcut, ONLY if this deploy did not change the database (no migration; if unsure, use",
        "the command above): the previous code, keeping the data as it is now:",
        f"  ops/server/deploy.sh {server.commits['c1']}",
    ]
    assert "restore.sh" not in result.stdout


def test_stopped_database_with_data_is_started_and_backed_up(server, deploy_fakes):
    result = _deploy(server, deploy_fakes, FAKE_RUNNING="", FAKE_VOLUMES="server/pgdata")
    assert result.returncode == 0, result.stderr
    commands = deploy_fakes.commands("docker")
    assert commands.index("docker compose up -d --wait db") < commands.index(BACKUP)
    assert "first deploy" not in result.stdout
    assert (
        "docker volume ls --quiet --filter label=com.docker.compose.project=server "
        "--filter label=com.docker.compose.volume=pgdata"
    ) in commands


def test_another_projects_database_does_not_count(server, deploy_fakes):
    # A second stack on the same machine (say the smoke test's) has its own pgdata.
    result = _deploy(server, deploy_fakes, FAKE_RUNNING="", FAKE_VOLUMES="tracker-smoke/pgdata server/caddy_data")
    assert result.returncode == 0, result.stderr
    assert "first deploy: no database yet" in result.stdout
    assert BACKUP not in deploy_fakes.commands()


def test_the_project_follows_compose_project_name(server, deploy_fakes):
    result = _deploy(server, deploy_fakes, FAKE_RUNNING="", FAKE_VOLUMES="tracker-smoke/pgdata",
                     COMPOSE_PROJECT_NAME="tracker-smoke")  # fmt: skip
    assert result.returncode == 0, result.stderr
    assert BACKUP in deploy_fakes.commands()


def test_an_unreadable_compose_file_stops_before_anything_changes(server, deploy_fakes):
    start = server.head()
    result = _deploy(server, deploy_fakes, FAKE_RUNNING="", FAKE_CONFIG_EXIT="1")
    assert result.returncode == 1
    assert "could not read the Compose project name" in result.stderr
    assert server.head() == start
    assert UP not in deploy_fakes.commands()


def test_backup_failure_stops_the_deploy(server, deploy_fakes):
    start = server.head()
    result = _deploy(server, deploy_fakes, FAKE_RUNNING="db", FAKE_BACKUP_EXIT="1")
    assert result.returncode == 1
    assert "the pre-deploy backup failed, so nothing was deployed" in result.stderr
    assert server.head() == start
    assert UP not in deploy_fakes.commands()


def test_skip_backup_deploys_without_one(server, deploy_fakes):
    result = _deploy(server, deploy_fakes, "--skip-backup", FAKE_RUNNING="db")
    assert result.returncode == 0, result.stderr
    assert "WARNING: --skip-backup" in result.stderr
    assert BACKUP not in deploy_fakes.commands()
    assert server.head() == server.commits["c3"]
    assert "This deploy took no pre-deploy backup (first deploy, or --skip-backup)" in result.stdout


@pytest.mark.parametrize("ref", ["v1", "c1-short", "c2-full"])
def test_deploys_the_given_ref(server, deploy_fakes, ref):
    git_ref = {"v1": "v1", "c1-short": server.commits["c1"][:9], "c2-full": server.commits["c2"]}[ref]
    expected = server.commits["c2"] if ref == "c2-full" else server.commits["c1"]
    result = _deploy(server, deploy_fakes, git_ref)
    assert result.returncode == 0, result.stderr
    assert server.head() == expected
    assert UP in deploy_fakes.commands()


def test_a_local_branch_gets_a_warning(server, deploy_fakes):
    result = _deploy(server, deploy_fakes, "main")
    assert result.returncode == 0, result.stderr
    assert "'main' is a local branch" in result.stderr
    assert server.head() == server.commits["c2"]  # the clone's main, not origin's c3


def test_health_check_targets_this_server(server, deploy_fakes):
    result = _deploy(server, deploy_fakes)
    assert result.returncode == 0
    args = deploy_fakes.calls("curl")[0]["args"]
    assert args[-1] == "https://tracker.test/api/health"
    assert args[args.index("--resolve") + 1] == "tracker.test:443:127.0.0.1"
    assert "--fail" in args
    assert "--insecure" not in args


def test_localhost_accepts_caddys_internal_certificate(server, deploy_fakes):
    server.env_file.write_text(server.env_file.read_text().replace("DOMAIN=tracker.test", "DOMAIN=localhost"))
    result = _deploy(server, deploy_fakes)
    assert result.returncode == 0, result.stderr
    args = deploy_fakes.calls("curl")[0]["args"]
    assert "--insecure" in args
    assert args[args.index("--resolve") + 1] == "localhost:443:127.0.0.1"


def test_health_retries_until_healthy(server, deploy_fakes):
    result = _deploy(server, deploy_fakes, FAKE_CURL_FAILS="2")
    assert result.returncode == 0, result.stderr
    assert len(deploy_fakes.calls("curl")) == 3
    assert "healthy" in result.stdout


def test_health_timeout_fails_with_hints(server, deploy_fakes):
    result = _deploy(server, deploy_fakes, FAKE_CURL_FAILS="always", TRACKER_HEALTH_TIMEOUT="1",
                     TRACKER_HEALTH_INTERVAL="0.2")  # fmt: skip
    assert result.returncode == 1
    assert "https://tracker.test/api/health did not answer within 1s" in result.stderr
    assert "Last error: curl: (7) Failed to connect" in result.stderr
    assert "docker compose logs backend --tail 50" in result.stderr
    assert "dig +short tracker.test" in result.stderr
    assert "docker compose ps" in deploy_fakes.commands("docker")
    assert deploy_fakes.calls("curl")  # (retries: test_health_retries_until_healthy)
    # The new code stays checked out; the way back is printed.
    assert server.head() == server.commits["c3"]
    assert f"ops/server/deploy.sh {server.commits['c1']}" in result.stdout


def test_compose_up_failure_prints_the_rollback(server, deploy_fakes):
    result = _deploy(server, deploy_fakes, FAKE_UP_EXIT="1")
    assert result.returncode == 1
    assert "docker compose up failed" in result.stderr
    assert f"ops/server/deploy.sh {server.commits['c1']}" in result.stdout
    assert deploy_fakes.calls("curl") == []


def test_rollback_deploys_the_previous_commit(server, deploy_fakes):
    assert _deploy(server, deploy_fakes).returncode == 0
    assert server.head() == server.commits["c3"]
    result = _deploy(server, deploy_fakes, server.commits["c1"])
    assert result.returncode == 0, result.stderr
    assert server.head() == server.commits["c1"]
    assert f"ops/server/deploy.sh {server.commits['c3']}" in result.stdout


@pytest.mark.parametrize("contact", ["you@example.com", "Me@Example.COM"])
def test_refuses_the_example_contact_email(server, deploy_fakes, contact):
    server.env_file.write_text(server.env_file.read_text().replace("CONTACT_EMAIL=", f"CONTACT_EMAIL={contact}"))
    start = server.head()
    result = _deploy(server, deploy_fakes)
    _refused(result, deploy_fakes, server, start, f"CONTACT_EMAIL in .env is still an example address ({contact})")
    assert "or leave it empty" in result.stderr


@pytest.mark.parametrize("line", ["CONTACT_EMAIL=", "CONTACT_EMAIL=me@mydomain.test", "CONTACT_EMAIL=me@example.com.au"])
def test_accepts_a_blank_or_real_contact_email(server, deploy_fakes, line):
    server.env_file.write_text(server.env_file.read_text().replace("CONTACT_EMAIL=", line))
    assert _deploy(server, deploy_fakes).returncode == 0


# --- deploy.sh --restore DUMP [REF]: a rollback in one command -----------------------------

OLD_DUMP = "backups/pre-deploy/tracker-20261007T120000Z.dump"
OLD_DUMP_IN_CONTAINER = "/backups/pre-deploy/tracker-20261007T120000Z.dump"
SERVICES = "backend sheet-sync job-scan db-backup caddy"
CHECK = f"docker compose run --rm -T db-backup python -m app.cli restore {OLD_DUMP_IN_CONTAINER} --check"
RESTORE = f"docker compose run --rm -T db-backup python -m app.cli restore {OLD_DUMP_IN_CONTAINER} --yes"
BUILD = "docker compose build"
STOP = f"docker compose stop {SERVICES}"
RUNNING = "backend\ndb\ncaddy"


def _rollback(server, fakes, *extra, input="", **env):
    env.setdefault("FAKE_RUNNING", RUNNING)
    return fakes.run([server.deploy, "--restore", OLD_DUMP, *extra, server.commits["c2"]], cwd=server.path,
                     input=input, **env)  # fmt: skip


def _compose_steps(fakes) -> list[tuple[str, str]]:
    """(command, checkout it ran in) for each docker compose command that changes something."""
    return [
        (" ".join(["docker", *c["args"]]), c["compose"])
        for c in fakes.calls("docker")
        if c["args"][:2] != ["compose", "ps"] and c["args"][:2] != ["compose", "config"] and c["args"][0] == "compose"
    ]


def test_restore_backs_up_checks_out_stops_restores_starts_and_checks_health(server, deploy_fakes):
    result = _rollback(server, deploy_fakes, "--yes")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _compose_steps(deploy_fakes) == [
        (CHECK, "# c1"),  # the dump is checked before anything changes
        (BACKUP, "# c1"),  # the pre-deploy backup runs on the code being replaced
        (BUILD, "# c2"),  # then the checkout; built while the app still runs
        (STOP, "# c2"),
        (RESTORE, "# c2"),
        (UP, "# c2"),
    ]
    assert len(deploy_fakes.calls("curl")) == 1  # health checked last
    assert server.head() == server.commits["c2"]
    assert f"the database now holds the data from {OLD_DUMP}" in result.stdout
    assert "--yes: not asking for confirmation" in result.stdout
    # This deploy's own undo: its pre-deploy backup and the commit it replaced.
    assert f"  ops/server/deploy.sh --restore {DUMP} {server.commits['c1']}" in _rollback_lines(result)


def test_restore_asks_for_the_database_name_first(server, deploy_fakes):
    result = _rollback(server, deploy_fakes, input="internship_tracker\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'This REPLACES ALL DATA in the database "internship_tracker" with:' in result.stdout
    assert f"  {OLD_DUMP}\n" in result.stdout
    assert RESTORE in deploy_fakes.commands()


@pytest.mark.parametrize("answer", ["", "yes", "internship_tracker extra"])
def test_restore_not_confirmed_changes_nothing(server, deploy_fakes, answer):
    start = server.head()
    result = _rollback(server, deploy_fakes, input=answer + "\n")
    assert result.returncode == 1
    assert "not confirmed; nothing was changed" in result.stderr
    assert server.head() == start
    assert [step for step, _ in _compose_steps(deploy_fakes)] == [CHECK]


def test_restore_of_a_missing_dump_changes_nothing(server, deploy_fakes):
    # The server's own dumps are root's, so the container checks them.
    start = server.head()
    result = _rollback(server, deploy_fakes, "--yes", FAKE_CHECK_EXIT="1")
    assert result.returncode == 1
    assert f"{OLD_DUMP} can't be restored (see the error above); nothing was changed" in result.stderr
    assert server.head() == start
    assert [step for step, _ in _compose_steps(deploy_fakes)] == [CHECK]


def test_restore_of_a_missing_outside_file_is_refused_before_anything_runs(server, deploy_fakes, tmp_path):
    start = server.head()
    result = deploy_fakes.run([server.deploy, "--restore", tmp_path / "nope.dump.enc", "--yes"], cwd=server.path)
    assert result.returncode == 1
    assert f"cannot read {tmp_path / 'nope.dump.enc'}" in result.stderr
    assert server.head() == start
    assert deploy_fakes.calls() == []


def test_restore_mounts_an_outside_file_read_only(server, deploy_fakes, tmp_path):
    enc = tmp_path / "tracker-20261007T073000Z.dump.enc"
    enc.write_bytes(b"gAAAA-ciphertext")
    result = deploy_fakes.run([server.deploy, "--yes", "--restore", enc.name], cwd=tmp_path, FAKE_RUNNING=RUNNING)
    assert result.returncode == 0, result.stdout + result.stderr
    restore = next(c for c in deploy_fakes.calls("docker") if "--yes" in c["args"])
    assert restore["args"][restore["args"].index("-v") + 1] == f"{enc}:/restore/backup.dump.enc:ro"
    assert server.head() == server.commits["c3"]  # REF defaults to origin/main


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--restore"], "--restore needs the backup to restore"),
        (["--restore", ""], "--restore needs the backup to restore"),
        (["--yes"], "--yes only goes with --restore"),
        (["--restore", "backup.sql"], "must end in .dump or .dump.enc"),
    ],
)
def test_restore_usage_errors(server, deploy_fakes, args, message):
    result = deploy_fakes.run([server.deploy, *args], cwd=server.path)
    assert result.returncode == 1
    assert message in result.stderr
    assert deploy_fakes.calls() == []


def test_restore_needs_a_database(server, deploy_fakes):
    start = server.head()
    result = _rollback(server, deploy_fakes, "--yes", FAKE_RUNNING="", FAKE_VOLUMES="")
    assert result.returncode == 1
    assert "there is no database here yet to restore into; nothing was changed" in result.stderr
    assert f"ops/server/restore.sh {OLD_DUMP}" in result.stderr
    assert server.head() == start
    assert _compose_steps(deploy_fakes) == []


def test_restore_failure_restarts_the_old_app_and_says_the_data_is_unchanged(server, deploy_fakes):
    result = _rollback(server, deploy_fakes, "--yes", FAKE_RESTORE_EXIT="1")
    assert result.returncode == 1
    assert "the restore failed (see the error above); the database was not changed" in result.stderr
    steps = [step for step, _ in _compose_steps(deploy_fakes)]
    assert steps[-2:] == [RESTORE, f"docker compose start {SERVICES}"]
    assert UP not in steps
    assert deploy_fakes.calls("curl") == []
    assert server.head() == server.commits["c2"]
    assert f"To put the code back:\n      ops/server/deploy.sh {server.commits['c1']}\n" in result.stdout
    assert "--restore" not in result.stdout


def test_build_failure_stops_before_the_app_or_the_data(server, deploy_fakes):
    result = _rollback(server, deploy_fakes, "--yes", FAKE_BUILD_EXIT="1")
    assert result.returncode == 1
    assert "docker compose build failed (see the error above); the database was not changed" in result.stderr
    steps = [step for step, _ in _compose_steps(deploy_fakes)]
    assert steps[-1] == BUILD
    assert STOP not in steps
    assert f"ops/server/deploy.sh {server.commits['c1']}" in result.stdout


def test_stop_failure_leaves_the_data_alone(server, deploy_fakes):
    result = _rollback(server, deploy_fakes, "--yes", FAKE_STOP_EXIT="1")
    assert result.returncode == 1
    assert "docker compose stop failed" in result.stderr
    assert RESTORE not in deploy_fakes.commands()


@pytest.mark.parametrize("failure", [{"FAKE_UP_EXIT": "1"}, {"FAKE_CURL_FAILS": "always", "TRACKER_HEALTH_TIMEOUT": "0"}])
def test_restore_then_start_failure_prints_the_undo(server, deploy_fakes, failure):
    result = _rollback(server, deploy_fakes, "--yes", **failure)
    assert result.returncode == 1
    assert RESTORE in deploy_fakes.commands()
    # The data is replaced now: the way back is this deploy's pre-deploy backup.
    assert f"  ops/server/deploy.sh --restore {DUMP} {server.commits['c1']}" in _rollback_lines(result)


def test_restore_with_skip_backup_says_there_is_no_undo_for_the_data(server, deploy_fakes):
    result = _rollback(server, deploy_fakes, "--yes", "--skip-backup")
    assert result.returncode == 0, result.stdout + result.stderr
    assert BACKUP not in deploy_fakes.commands()
    assert RESTORE in deploy_fakes.commands()
    assert "This deploy took no pre-deploy backup (first deploy, or --skip-backup)" in result.stdout
    assert "--restore" not in result.stdout.split("Deployed")[1]


def test_restore_starts_a_stopped_database_for_the_backup(server, deploy_fakes):
    result = _rollback(server, deploy_fakes, "--yes", FAKE_RUNNING="", FAKE_VOLUMES="server/pgdata")
    assert result.returncode == 0, result.stdout + result.stderr
    steps = [step for step, _ in _compose_steps(deploy_fakes)]
    assert steps.index("docker compose up -d --wait db") < steps.index(BACKUP) < steps.index(RESTORE)
