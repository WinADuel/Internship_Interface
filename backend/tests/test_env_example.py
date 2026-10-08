"""The repo-root .env.example is what the server's .env starts from (Phase 3
Task 8, docs/deploy/server-setup.md step 6), so it must name every value the
backend and docker-compose.yml need, with generation commands that work on a
stock Mac and on Ubuntu."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO_ROOT / ".env.example"
COMPOSE = REPO_ROOT / "docker-compose.yml"

FERNET_OPENSSL = "openssl rand -base64 32 | tr '+/' '-_'"


@pytest.fixture(scope="module")
def text() -> str:
    return ENV_EXAMPLE.read_text()


@pytest.fixture(scope="module")
def values(text) -> dict[str, str]:
    found = {}
    for line in text.splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line)
        if match:
            assert match.group(1) not in found, f"{match.group(1)} is set twice"
            found[match.group(1)] = match.group(2)
    return found


def test_has_every_setting_the_backend_requires(values):
    required = {name.upper() for name, field in Settings.model_fields.items() if field.is_required()}
    assert required, "Settings has no required fields?"
    assert required <= values.keys(), required - values.keys()


def test_has_every_variable_compose_needs(values):
    # ${NAME} without a :- default must come from .env.
    needed = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)\}", COMPOSE.read_text()))
    assert {"DOMAIN", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"} <= needed
    assert needed <= values.keys(), needed - values.keys()


def test_contact_email_and_tz(values):
    assert "CONTACT_EMAIL" in values
    assert values["TZ"] == "America/Chicago"
    assert values["COOKIE_SECURE"] == "true"


def test_backup_encryption_key_is_blank(values):
    # Blank means "no off-site copy"; a placeholder would stop the backend from starting.
    assert values["BACKUP_ENCRYPTION_KEY"] == ""


def test_redirect_uri_matches_the_domain(values, text):
    assert values["GOOGLE_REDIRECT_URI"] == f"https://{values['DOMAIN']}/api/docs/google/callback"
    assert "https://localhost/api/docs/google/callback" in text


def test_database_url_uses_the_postgres_values(values):
    assert values["DATABASE_URL"] == (
        f"postgresql+psycopg://{values['POSTGRES_USER']}:{values['POSTGRES_PASSWORD']}"
        f"@db:5432/{values['POSTGRES_DB']}"
    )


def test_secrets_are_change_me_placeholders(values):
    # deploy.sh refuses a .env that still has change-me in it.
    for key in ("POSTGRES_PASSWORD", "JWT_SECRET", "TOKEN_ENCRYPTION_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
        assert "change-me" in values[key], key


def test_gives_openssl_and_python_commands(text):
    assert "openssl rand -hex 48" in text  # JWT_SECRET
    assert "openssl rand -hex 16" in text  # database password
    assert text.count(FERNET_OPENSSL) >= 1
    assert "secrets.token_urlsafe" in text
    assert "Fernet.generate_key()" in text


def test_openssl_fernet_command_makes_valid_keys():
    if shutil.which("openssl") is None:
        if os.environ.get("CI"):
            pytest.fail("openssl not on PATH")
        pytest.skip("openssl not on PATH")
    keys = set()
    for _ in range(5):
        result = subprocess.run(
            ["bash", "-c", FERNET_OPENSSL], capture_output=True, text=True, timeout=10, check=True
        )
        key = result.stdout.strip()
        Fernet(key)  # raises if invalid
        keys.add(key)
    assert len(keys) == 5
