#!/usr/bin/env bash
# Validates the repo-root Caddyfile with `caddy validate` (Phase 3 spec §4.3).
#
# Usage: ops/checks/check-caddyfile.sh
#   Runs Caddy from the caddy:2 image (the same image the frontend Dockerfile builds on).
#   Set CADDY_BIN=/path/to/caddy to use a local Caddy binary instead of Docker.
#   Without Docker or CADDY_BIN the check is skipped (exit 0) with a message.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
caddyfile="$repo_root/Caddyfile"

if [[ -n "${CADDY_BIN:-}" ]]; then
	DOMAIN=localhost "$CADDY_BIN" validate --config "$caddyfile" --adapter caddyfile
elif command -v docker >/dev/null 2>&1; then
	docker run --rm \
		-e DOMAIN=localhost \
		-v "$caddyfile:/etc/caddy/Caddyfile:ro" \
		caddy:2 \
		caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
else
	echo "check-caddyfile: skipped (no docker and no CADDY_BIN)" >&2
	exit 0
fi
echo "check-caddyfile: Caddyfile is valid"
