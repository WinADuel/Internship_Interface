#!/usr/bin/env bash
# Full-stack smoke test (Phase 3 Task 9): builds and runs the real stack with
# DOMAIN=localhost, the way the server runs it, through the real server scripts.
# CI runs it on every pull request (the stack-smoke job).
#
# Usage: ops/checks/stack-smoke.sh [--force-env]
#   Needs Docker with Compose, network access for the image builds, free
#   ports 80 and 443, and curl, git and openssl. Run it from a clean checkout:
#   deploy.sh refuses changes to tracked files.
#   It writes a throwaway .env (generated secrets, placeholder Google values)
#   and at the end removes it, ./backups and the Compose project's containers
#   and volumes (project "tracker-smoke", so a local stack's data is untouched).
#   --force-env  run even though .env exists: it's moved to .env.before-smoke
#                and put back at the end. Without it an existing .env stops the
#                test, as does an existing ./backups (it would be deleted).
#
# Steps: deploy.sh (first deploy) of the checked-out commit; HTTPS, security
# headers and the public pages; the API refuses an unauthenticated call; a
# manual backup; restore.sh of that backup removes a row added after it; a
# second deploy.sh takes its pre-deploy backup.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
# say, info, die and wait_for_health, as deploy.sh and restore.sh use them.
# shellcheck source=../server/lib.sh
source "$repo_root/ops/server/lib.sh"

CONTACT=smoke@example.com
# Every docker compose command below, and in deploy.sh and restore.sh, uses this project.
export COMPOSE_PROJECT_NAME=tracker-smoke
# A row restore.sh must remove: added after the backup it restores.
MARKER=stack-smoke-marker

usage() {
	sed -n '2,20p' "$script_dir/stack-smoke.sh" | sed 's/^# \{0,1\}//'
}

failures=0
work=""
env_written=0
env_saved=0

# check <description> <command...>: runs the command; a failure is counted and
# the test goes on, so one run reports every broken header and page.
check() {
	local what="$1"
	shift
	if "$@"; then
		info "ok: $what"
	else
		printf 'FAIL: %s\n' "$what" >&2
		failures=$((failures + 1))
	fi
}

# fetch <path>: GET https://localhost<path>. Headers go to $work/headers and the
# body to $work/body; prints the status code. Caddy's local certificate
# authority isn't trusted, hence --insecure (as in wait_for_health).
fetch() {
	curl --silent --show-error --max-time 15 --insecure \
		--resolve localhost:443:127.0.0.1 \
		--dump-header "$work/headers" --output "$work/body" \
		--write-out '%{http_code}' "https://localhost$1"
}

# header <name>: the value of the last <name> header in $work/headers.
header() {
	{ grep -i "^$1:" "$work/headers" || true; } | tail -n 1 | sed -E 's/^[^:]*:[[:space:]]*//; s/\r$//'
}

has_header() {
	local value
	value="$(header "$1")"
	[[ "$value" == *"$2"* ]]
}

# Exactly one of the header: a second copy (say from the backend) would make
# browsers enforce both.
header_once() {
	[[ "$(grep -ci "^$1:" "$work/headers")" == 1 ]]
}

body_has() {
	grep -qF -- "$1" "$work/body"
}

body_lacks() {
	! grep -qF -- "$1" "$work/body"
}

status_is() {
	local expected="$1" path="$2" got
	got="$(fetch "$path")" || return 1
	[[ "$got" == "$expected" ]] || {
		printf '  %s answered %s, expected %s\n' "$path" "$got" "$expected" >&2
		return 1
	}
}

check_security_headers() {
	local path="$1"
	check "$path: one Content-Security-Policy" header_once Content-Security-Policy
	check "$path: CSP default-src 'self'" has_header Content-Security-Policy "default-src 'self'"
	check "$path: CSP script-src 'self'" has_header Content-Security-Policy "script-src 'self';"
	check "$path: CSP frame-ancestors 'none'" has_header Content-Security-Policy "frame-ancestors 'none'"
	check "$path: CSP object-src 'none'" has_header Content-Security-Policy "object-src 'none'"
	check "$path: Permissions-Policy" has_header Permissions-Policy "camera=(), microphone=()"
	check "$path: Strict-Transport-Security" has_header Strict-Transport-Security "max-age=31536000"
	check "$path: X-Frame-Options DENY" has_header X-Frame-Options DENY
	check "$path: X-Content-Type-Options nosniff" has_header X-Content-Type-Options nosniff
	check "$path: Referrer-Policy" has_header Referrer-Policy strict-origin-when-cross-origin
}

