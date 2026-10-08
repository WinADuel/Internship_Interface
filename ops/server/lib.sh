# shellcheck shell=bash
# Shared helpers for deploy.sh and restore.sh (Phase 3 spec §4.2, §4.4).
# Sourced, not run. Every function expects the current directory to be the
# repo root (both scripts cd there first).
#
# Test hooks (for backend/tests/ops only; never set them on the server):
#   TRACKER_HEALTH_TIMEOUT   seconds to wait for /api/health (default 120)
#   TRACKER_HEALTH_INTERVAL  seconds between attempts (default 3)

say() {
	printf '==> %s\n' "$*"
}

info() {
	printf '    %s\n' "$*"
}

warn() {
	printf 'WARNING: %s\n' "$*" >&2
}

# die <message> [how to fix it]
die() {
	printf 'ERROR: %s\n' "$1" >&2
	if [[ -n "${2:-}" ]]; then
		printf '  To fix: %s\n' "$2" >&2
	fi
	exit 1
}

# env_value <KEY>: the value of KEY in .env (the last line that sets it), with
# surrounding quotes removed; empty when unset. The file is read, never
# sourced, so nothing in it can run as a command.
env_value() {
	local key="$1"
	{ grep -E "^[[:space:]]*${key}[[:space:]]*=" .env || true; } |
		tail -n 1 |
		sed -E \
			-e 's/\r$//' \
			-e 's/^[^=]*=[[:space:]]*//' \
			-e 's/[[:space:]]+$//' \
			-e 's/^"(.*)"$/\1/' \
			-e "s/^'(.*)'\$/\\1/"
}

# Refuses to go on unless .env exists, is private to this user and has no
# change-me placeholders left (spec §4.2 step 1, §5).
check_env_file() {
	local mode owner placeholders
	if [[ ! -f .env ]]; then
		die ".env is missing in $PWD." \
			"cp .env.example .env && chmod 600 .env, then fill it in (docs/deploy/server-setup.md)."
	fi
	mode="$(stat -c '%a' .env)"
	# Any permission bit for group or others (the last two octal digits) is too open.
	if (((8#$mode & 8#077) != 0)); then
		die ".env can be read by other users on this server (mode $mode); it holds every secret." \
			"chmod 600 .env"
	fi
	owner="$(stat -c '%u' .env)"
	if [[ "$owner" != "$(id -u)" ]]; then
		die ".env belongs to $(stat -c '%U' .env), not to you ($(id -un))." \
			"sudo chown $(id -un): .env"
	fi
	placeholders="$(
		{ grep -E '^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*[[:space:]]*=.*change-me' .env || true; } |
			sed -E 's/^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*).*/\1/' |
			tr '\n' ' '
	)"
	if [[ -n "$placeholders" ]]; then
		die ".env still has change-me placeholders: ${placeholders% }" \
			"edit .env (nano .env) and replace each change-me value; the guide shows how to generate them."
	fi
}

# check_domain <domain>: refuses an empty, malformed or example domain.
check_domain() {
	local domain="$1"
	if [[ -z "$domain" ]]; then
		die "DOMAIN is not set in .env." "add a line like DOMAIN=yourdomain.com to .env"
	fi
	if [[ ! "$domain" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]; then
		die "DOMAIN in .env is not a plain host name: '$domain'" \
			"use just the name, e.g. DOMAIN=yourdomain.com (no https://, no slash, no comment)"
	fi
	if [[ "$domain" == example.com || "$domain" == *.example.com ]]; then
		die "DOMAIN in .env is still the example ($domain)." "set DOMAIN to your own domain"
	fi
}

require_docker() {
	if ! docker info >/dev/null 2>&1; then
		die "cannot talk to Docker." \
			"if you just ran bootstrap.sh, log out and back in so the docker group applies, then check with: docker info"
	fi
}

# True when the db service's container is running.
db_is_running() {
	local services
	# Captured first: `grep -q` in a pipe could end docker early and fail the pipe.
	if ! services="$(docker compose ps --status running --services)"; then
		die "docker compose ps failed (see the error above)."
	fi
	grep -qx db <<<"$services"
}

# True when a Compose pgdata volume exists, i.e. this server has database
# files even if the db container isn't running (after `docker compose down`).
db_volume_exists() {
	local volumes
	if ! volumes="$(docker volume ls --quiet --filter label=com.docker.compose.volume=pgdata)"; then
		die "docker volume ls failed (see the error above)."
	fi
	[[ -n "$volumes" ]]
}

# take_backup <label>: one backup in the db-backup service. Its log goes to
# stderr as it happens; the new dump's path inside the container (for example
# /backups/pre-deploy/tracker-20261008T023000Z.dump) is printed on stdout.
# Returns non-zero when the backup failed.
take_backup() {
	local label="$1" log status=0
	log="$(mktemp)"
	docker compose run --rm -T db-backup python -m app.jobs.db_backup --once --label "$label" </dev/null 2>&1 |
		tee "$log" >&2 || status=$?
	{ grep -oE '/backups/[a-z-]+/tracker-[0-9]{8}T[0-9]{6}Z\.dump' "$log" || true; } | tail -n 1
	rm -f "$log"
	return "$status"
}

# wait_for_health <domain>: polls https://<domain>/api/health on this server.
# --resolve sends the request to 127.0.0.1 with the right name for HTTPS, so
# it tests this server even before DNS points here. localhost uses Caddy's
# internal certificate authority, which curl doesn't trust, hence --insecure.
wait_for_health() {
	local domain="$1"
	local url="https://$domain/api/health"
	local timeout="${TRACKER_HEALTH_TIMEOUT:-120}"
	local interval="${TRACKER_HEALTH_INTERVAL:-3}"
	local deadline=$((SECONDS + timeout))
	local tls_options=()
	local last_error=""
	if [[ "$domain" == localhost ]]; then
		tls_options=(--insecure)
	fi
	say "Waiting up to ${timeout}s for $url"
	while true; do
		if last_error="$(curl --silent --show-error --fail --max-time 10 \
			--resolve "$domain:443:127.0.0.1" "${tls_options[@]}" \
			--output /dev/null "$url" 2>&1)"; then
			info "healthy"
			return 0
		fi
		if ((SECONDS >= deadline)); then
			break
		fi
		sleep "$interval"
	done
	printf 'ERROR: %s did not answer within %ss.\n' "$url" "$timeout" >&2
	if [[ -n "$last_error" ]]; then
		printf '  Last error: %s\n' "$last_error" >&2
	fi
	printf '  Container status:\n' >&2
	docker compose ps >&2 || true
	printf '  To look into it:\n' >&2
	printf '    docker compose logs backend --tail 50   (the app)\n' >&2
	printf '    docker compose logs caddy --tail 50     (HTTPS certificate problems show here;\n' >&2
	printf '                                            check DNS with: dig +short %s)\n' "$domain" >&2
	return 1
}
