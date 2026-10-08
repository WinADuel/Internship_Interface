"""ops/checks/stack-smoke.sh (Phase 3 Task 9) guards the checkout it runs in:
it never replaces a real .env or deletes real backups, and it always cleans
up. The script runs from a copy of the repo's ops/ folder with a fake docker
(logs its argv, answers 0) and a fake deploy.sh that fails, so nothing here
builds or starts the real stack; CI's stack-smoke job does that."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from tests.ops.conftest import REPO_ROOT, SCRIPTS, is_executable

SCRIPT = REPO_ROOT / "ops" / "checks" / "stack-smoke.sh"
MY_ENV = "DOMAIN=tracker.mine.test\nJWT_SECRET=my-real-secret\n"

FAKE_DOCKER = """#!{python}
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({{"args": sys.argv[1:], "project": os.environ.get("COMPOSE_PROJECT_NAME")}}) + "\\n")
"""

# Stands in for ops/server/deploy.sh: records the .env it was given, then fails.
FAKE_DEPLOY = """#!/bin/sh
cp .env "$FAKE_SEEN/env"
stat -c '%a' .env > "$FAKE_SEEN/mode"
echo "$*" > "$FAKE_SEEN/args"
exit 3
"""

FAKE_GIT = """#!/bin/sh
echo 0123456789abcdef0123456789abcdef01234567
"""


class Checkout:
    def __init__(self, root: Path):
        self.path = root / "repo"
        checks = self.path / "ops" / "checks"
        server = self.path / "ops" / "server"
        checks.mkdir(parents=True)
        server.mkdir(parents=True)
        shutil.copy2(SCRIPT, checks / "stack-smoke.sh")
        shutil.copy2(SCRIPTS / "lib.sh", server / "lib.sh")
        self._write(server / "deploy.sh", FAKE_DEPLOY)
        self.bin = root / "fakebin"
        self.bin.mkdir()
        self._write(self.bin / "docker", FAKE_DOCKER.format(python=sys.executable))
        self._write(self.bin / "git", FAKE_GIT)
        self.seen = root / "seen"
        self.seen.mkdir()
        self.log = root / "docker.log"
        self.env_file = self.path / ".env"

    @staticmethod
    def _write(path: Path, text: str) -> None:
        path.write_text(text)
        path.chmod(0o755)

    def run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["/bin/bash", str(self.path / "ops" / "checks" / "stack-smoke.sh"), *args],
            cwd=self.path.parent,
            env={
                "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                "LANG": "C.UTF-8",
                "FAKE_LOG": str(self.log),
                "FAKE_SEEN": str(self.seen),
            },
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def docker_calls(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def docker_commands(self) -> list[str]:
        return [" ".join(call["args"]) for call in self.docker_calls()]


@pytest.fixture()
def checkout(tmp_path) -> Checkout:
    if shutil.which("openssl") is None:
        pytest.skip("openssl not installed")
    return Checkout(tmp_path)


def test_script_is_executable():
    assert is_executable(SCRIPT)
    assert SCRIPT.read_text().startswith("#!/usr/bin/env bash\n")


def test_help_explains_usage(checkout):
    result = checkout.run("--help")
    assert result.returncode == 0
    assert "Usage: ops/checks/stack-smoke.sh [--force-env]" in result.stdout
    assert checkout.docker_calls() == []


def test_refuses_to_replace_an_existing_env(checkout):
    checkout.env_file.write_text(MY_ENV)
    result = checkout.run()
    assert result.returncode == 1
    assert ".env exists" in result.stderr
    assert "--force-env" in result.stderr
    assert checkout.env_file.read_text() == MY_ENV
    assert checkout.docker_calls() == []
    assert not (checkout.seen / "env").exists()


def test_refuses_when_backups_exist(checkout):
    backups = checkout.path / "backups" / "nightly"
    backups.mkdir(parents=True)
    (backups / "tracker-20261008T023000Z.dump").write_text("dump")
    result = checkout.run()
    assert result.returncode == 1
    assert "backups exists" in result.stderr
    assert (backups / "tracker-20261008T023000Z.dump").exists()
    assert not checkout.env_file.exists()
    assert checkout.docker_calls() == []


def test_refuses_after_an_interrupted_run_left_env_aside(checkout):
    checkout.env_file.write_text("THROWAWAY=1\n")
    saved = checkout.path / ".env.before-smoke"
    saved.write_text(MY_ENV)
    result = checkout.run("--force-env")
    assert result.returncode == 1
    assert ".env.before-smoke exists" in result.stderr
    assert saved.read_text() == MY_ENV
    assert checkout.env_file.read_text() == "THROWAWAY=1\n"
    assert checkout.docker_calls() == []


def test_unknown_argument_is_refused(checkout):
    result = checkout.run("--nope")
    assert result.returncode == 1
    assert "unknown argument: --nope" in result.stderr
    assert checkout.docker_calls() == []


def test_writes_a_private_throwaway_env_and_removes_it(checkout):
    result = checkout.run()
    assert result.returncode == 3, result.stdout + result.stderr
    assert (checkout.seen / "mode").read_text().strip() == "600"
    assert (checkout.seen / "args").read_text().strip() == "0123456789abcdef0123456789abcdef01234567"
    env = dict(
        line.split("=", 1)
        for line in (checkout.seen / "env").read_text().splitlines()
        if line and not line.startswith("#")
    )
    assert env["DOMAIN"] == "localhost"
    assert env["CONTACT_EMAIL"] == "smoke@example.com"
    assert env["COOKIE_SECURE"] == "true"
    assert "change-me" not in (checkout.seen / "env").read_text()
    assert len(env["JWT_SECRET"]) >= 32
    Fernet(env["TOKEN_ENCRYPTION_KEY"])
    Fernet(env["BACKUP_ENCRYPTION_KEY"])
    assert env["TOKEN_ENCRYPTION_KEY"] != env["BACKUP_ENCRYPTION_KEY"]
    assert f":{env['POSTGRES_PASSWORD']}@db:5432/{env['POSTGRES_DB']}" in env["DATABASE_URL"]
    # The failure dumped the logs, then everything was taken down and the .env removed.
    commands = checkout.docker_commands()
    assert "compose logs --no-color --tail 80" in commands
    assert commands[-1] == "compose down --volumes --remove-orphans"
    assert {call["project"] for call in checkout.docker_calls()} == {"tracker-smoke"}
    assert not checkout.env_file.exists()
    assert "FAILED" in result.stderr


def test_force_env_puts_your_env_back_even_when_the_test_fails(checkout):
    checkout.env_file.write_text(MY_ENV)
    checkout.env_file.chmod(0o600)
    result = checkout.run("--force-env")
    assert result.returncode == 3, result.stdout + result.stderr
    assert "DOMAIN=localhost" in (checkout.seen / "env").read_text()
    assert checkout.env_file.read_text() == MY_ENV
    assert not (checkout.path / ".env.before-smoke").exists()
    assert "compose down --volumes --remove-orphans" in checkout.docker_commands()