# check_page <path> <status> <content type>: one GET, then its status, type and headers.
check_page() {
	local path="$1" status="$2" type="$3"
	check "$path answers $status" status_is "$status" "$path"
	check "$path is $type" has_header Content-Type "$type"
	check_security_headers "$path"
}

# db_query <sql>: one value from the database, through psql in the db container.
db_query() {
	docker compose exec -T db psql -X -A -t -v ON_ERROR_STOP=1 \
		-U "$(env_value POSTGRES_USER)" -d "$(env_value POSTGRES_DB)" -c "$1" </dev/null
}

marker_count() {
	db_query "SELECT count(*) FROM watch_companies WHERE board_token = '$MARKER'"
}

# latest_dump <label>: the newest dump's file name in backups/<label>. The files
# are root-only on the host, so the backend container (which mounts ./backups)
# lists them.
latest_dump() {
	docker compose exec -T backend sh -c "ls -1 /backups/$1 2>/dev/null || true" </dev/null |
		{ grep -E '^tracker-[0-9]{8}T[0-9]{6}Z\.dump$' || true; } | tail -n 1
}

backend_healthy() {
	local id
	id="$(docker compose ps -q backend)"
	[[ -n "$id" && "$(docker inspect --format '{{.State.Health.Status}}' "$id")" == healthy ]]
}

write_env() {
	local db_password
	db_password="$(openssl rand -hex 16)"
	# umask: the file is created 0600, so the secrets are never readable by others.
	(
		umask 077
		cat >.env <<EOF
# Throwaway .env written by ops/checks/stack-smoke.sh; it deletes this file when done.
DOMAIN=localhost
CONTACT_EMAIL=$CONTACT
POSTGRES_USER=app
POSTGRES_PASSWORD=$db_password
POSTGRES_DB=internship_tracker
DATABASE_URL=postgresql+psycopg://app:$db_password@db:5432/internship_tracker
JWT_SECRET=$(openssl rand -hex 48)
TOKEN_ENCRYPTION_KEY=$(openssl rand -base64 32 | tr '+/' '-_')
BACKUP_ENCRYPTION_KEY=$(openssl rand -base64 32 | tr '+/' '-_')
GOOGLE_CLIENT_ID=smoke-test-client-id
GOOGLE_CLIENT_SECRET=smoke-test-client-secret
GOOGLE_REDIRECT_URI=https://localhost/api/docs/google/callback
COOKIE_SECURE=true
TZ=UTC
EOF
	)
	chmod 600 .env
}

# ./backups is root's on the host (the containers write it), so a plain rm
# can't empty it unless this runs as root. The backend image (root inside)
# empties it; sudo is the fallback when that image was never built.
remove_backups() {
	[[ -e backups ]] || return 0
	rm -rf backups 2>/dev/null && return 0
	if docker image inspect "$COMPOSE_PROJECT_NAME-backend" >/dev/null 2>&1; then
		docker run --rm -v "$repo_root/backups:/backups" --entrypoint find \
			"$COMPOSE_PROJECT_NAME-backend" /backups -mindepth 1 -delete || true
	fi
	rm -rf backups 2>/dev/null && return 0
	if sudo -n true 2>/dev/null; then
		sudo -n rm -rf backups && return 0
	fi
	warn "could not remove $repo_root/backups (owned by root): sudo rm -rf backups"
}

cleanup() {
	local status=$?
	set +e
	trap - EXIT
	if ((status != 0)); then
		printf '\n' >&2
		say "FAILED: container status and logs" >&2
		docker compose ps -a >&2
		docker compose logs --no-color --tail 80 >&2
	fi
	say "Cleaning up"
	if ((env_written)); then
		docker compose down --volumes --remove-orphans
		remove_backups
		rm -f .env
	fi
	if ((env_saved)); then
		mv .env.before-smoke .env && info "your .env is back in place"
	fi
	[[ -n "$work" ]] && rm -rf "$work"
	exit "$status"
}

