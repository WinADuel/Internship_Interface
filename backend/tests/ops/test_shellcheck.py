"""Every shell script in ops/ passes ShellCheck (Phase 3 plan: no warnings).
Settings come from the repo-root .shellcheckrc (follow `source` lines).
Skipped locally without shellcheck; a failure in CI."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.ops.conftest import REPO_ROOT, SCRIPTS, is_executable

SHELL_SCRIPTS = sorted((REPO_ROOT / "ops").rglob("*.sh"))


def _shellcheck() -> str:
    # The venv's shellcheck-py puts it next to the Python running the tests.
    found = shutil.which("shellcheck") or shutil.which("shellcheck", path=str(Path(sys.executable).parent))
    if found is None:
        if os.environ.get("CI"):
            pytest.fail("shellcheck not on PATH")
        pytest.skip("shellcheck not on PATH")
    return found


def test_finds_the_scripts():
    names = {path.relative_to(REPO_ROOT).as_posix() for path in SHELL_SCRIPTS}
    assert {"ops/server/bootstrap.sh", "ops/server/deploy.sh", "ops/server/restore.sh", "ops/server/lib.sh"} <= names


def test_shellcheck_is_clean():
    result = subprocess.run(
        [_shellcheck(), *map(str, SHELL_SCRIPTS)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_server_scripts_are_executable():
    for name in ("bootstrap.sh", "deploy.sh", "restore.sh"):
        assert is_executable(SCRIPTS / name), name
        assert (SCRIPTS / name).read_text().startswith("#!/usr/bin/env bash\n"), name
