"""ops/checks/check-caddyfile.sh picks Caddy from CADDY_BIN or Docker, and
skips without either, except under CI, where a skip would hide a broken
Caddyfile (Phase 3 Task 8). Driven with fake docker/caddy programs on a PATH
that holds nothing else, so the real Docker is never run."""

import os
import subprocess
from pathlib import Path

import pytest

from tests.ops.conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "ops" / "checks" / "check-caddyfile.sh"

FAKE = """#!/bin/sh
printf '%s|DOMAIN=%s\\n' "$*" "$DOMAIN" >> "{log}"
exit {code}
"""


@pytest.fixture()
def bin_dir(tmp_path) -> Path:
    path = tmp_path / "bin"
    path.mkdir()
    # The script needs dirname; nothing else from PATH (bash is run directly).
    (path / "dirname").symlink_to(_which("dirname"))
    return path


def _which(name: str) -> str:
    for folder in ("/usr/bin", "/bin"):
        candidate = Path(folder) / name
        if candidate.exists():
            return str(candidate)
    pytest.skip(f"{name} not found")


def _fake(bin_dir: Path, name: str, log: Path, code: int = 0) -> Path:
    path = bin_dir / name
    path.write_text(FAKE.format(log=log, code=code))
    path.chmod(0o755)
    return path


def _run(bin_dir: Path, **env) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["/bin/bash", str(SCRIPT)],
        env={"PATH": str(bin_dir), "LANG": "C.UTF-8", **env},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_skips_without_docker_or_caddy_bin_outside_ci(bin_dir):
    result = _run(bin_dir)
    assert result.returncode == 0
    assert "skipped" in result.stderr


@pytest.mark.parametrize("ci", ["true", "1"])
def test_fails_without_docker_or_caddy_bin_in_ci(bin_dir, ci):
    result = _run(bin_dir, CI=ci)
    assert result.returncode != 0
    assert "skipped" not in result.stderr
    assert "CI" in result.stderr
    assert "valid" not in result.stdout


def test_uses_docker_with_the_caddy_image(bin_dir, tmp_path):
    log = tmp_path / "calls.log"
    _fake(bin_dir, "docker", log)
    result = _run(bin_dir, CI="true")
    assert result.returncode == 0, result.stderr
    args = log.read_text().strip()
    assert args.startswith("run --rm -e DOMAIN=localhost -v ")
    assert f"{REPO_ROOT / 'Caddyfile'}:/etc/caddy/Caddyfile:ro caddy:2 caddy validate" in args
    assert "Caddyfile is valid" in result.stdout


def test_docker_validation_failure_fails(bin_dir, tmp_path):
    _fake(bin_dir, "docker", tmp_path / "calls.log", code=1)
    result = _run(bin_dir, CI="true")
    assert result.returncode != 0
    assert "valid" not in result.stdout


def test_caddy_bin_wins_over_docker(bin_dir, tmp_path):
    docker_log = tmp_path / "docker.log"
    caddy_log = tmp_path / "caddy.log"
    _fake(bin_dir, "docker", docker_log)
    caddy = _fake(tmp_path, "caddy", caddy_log)
    result = _run(bin_dir, CADDY_BIN=str(caddy))
    assert result.returncode == 0, result.stderr
    assert not docker_log.exists()
    assert caddy_log.read_text().strip() == (
        f"validate --config {REPO_ROOT / 'Caddyfile'} --adapter caddyfile|DOMAIN=localhost"
    )


def test_script_is_executable():
    assert os.access(SCRIPT, os.X_OK)
