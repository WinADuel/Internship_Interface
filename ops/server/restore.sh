#!/usr/bin/env bash
# Replaces the tracker's whole database with a backup (Phase 3 spec §4.4).
# Run it as the deploy user, from any directory.
#
# Usage: ops/server/restore.sh [--yes] [--no-safety-backup] FILE
#   FILE  a dump the server made: backups/<nightly|pre-deploy|manual>/tracker-....dump,
#         or the /backups/... path deploy.sh printed;
#         or an encrypted copy (.dump.enc) downloaded from Google Drive, anywhere
#         on the server (BACKUP_ENCRYPTION_KEY in .env must be the one that made it).
#   --yes               don't ask to type the database name first.
#   --no-safety-backup  skip the backup of the current data taken just before
#                       the restore. Only for when that backup itself fails.
#
# Steps: check the file is readable, ask for confirmation, back up the current
# data, stop the app (the database keeps running), restore, start everything,
# then wait for /api/health. The restore runs in one transaction: if it fails,
# the database is left as it was and the app starts again on the old data.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
# shellcheck source=lib.sh
source "$script_dir/lib.sh"

# Every service that uses the database: stopped during the restore (db keeps running).
APP_SERVICES=(backend sheet-sync job-scan db-backup caddy)

usage() {
	sed -n '2,17p' "$script_dir/restore.sh" | sed 's/^# \{0,1\}//'
}

main() {
	local file="" yes=0 safety_backup=1
	while (($# > 0)); do
		case "$1" in
		-h | --help)
			usage
			return 0
			;;
		--yes)
			yes=1
			;;
		--no-safety-backup)
			safety_backup=0
			;;
		-*)
			die "unknown option: $1" "see ops/server/restore.sh --help"
			;;
		*)
			if [[ -n "$file" ]]; then
				die "give one backup file (got '$file' and '$1')."
			fi
			file="$1"
			;;
		esac
		shift
	done
	if [[ -z "$file" ]]; then
		die "which backup? Give a file." "see ops/server/restore.sh --help"
	fi

	# Where the db-backup container will find the file. Dumps the server made
	# stay where they are (./backups is mounted at /backups, and is readable
	# only by root on the host); any other file is mounted read-only.
	local path container_path mount=()
	case "$file" in
	*.dump | *.dump.enc) ;;
	*) die "'$file' is not a backup: the name must end in .dump or .dump.enc." ;;
	esac
	path="$(realpath --no-symlinks --canonicalize-missing -- "$file")"
	if [[ "$path" == /backups/* ]]; then
		container_path="$path"
	elif [[ "$path" == "$repo_root/backups/"* ]]; then
		container_path="/backups/${path#"$repo_root/backups/"}"
	else
		if [[ ! -f "$path" || ! -r "$path" ]]; then
			die "cannot read $path." "check the path (ls -l '$path')"
		fi
		if [[ "$path" == *:* ]]; then
			die "Docker can't mount a path with ':' in it: $path" "move or rename the file"
		fi
		container_path="/restore/backup.dump"
		if [[ "$path" == *.enc ]]; then
			container_path="/restore/backup.dump.enc"
		fi
		mount=(-v "$path:$container_path:ro")
	fi

	cd "$repo_root"

	say "Checking .env"
	check_env_file
	local domain database
	domain="$(env_value DOMAIN)"
	check_domain "$domain"
	database="$(env_value POSTGRES_DB)"
	if [[ -z "$database" ]]; then
		die "POSTGRES_DB is not set in .env."
	fi

	say "Checking Docker"
	require_docker

	say "Checking the backup can be read"
	if ! docker compose run --rm -T "${mount[@]}" db-backup \
		python -m app.cli restore "$container_path" --check </dev/null; then
		die "$file can't be restored (see the error above); nothing was changed."
	fi

	if ((yes)); then
		info "--yes: not asking for confirmation"
	else
		printf '\nThis REPLACES ALL DATA in the database "%s" with:\n  %s\n' "$database" "$file"
		printf 'Type the database name (%s) to continue: ' "$database"
		local answer=""
		read -r answer || true
		if [[ "$answer" != "$database" ]]; then
			die "not confirmed; nothing was changed."
		fi
	fi

	local safety_path=""
	if ((safety_backup)); then
		say "Backing up the current data first (safety backup)"
		if ! safety_path="$(take_backup manual)"; then
			die "the safety backup failed; nothing was changed." \
				"read the error above. Only if the current data doesn't matter, re-run with --no-safety-backup"
		fi
	else
		warn "--no-safety-backup: the current data is not backed up first."
	fi

	say "Stopping the app (the database keeps running)"
	docker compose stop "${APP_SERVICES[@]}"

	say "Restoring $file"
	if ! docker compose run --rm -T "${mount[@]}" db-backup \
		python -m app.cli restore "$container_path" --yes </dev/null; then
		say "Starting the app again on the old data"
		docker compose up -d || true
		die "the restore failed (see the error above); the database was not changed."
	fi

	say "Starting the app"
	docker compose up -d
	if ! wait_for_health "$domain"; then
		exit 1
	fi

	say "Restored"
	info "the database now holds the data from $file"
	if [[ -n "$safety_path" ]]; then
		info "to undo, restore the safety backup taken just before:"
		info "  ops/server/restore.sh $safety_path"
	fi
}

main "$@"