main() {
	local force_env=0
	while (($# > 0)); do
		case "$1" in
		-h | --help)
			usage
			return 0
			;;
		--force-env)
			force_env=1
			;;
		*)
			die "unknown argument: $1" "see ops/checks/stack-smoke.sh --help"
			;;
		esac
		shift
	done

	cd "$repo_root"
	local tool
	for tool in docker curl git openssl; do
		command -v "$tool" >/dev/null 2>&1 || die "$tool is not installed."
	done
	if [[ -e .env.before-smoke ]]; then
		die ".env.before-smoke exists: a previous smoke test was stopped before it could put .env back." \
			"check which file is your real .env, then remove .env.before-smoke"
	fi
	if [[ -e .env || -L .env ]] && ((!force_env)); then
		die "$repo_root/.env exists; this test writes its own and would replace yours." \
			"run it in a checkout without .env, or pass --force-env (yours is moved aside and put back)"
	fi
	if [[ -e backups ]]; then
		die "$repo_root/backups exists; this test deletes ./backups at the end." \
			"run it in a checkout without backups, or move them somewhere safe first"
	fi
	require_docker

	work="$(mktemp -d)"
	trap cleanup EXIT
	if [[ -e .env || -L .env ]]; then
		mv .env .env.before-smoke
		env_saved=1
		info "moved your .env to .env.before-smoke for the test"
	fi

	say "1. Writing a throwaway .env (DOMAIN=localhost)"
	# Set first: a half-written .env is removed too.
	env_written=1
	write_env

	# The checked-out commit, not deploy.sh's default origin/main: a pull request's CI
	# checkout is a detached merge commit, and that is the code under test. deploy.sh's
	# `git fetch` works there too (actions/checkout leaves an authenticated origin).
	local ref
	ref="$(git rev-parse HEAD)"

	# deploy.sh looks for any Compose pgdata volume, so a local stack's would make this
	# look like a redeploy (with a backup); CI starts with none.
	local other_volumes
	other_volumes="$(docker volume ls --quiet --filter label=com.docker.compose.volume=pgdata)"

	say "2. First deploy: ops/server/deploy.sh ${ref:0:12}"
	ops/server/deploy.sh "$ref" </dev/null | tee "$work/deploy1.log"
	if [[ -z "$other_volumes" ]]; then
		check "deploy.sh saw a first deploy (no backup)" grep -q "first deploy: no database yet" "$work/deploy1.log"
	fi
	check "backend container is healthy" backend_healthy

	say "3. HTTPS, security headers and the public pages"
	check "http:// redirects to https://" test \
		"$(curl --silent --max-time 15 --output /dev/null --write-out '%{http_code} %{redirect_url}' http://localhost/)" \
		= "308 https://localhost/"
	check_page / 200 text/html
	check "/ is the app" body_has "<title>Internship Tracker</title>"
	check_page /api/health 200 application/json
	check "/api/health says ok" body_has '"status":"ok"'
	local page
	for page in /about.html /privacy.html; do
		check_page "$page" 200 text/html
		check "$page shows CONTACT_EMAIL" body_has "$CONTACT"
		check "$page has no template left" body_lacks "{{"
	done
	check_page /manifest.webmanifest 200 application/manifest+json

	say "4. The API refuses a call without a session"
	check_page /api/backups/status 401 application/json

	say "5. Manual backup"
	docker compose run --rm -T db-backup python -m app.jobs.db_backup --once --label manual </dev/null
	local dump
	dump="$(latest_dump manual)"
	[[ -n "$dump" ]] || die "the manual backup exited 0, but backups/manual has no dump."
	info "backups/manual/$dump"

	say "6. Restore that backup: a row added after it must go"
	db_query "INSERT INTO watch_companies (name, ats, board_token, careers_url)
		VALUES ('Smoke test', 'greenhouse', '$MARKER', 'https://example.com/careers')" >/dev/null
	[[ "$(marker_count)" == 1 ]] || die "could not add the marker row."
	ops/server/restore.sh --yes "backups/manual/$dump" </dev/null
	check "the restore removed the marker row" test "$(marker_count)" = 0
	check "/api/health answers after the restore" status_is 200 /api/health
	check "backend container is healthy after the restore" backend_healthy

	say "7. Second deploy: takes a pre-deploy backup first"
	ops/server/deploy.sh "$ref" </dev/null | tee "$work/deploy2.log"
	check "deploy.sh backed up before deploying" grep -q "Backing up the database (pre-deploy)" "$work/deploy2.log"
	check "backups/pre-deploy has a dump" test -n "$(latest_dump pre-deploy)"
	check "/api/health answers after the second deploy" status_is 200 /api/health

	say "8. Containers"
	docker compose ps
	if ((failures > 0)); then
		die "$failures check(s) failed (marked FAIL above)."
	fi
	say "Stack smoke test passed"
}

main "$@"
