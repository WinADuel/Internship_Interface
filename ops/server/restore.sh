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

	# Before the cd: a relative path is from where the script was started.
	resolve_backup_file "$file" "$repo_root"

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

	check_backup_file "$file"

	if ((yes)); then
		info "--yes: not asking for confirmation"
	else
		confirm_restore "$database" "$file"
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

	stop_app

	if ! restore_backup_file "$file"; then
		say "Starting the app again on the old data"
		docker compose up -d || true
		die "the restore failed (see the error above); the database was not changed."
	fi

	# From here the data is replaced: whatever goes wrong, the way back is printed.
	say "Starting the app"
	if ! docker compose up -d; then
		print_undo "$safety_path"
		die "docker compose up failed (see the error above); the database holds the data from $file."
	fi
	if ! wait_for_health "$domain"; then
		print_undo "$safety_path"
		exit 1
	fi

	say "Restored"
	info "the database now holds the data from $file"
	print_undo "$safety_path"
}

# print_undo <safety backup path or "">
print_undo() {
	local safety_path="$1"
	if [[ -n "$safety_path" ]]; then
		info "to undo, restore the safety backup taken just before:"
		info "  ops/server/restore.sh $safety_path"
	fi
}

main "$@"
