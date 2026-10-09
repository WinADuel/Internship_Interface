# shellcheck shell=bash
# Shared helpers for deploy.sh and restore.sh (Phase 3 spec §4.2, §4.4).
# Sourced, not run. Every function except resolve_backup_file expects the
# current directory to be the repo root (both scripts cd there first).
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

# Refuses to go on unless .env exists, is private to this user, has no
# change-me placeholders left (spec §4.2 step 1, §5) and doesn't put the
# example contact address on the public pages.
check_env_file() {
	local mode owner placeholders contact
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
	# Blank is fine: the pages then say "the site owner".
	contact="$(env_value CONTACT_EMAIL)"
	if [[ "${contact,,}" == *@example.com ]]; then
		die "CONTACT_EMAIL in .env is still an example address ($contact); the public pages would show it." \
			"set CONTACT_EMAIL to your own email (Google requires one to publish the app), or leave it empty"
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

# True when this Compose project's pgdata volume exists, i.e. this server has
# database files even if the db container isn't running (after `docker compose
# down`). Another project's database on the same machine doesn't count. The
# project name is what Compose uses (COMPOSE_PROJECT_NAME, else the folder name).
db_volume_exists() {
	local project volumes
	project="$(docker compose config --no-interpolate 2>/dev/null | sed -n '1s/^name: //p')"
	[[ -n "$project" ]] || die "could not read the Compose project name (docker compose config failed)."
	if ! volumes="$(docker volume ls --quiet --filter "label=com.docker.compose.project=$project" \
		--filter label=com.docker.compose.volume=pgdata)"; then
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

# Every service that uses the database: stopped during a restore (db keeps running).
APP_SERVICES=(backend sheet-sync job-scan gmail-sync db-backup caddy)

# resolve_backup_file <file> <repo root>: where the db-backup container will find a backup,
# in RESTORE_PATH (inside the container) and RESTORE_MOUNT (options for
# `docker compose run`). Dumps the server made stay where they are (./backups
# is mounted at /backups, and is readable only by root on the host); any other
# file is mounted read-only. Call it before cd-ing to the repo root, since a
# relative path is from wherever the script was started.
RESTORE_PATH=""
RESTORE_MOUNT=()
resolve_backup_file() {
	local file="$1" repo="$2" path
	case "$file" in
	*.dump | *.dump.enc) ;;
	*) die "'$file' is not a backup: the name must end in .dump or .dump.enc." ;;
	esac
	path="$(realpath --no-symlinks --canonicalize-missing -- "$file")"
	RESTORE_MOUNT=()
	if [[ "$path" == /backups/* ]]; then
		RESTORE_PATH="$path"
	elif [[ "$path" == "$repo/backups/"* ]]; then
		RESTORE_PATH="/backups/${path#"$repo/backups/"}"
	else
		if [[ ! -f "$path" || ! -r "$path" ]]; then
			die "cannot read $path." "check the path (ls -l '$path')"
		fi
		if [[ "$path" == *:* ]]; then
			die "Docker can't mount a path with ':' in it: $path" "move or rename the file"
		fi
		RESTORE_PATH="/restore/backup.dump"
		if [[ "$path" == *.enc ]]; then
			RESTORE_PATH="/restore/backup.dump.enc"
		fi
		RESTORE_MOUNT=(-v "$path:$RESTORE_PATH:ro")
	fi
}

# check_backup_file <file as given>: refuses, before anything changes, unless
# the backup found by resolve_backup_file exists and can be restored.
check_backup_file() {
	say "Checking the backup can be read"
	if ! docker compose run --rm -T "${RESTORE_MOUNT[@]}" db-backup \
		python -m app.cli restore "$RESTORE_PATH" --check </dev/null; then
		die "$1 can't be restored (see the error above); nothing was changed."
	fi
}

# confirm_restore <database> <file as given>: asks for the database name to
# be typed; anything else stops the script. --yes skips this (the callers').
confirm_restore() {
	local database="$1" file="$2" answer=""
	printf '\nThis REPLACES ALL DATA in the database "%s" with:\n  %s\n' "$database" "$file"
	printf 'Type the database name (%s) to continue: ' "$database"
	read -r answer || true
	if [[ "$answer" != "$database" ]]; then
		die "not confirmed; nothing was changed."
	fi
}

stop_app() {
	say "Stopping the app (the database keeps running)"
	docker compose stop "${APP_SERVICES[@]}"
}

# restore_backup_file <file as given>: replaces the whole database with the
# backup found by resolve_backup_file. It runs in one transaction: when it
# fails (non-zero), the database is left as it was.
restore_backup_file() {
	say "Restoring $1"
	docker compose run --rm -T "${RESTORE_MOUNT[@]}" db-backup \
		python -m app.cli restore "$RESTORE_PATH" --yes </dev/null
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
