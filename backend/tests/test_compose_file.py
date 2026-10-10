"""Static checks on the repo-root docker-compose.yml (Phase 3 spec §4.3).

These parse the file only; nothing here talks to Docker.
"""

from pathlib import Path

import pytest
import yaml

COMPOSE_PATH = Path(__file__).resolve().parents[2] / "docker-compose.yml"

EXPECTED_LOGGING = {
    "driver": "json-file",
    "options": {"max-size": "10m", "max-file": "3"},
}


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(COMPOSE_PATH.read_text())


@pytest.fixture(scope="module")
def services(compose):
    return compose["services"]


def test_logging_anchor_rotates_json_file_logs(compose):
    assert compose["x-logging"] == EXPECTED_LOGGING


def test_every_service_uses_the_logging_anchor(compose, services):
    # A YAML alias loads as the very same object as its anchor, so identity
    # proves each service reuses x-logging rather than a hand-copied block.
    assert services
    for name, service in services.items():
        assert service.get("logging") is compose["x-logging"], name


def test_backend_healthcheck_hits_api_health_without_curl(services):
    healthcheck = services["backend"]["healthcheck"]
    test = healthcheck["test"]
    assert test[0] == "CMD"
    assert test[1] == "python"
    command = " ".join(test)
    assert "urllib.request" in command
    assert "http://localhost:8000/api/health" in command
    assert "curl" not in command
    assert healthcheck["interval"] == "10s"
    assert healthcheck["timeout"] == "5s"
    assert healthcheck["retries"] == 6
    assert healthcheck["start_period"] == "30s"


def test_backend_serves_on_the_port_the_healthcheck_probes():
    dockerfile = (COMPOSE_PATH.parent / "backend" / "Dockerfile").read_text()
    assert "--port 8000" in dockerfile


@pytest.mark.parametrize(
    ("service", "dependency", "condition"),
    [
        ("backend", "db", "service_healthy"),
        ("sheet-sync", "db", "service_healthy"),
        ("job-scan", "db", "service_healthy"),
        ("db-backup", "db", "service_healthy"),
        ("gmail-sync", "db", "service_healthy"),
        ("caddy", "backend", "service_healthy"),
    ],
)
def test_depends_on_conditions(services, service, dependency, condition):
    depends_on = services[service]["depends_on"]
    assert depends_on[dependency] == {"condition": condition}


def test_db_publishes_no_ports(services):
    assert "ports" not in services["db"]


def test_only_caddy_publishes_ports(services):
    publishing = sorted(name for name, service in services.items() if "ports" in service)
    assert publishing == ["caddy"]


def test_backend_image_installs_postgres_16_client_from_pgdg():
    dockerfile = (COMPOSE_PATH.parent / "backend" / "Dockerfile").read_text()
    assert "apt.postgresql.org/pub/repos/apt" in dockerfile
    assert "bookworm-pgdg" in dockerfile
    assert "postgresql-client-16" in dockerfile
    assert "--no-install-recommends" in dockerfile
    assert "rm -rf /var/lib/apt/lists/*" in dockerfile


def test_caddy_gets_domain_and_optional_contact_email(services):
    # CONTACT_EMAIL fills in the public pages (spec §4.5); empty means "the site owner".
    assert services["caddy"]["environment"] == {
        "DOMAIN": "${DOMAIN}",
        "CONTACT_EMAIL": "${CONTACT_EMAIL:-}",
    }


def test_caddy_mounts_the_repo_caddyfile_read_only(services):
    assert "./Caddyfile:/etc/caddy/Caddyfile:ro" in services["caddy"]["volumes"]


def test_env_example_lists_contact_email():
    env_example = (COMPOSE_PATH.parent / ".env.example").read_text()
    assert "\nCONTACT_EMAIL=" in env_example


def test_db_backup_service_runs_the_backup_job(services):
    service = services["db-backup"]
    assert service["build"] == "./backend"
    assert service["restart"] == "unless-stopped"
    assert service["env_file"] == ".env"
    assert service["command"] == "python -m app.jobs.db_backup"
    # TZ decides when 02:30 is; BACKUP_DIR is the bind-mounted folder on the host.
    assert service["environment"] == {"TZ": "${TZ:-UTC}", "BACKUP_DIR": "/backups"}
    assert service["volumes"] == ["./backups:/backups"]


def test_backend_writes_manual_backups_to_the_same_folder(services):
    # Back up now (POST /api/backups/run) runs pg_dump in the backend container.
    service = services["backend"]
    assert service["environment"] == {"BACKUP_DIR": "/backups"}
    assert service["volumes"] == ["./backups:/backups"]
    assert service["volumes"] == services["db-backup"]["volumes"]


def test_backups_folder_is_git_ignored():
    gitignore = (COMPOSE_PATH.parent / ".gitignore").read_text().splitlines()
    assert "/backups/" in gitignore


def test_gmail_sync_service_runs_the_gmail_job(services):
    service = services["gmail-sync"]
    assert service["build"] == "./backend"
    assert service["restart"] == "unless-stopped"
    assert service["env_file"] == ".env"
    assert service["command"] == "python -m app.jobs.gmail_sync"
    assert service["environment"] == {"TZ": "${TZ:-UTC}"}
    # It needs no files: nothing it reads is written to disk.
    assert "volumes" not in service


def test_restore_stops_every_service_that_uses_the_database(services):
    # ops/server/lib.sh APP_SERVICES: everything but the database itself.
    lib = (COMPOSE_PATH.parent / "ops" / "server" / "lib.sh").read_text()
    line = next(x for x in lib.splitlines() if x.startswith("APP_SERVICES=("))
    listed = line.removeprefix("APP_SERVICES=(").removesuffix(")").split()
    assert sorted(listed) == sorted(set(services) - {"db"})
