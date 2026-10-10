"""docs/deploy/server-setup.md (Phase 3 spec §4.7) must match the real
scripts: every ops script it names exists, every flag it passes is one the
script knows, its links resolve, and the scripts' "step N" hints point at
the right section."""

import re
from pathlib import Path

import pytest

from tests.ops.conftest import REPO_ROOT

GUIDE = REPO_ROOT / "docs" / "deploy" / "server-setup.md"
README = REPO_ROOT / "README.md"
SCRIPT_RE = re.compile(r"ops/(?:server|checks)/[a-z-]+\.sh")
# `deploy.sh --skip-backup`, `bash bootstrap.sh --dry-run`, ...
FLAG_RE = re.compile(r"\b((?:bootstrap|deploy|restore)\.sh)((?:\s+--[a-z-]+)+)")
LINK_RE = re.compile(r"\]\(([^)\s]+)\)")


@pytest.fixture(scope="module")
def guide() -> str:
    return GUIDE.read_text()


def _slug(heading: str) -> str:
    # GitHub's anchor for a heading: lower case, punctuation dropped, spaces to hyphens.
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    return {_slug(m) for m in re.findall(r"^#+\s+(.*)$", path.read_text(), flags=re.M)}


@pytest.mark.parametrize("doc", [GUIDE, README], ids=["guide", "readme"])
def test_every_ops_script_named_exists(doc):
    names = set(SCRIPT_RE.findall(doc.read_text()))
    assert names, doc
    for name in names:
        assert (REPO_ROOT / name).is_file(), name


def test_guide_covers_every_server_script(guide):
    for name in ("bootstrap.sh", "deploy.sh", "restore.sh"):
        assert f"ops/server/{name}" in guide, name


@pytest.mark.parametrize("doc", [GUIDE, README], ids=["guide", "readme"])
def test_every_flag_given_to_a_script_exists(doc):
    for script, flags in FLAG_RE.findall(doc.read_text()):
        source = (REPO_ROOT / "ops" / "server" / script).read_text()
        for flag in flags.split():
            assert f"{flag})" in source, f"{script} has no {flag} option"


def test_links_resolve(guide):
    links = LINK_RE.findall(guide)
    assert links
    for link in links:
        if link.startswith(("http://", "https://")):
            continue
        target, _, anchor = link.partition("#")
        path = (GUIDE.parent / target).resolve() if target else GUIDE
        assert path.is_file(), link
        if anchor:
            assert anchor in _anchors(path), link


def test_scripts_step_hints_point_at_the_right_sections(guide):
    sections = dict(re.findall(r"^## (\d+)\. (.*)$", guide, flags=re.M))
    assert [int(n) for n in sections] == list(range(1, 12))
    hints = []
    for script in (REPO_ROOT / "ops" / "server").glob("*.sh"):
        hints += re.findall(r"server-setup\.md, step (\d+)", script.read_text())
    assert hints == ["5"]  # bootstrap.sh: next, add the deploy key and clone
    assert "Deploy key" in sections["5"]


def test_guide_uses_the_env_example_commands(guide):
    env_example = (REPO_ROOT / ".env.example").read_text()
    for command in ("openssl rand -hex 16", "openssl rand -hex 48", "openssl rand -base64 32 | tr '+/' '-_'"):
        assert command in guide, command
        assert command in env_example, command
    for key in ("BACKUP_ENCRYPTION_KEY", "TOKEN_ENCRYPTION_KEY", "CONTACT_EMAIL", "GOOGLE_REDIRECT_URI", "COOKIE_SECURE=true"):
        assert key in guide, key
