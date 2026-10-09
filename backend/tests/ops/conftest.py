"""Fakes for driving the ops/server scripts (Phase 3 spec §6).

Each fake command is the same small Python program under a different name,
first on PATH. It appends {"cmd", "args", "cwd", ...} as one JSON line to the
file in FAKE_LOG and answers from FAKE_* environment variables. Nothing here
touches Docker, the network or the system: git is real, on throwaway repos."""

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "ops" / "server"

FAKE_PROGRAM = """#!{python}
import json, os, sys
from pathlib import Path

name = Path(sys.argv[0]).name
args = sys.argv[1:]
entry = {{"cmd": name, "args": args, "cwd": os.getcwd()}}
if name == "docker" and Path("docker-compose.yml").is_file():
    # Which checkout the command ran in (each test commit writes a different file).
    entry["compose"] = Path("docker-compose.yml").read_text().strip()
log_path = os.environ["FAKE_LOG"]
with open(log_path, "a") as log:
    log.write(json.dumps(entry) + "\\n")


def code(var):
    return int(os.environ.get(var, "0"))


if name == "docker":
    if args[:1] == ["info"]:
        sys.exit(code("FAKE_DOCKER_INFO_EXIT"))
    if args[:1] == ["volume"]:
        # FAKE_VOLUMES: one "project/volume" per line; prints the names that
        # match every --filter label=KEY=VALUE, as docker does.
        wanted = {{}}
        for i, arg in enumerate(args):
            if arg == "--filter":
                key, _, value = args[i + 1].removeprefix("label=").partition("=")
                wanted[key] = value
        for line in os.environ.get("FAKE_VOLUMES", "").split():
            project, volume = line.split("/")
            labels = {{"com.docker.compose.project": project, "com.docker.compose.volume": volume}}
            if all(labels.get(k) == v for k, v in wanted.items()):
                print(f"{{project}}_{{volume}}")
        sys.exit(0)
    if args[:2] == ["compose", "config"]:
        if code("FAKE_CONFIG_EXIT"):
            print("yaml: line 3: mapping values are not allowed in this context", file=sys.stderr)
            sys.exit(code("FAKE_CONFIG_EXIT"))
        # The project name, as Compose picks it: COMPOSE_PROJECT_NAME, else the folder.
        print("name: " + (os.environ.get("COMPOSE_PROJECT_NAME") or Path.cwd().name))
        print("services: {{}}")
        sys.exit(0)
    if args[:2] == ["compose", "ps"]:
        if "--services" in args:
            print(os.environ.get("FAKE_RUNNING", ""))
        else:
            print("NAME       SERVICE   STATUS")
        sys.exit(0)
    if args[:2] == ["compose", "run"]:
        if "app.jobs.db_backup" in args:
            label = args[args.index("--label") + 1]
            print(f"2026-10-08 12:00:00,000 INFO app.services.backup.service: {{label}} backup written: "
                  f"/backups/{{label}}/tracker-20261008T120000Z.dump", file=sys.stderr)
            sys.exit(code("FAKE_BACKUP_EXIT"))
        if "--check" in args:
            print("OK: readable backup (20 tables)")
            sys.exit(code("FAKE_CHECK_EXIT"))
        if "--yes" in args:
            sys.exit(code("FAKE_RESTORE_EXIT"))
    if args[:2] == ["compose", "up"]:
        sys.exit(code("FAKE_UP_EXIT"))
    if args[:2] == ["compose", "build"]:
        sys.exit(code("FAKE_BUILD_EXIT"))
    if args[:2] == ["compose", "stop"]:
        sys.exit(code("FAKE_STOP_EXIT"))
    sys.exit(0)

if name == "curl":
    counter = Path(log_path + ".curl")
    calls = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(calls + 1))
    if os.environ.get("FAKE_CURL_FAILS") == "always" or calls < int(os.environ.get("FAKE_CURL_FAILS", "0")):
        print("curl: (7) Failed to connect to tracker port 443", file=sys.stderr)
        sys.exit(7)
    sys.exit(0)

# bootstrap.sh's read-only queries
if name == "getent":
    sys.exit(code("FAKE_GETENT_EXIT"))
if name == "swapon" and "--show" in " ".join(args):
    print(os.environ.get("FAKE_SWAP", ""))
    sys.exit(0)
if name == "dpkg":
    print("amd64")
    sys.exit(0)
if name == "hostname":
    print("203.0.113.10 10.0.0.5")
    sys.exit(0)
if name == "systemctl" and args[:1] == ["is-active"]:
    sys.exit(code("FAKE_SSH_INACTIVE"))
sys.exit(0)
"""

# Everything bootstrap.sh runs, so even a dry-run bug could only log.
BOOTSTRAP_FAKES = [
    "apt-get", "curl", "dpkg", "fallocate", "getent", "hostname", "install", "mkswap",
    "rm", "sshd", "swapon", "sysctl", "systemctl", "timedatectl", "ufw", "useradd",
    "usermod", "visudo", "chmod", "chown",
]  # fmt: skip
DEPLOY_FAKES = ["docker", "curl"]


class Fakes:
    def __init__(self, root: Path, names: list[str]):
        self.bin = root / "fakebin"
        self.bin.mkdir()
        self.log = root / "fake.log"
        program = self.bin / "fake.py"
        program.write_text(FAKE_PROGRAM.format(python=sys.executable))
        program.chmod(0o755)
        for name in names:
            (self.bin / name).symlink_to(program)
        self.home = root / "home"
        self.home.mkdir()
        self.env = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(self.home),
            "LANG": "C.UTF-8",
            "FAKE_LOG": str(self.log),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
            "TRACKER_HEALTH_INTERVAL": "0",
        }

    def calls(self, cmd: str | None = None) -> list[dict]:
        if not self.log.exists():
            return []
        entries = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [e for e in entries if cmd is None or e["cmd"] == cmd]

    def commands(self, cmd: str | None = None) -> list[str]:
        return [" ".join([e["cmd"], *e["args"]]) for e in self.calls(cmd)]

    def run(self, argv: list[str], *, cwd: Path, input: str = "", **env) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(a) for a in argv],
            cwd=cwd,
            env={**self.env, **env},
            input=input,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )


def git(cwd: Path, *args: str, env: dict) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=60, check=True
    )
    return result.stdout.strip()


ENV_FILE = """DOMAIN=tracker.test
CONTACT_EMAIL=
POSTGRES_USER=app
POSTGRES_PASSWORD=pw-0123456789
POSTGRES_DB=internship_tracker
DATABASE_URL=postgresql+psycopg://app:pw-0123456789@db:5432/internship_tracker
JWT_SECRET=not-a-placeholder-0123456789abcdef0123456789abcdef
TOKEN_ENCRYPTION_KEY=ABq5Suzsc4_drcqfJe-4EkCP5_VE9Qud2EdPzorSPOk=
"""


class Server:
    """A clone of a throwaway origin, as on the server: commits c1 (tag v1),
    c2 and c3, each with its own docker-compose.yml and the real
    ops/server scripts. The clone was made at c2 and is checked out at c1;
    c3 was pushed after the clone, so only a fetch can find it."""

    def __init__(self, root: Path, fakes: Fakes):
        env = fakes.env
        origin = root / "origin.git"
        work = root / "work"
        self.path = root / "server"
        git(root, "init", "--quiet", "--bare", "--initial-branch=main", str(origin), env=env)
        git(root, "clone", "--quiet", str(origin), str(work), env=env)
        shutil.copytree(SCRIPTS, work / "ops" / "server")
        (work / ".gitignore").write_text(".env\n/backups/\n")
        self.commits = {}
        for name in ("c1", "c2"):
            self._commit(work, name, env)
        git(work, "tag", "v1", self.commits["c1"], env=env)
        git(work, "push", "--quiet", "origin", "main", "--tags", env=env)
        git(root, "clone", "--quiet", str(origin), str(self.path), env=env)
        self._commit(work, "c3", env)
        git(work, "push", "--quiet", "origin", "main", env=env)
        git(self.path, "checkout", "--quiet", "--detach", self.commits["c1"], env=env)
        self.env_file = self.path / ".env"
        self.env_file.write_text(ENV_FILE)
        self.env_file.chmod(0o600)
        self._git_env = env

    def _commit(self, work: Path, name: str, env: dict) -> None:
        (work / "docker-compose.yml").write_text(f"# {name}\n")
        git(work, "add", "-A", env=env)
        git(work, "commit", "--quiet", "-m", f"commit {name}", env=env)
        self.commits[name] = git(work, "rev-parse", "HEAD", env=env)

    def head(self) -> str:
        return git(self.path, "rev-parse", "HEAD", env=self._git_env)

    @property
    def deploy(self) -> Path:
        return self.path / "ops" / "server" / "deploy.sh"

    @property
    def restore(self) -> Path:
        return self.path / "ops" / "server" / "restore.sh"


@pytest.fixture()
def deploy_fakes(tmp_path) -> Fakes:
    return Fakes(tmp_path, DEPLOY_FAKES)


@pytest.fixture()
def server(tmp_path, deploy_fakes) -> Server:
    return Server(tmp_path, deploy_fakes)


class FakeHost:
    """The files bootstrap.sh reads to see what the server already has, under
    tmp_path instead of the test machine's own (a CI runner has a real
    /swapfile, for example). It starts as a new droplet: root has an SSH key,
    nothing else exists yet."""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir()
        self.os_release = root / "os-release"
        self.os_release.write_text('ID=ubuntu\nVERSION_ID="24.04"\nVERSION_CODENAME=noble\n')
        self.zoneinfo = root / "zoneinfo"
        for zone in ("America/Chicago", "Europe/London"):
            (self.zoneinfo / zone).parent.mkdir(parents=True, exist_ok=True)
            (self.zoneinfo / zone).write_bytes(b"TZif")
        self.root_keys = root / "root-authorized_keys"
        self.root_keys.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeKeyForTestsOnly tracker\n")
        self.deploy_keys = root / "deploy-authorized_keys"
        self.docker_key = root / "docker.asc"
        self.swapfile = root / "swapfile"
        self.fstab = root / "fstab"

    def env(self) -> dict[str, str]:
        return {
            "TRACKER_BOOTSTRAP_OS_RELEASE": str(self.os_release),
            "TRACKER_BOOTSTRAP_ZONEINFO": str(self.zoneinfo),
            "TRACKER_BOOTSTRAP_ROOT_KEYS": str(self.root_keys),
            "TRACKER_BOOTSTRAP_DEPLOY_KEYS": str(self.deploy_keys),
            "TRACKER_BOOTSTRAP_DOCKER_KEY": str(self.docker_key),
            "TRACKER_BOOTSTRAP_SWAPFILE": str(self.swapfile),
            "TRACKER_BOOTSTRAP_FSTAB": str(self.fstab),
        }


@pytest.fixture()
def fake_host(tmp_path) -> FakeHost:
    return FakeHost(tmp_path / "host")


@pytest.fixture()
def bootstrap_fakes(tmp_path, fake_host) -> Fakes:
    fakes = Fakes(tmp_path, BOOTSTRAP_FAKES)
    fakes.env.update(
        {
            "TRACKER_BOOTSTRAP_EUID": "0",
            **fake_host.env(),
            "FAKE_GETENT_EXIT": "2",  # no deploy user yet
        }
    )
    return fakes


def is_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & stat.S_IXUSR)
