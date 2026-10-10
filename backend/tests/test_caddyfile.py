"""Static checks on the repo-root Caddyfile (Phase 3 spec §4.3, §4.5).

These read the file only; `ops/checks/check-caddyfile.sh` runs `caddy validate` on it.
"""

from pathlib import Path

import pytest

CADDYFILE = (Path(__file__).resolve().parents[2] / "Caddyfile").read_text()

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


def _header_block() -> str:
    start = CADDYFILE.index("\theader {")
    return CADDYFILE[start : CADDYFILE.index("\t}", start)]


@pytest.mark.parametrize(
    "line",
    [
        'Strict-Transport-Security "max-age=31536000"',
        "X-Frame-Options DENY",
        "X-Content-Type-Options nosniff",
        "Referrer-Policy strict-origin-when-cross-origin",
        f'Content-Security-Policy "{CSP}"',
        'Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=()"',
    ],
)
def test_security_headers_are_set_site_wide(line):
    assert line in _header_block()


def test_header_block_comes_before_the_handlers():
    # A top-level header block covers /api/* and the static files alike.
    assert CADDYFILE.index("\theader {") < CADDYFILE.index("\thandle ")


def test_templates_run_only_on_the_public_pages():
    assert "@public_pages path /about.html /privacy.html" in CADDYFILE
    lines = [line.strip() for line in CADDYFILE.splitlines()]
    templates = [line for line in lines if line.startswith("templates")]
    assert templates == ["templates @public_pages"]


def test_manifest_is_served_as_a_web_app_manifest():
    # Caddy's built-in type table has no entry for .webmanifest (spec §4.6).
    assert "@manifest path /manifest.webmanifest" in CADDYFILE
    assert "header @manifest Content-Type application/manifest+json" in CADDYFILE
