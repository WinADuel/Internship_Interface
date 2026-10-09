#!/usr/bin/env bash
# Deploys the tracker on the server (Phase 3 spec §4.2). Run it as the deploy
# user; it works from the repo folder whatever directory you start it in.
#
# Usage: ops/server/deploy.sh [--skip-backup] [--restore DUMP [--yes]] [REF]
#   REF            what to deploy: a commit, a tag or origin/<branch>
#                  (default origin/main).
#   --restore DUMP also replace the whole database with DUMP (as restore.sh
#                  does), between the checkout and the start: a rollback in one
#                  command. Every deploy prints the exact rollback command at
#                  the end: --restore with its pre-deploy backup and the
#                  previous commit.
#   --yes          with --restore: don't ask to type the database name first.
#   --skip-backup  deploy without the pre-deploy database backup.
#                  DANGEROUS: if the deploy breaks the data, there is no copy
#                  from just before it. Only for when the backup itself is broken.
#
# Steps: check .env and Docker, fetch, back up the database, check out REF,
# (with --restore: stop the app, restore DUMP,) rebuild and start the stack,
# then wait up to 2 minutes for /api/health.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
# shellcheck source=lib.sh
source "$script_dir/lib.sh"

usage() {
	sed -n '2,21p' "$script_dir/deploy.sh" | sed 's/^# \{0,1\}//'
}

# Everything runs inside main, which bash reads in full before running it, so
# the checkout replacing this file on disk can't change what runs mid-deploy.
main() {
	local ref="" skip_backup=0 restore_file="" yes=0
	while (($# > 0)); do
		case "$1" in
		-h | --help)
			usage
			return 0
			;;
		--skip-backup)
			skip_backup=1
			;;
		--restore)
			if (($# < 2)) || [[ -z "$2" ]]; then
				die "--restore needs the backup to restore." "see ops/server/deploy.sh --help"
			fi
			restore_file="$2"
			shift
			;;
		--yes)
			yes=1
			;;
		-*)
			die "unknown option: $1" "see ops/server/deploy.sh --help"
			;;
		*)
			if [[ -n "$ref" ]]; then
				die "only one REF can be deployed at a time (got '$ref' and '$1')."
			fi
			ref="$1"
			;;
		esac
		shift
	done
	ref="${ref:-origin/main}"
	if ((yes)) && [[ -z "$restore_file" ]]; then
		die "--yes only goes with --restore." "see ops/server/deploy.sh --help"
	fi
	if [[ -n "$restore_file" ]]; then
		# Before the cd: a relative path is from where the script was started.
		resolve_backup_file "$restore_file" "$repo_root"
	fi

	cd "$repo_root"

	say "Checking .env"
	check_env_file
	local domain database
	domain="$(env_value DOMAIN)"
	check_domain "$domain"
	info "DOMAIN=$domain"
	database="$(env_value POSTGRES_DB)"
	if [[ -n "$restore_file" && -z "$database" ]]; then
		die "POSTGRES_DB is not set in .env."
	fi

	say "Checking Docker"
	require_docker

	say "Checking for local changes"
	if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
		git status --short --untracked-files=no >&2
		die "files in $repo_root were changed on the server; deploying would mix them with the new code." \
			"undo the changes with: git checkout -- <file>   (keep a copy first if you need them)"
	fi

	say "Fetching from GitHub"
	if ! git fetch --tags origin; then
		die "git fetch failed." \
			"check the deploy key works: ssh -T git@github.com (see docs/deploy/server-setup.md)"
	fi

	local previous new
	previous="$(git rev-parse HEAD)"
	if [[ "$ref" == -* ]] || ! new="$(git rev-parse --verify --quiet "${ref}^{commit}")"; then
		die "'$ref' is not a commit, tag or branch in this repo." \
			"use a commit from 'git log --oneline origin/main', a tag, or origin/main"
	fi
	if git show-ref --verify --quiet "refs/heads/$ref"; then
		warn "'$ref' is a local branch, which this script never updates; for the latest code use origin/$ref."
	fi
	info "deploying $ref: $(git log -1 --format='%h %s' "$new")"
	info "currently on: $(git log -1 --format='%h %s' "$previous")"

	if [[ -n "$restore_file" ]]; then
		if ! db_is_running && ! db_volume_exists; then
			die "there is no database here yet to restore into; nothing was changed." \
				"deploy first (ops/server/deploy.sh), then restore with ops/server/restore.sh $restore_file"
		fi
		check_backup_file "$restore_file"
		if ((yes)); then
			info "--yes: not asking for confirmation"
		else
			confirm_restore "$database" "$restore_file"
		fi
	fi

	local backup_path=""
	if ((skip_backup)); then
		warn "--skip-backup: deploying without a pre-deploy backup."
	elif db_is_running || db_volume_exists; then
		say "Backing up the database (pre-deploy)"
		if ! db_is_running; then
			info "the database isn't running; starting it for the backup"
			if ! docker compose up -d --wait db; then
				die "could not start the database for the pre-deploy backup; nothing was deployed." \
					"see docker compose logs db --tail 50"
			fi
		fi
		if ! backup_path="$(take_backup pre-deploy)"; then
			die "the pre-deploy backup failed, so nothing was deployed." \
				"read the error above and docker compose logs db --tail 50; then run this again"
		fi
	else
		info "first deploy: no database yet, skipping backup"
	fi

	say "Checking out ${new:0:12}"
	git checkout --quiet --detach "$new"

	if [[ -n "$restore_file" ]]; then
		# Built while the app still runs: a failed build leaves it running, data untouched.
		say "Building the app (the database is restored after this)"
		if ! docker compose build; then
			print_code_back "$previous" "$new"
			die "docker compose build failed (see the error above); the database was not changed."
		fi
		if ! stop_app; then
			print_code_back "$previous" "$new"
			die "docker compose stop failed (see the error above); the database was not changed."
		fi
		if ! restore_backup_file "$restore_file"; then
			# The data is as it was: start the containers that were running before.
			say "Starting the app again on the old data"
			docker compose start "${APP_SERVICES[@]}" || true
			print_code_back "$previous" "$new"
			die "the restore failed (see the error above); the database was not changed."
		fi
		info "the database now holds the data from $restore_file"
	fi

	say "Building and starting the app (the first build takes several minutes)"
	if ! docker compose up -d --build --remove-orphans; then
		print_rollback "$previous" "$backup_path"
		die "docker compose up failed (see the error above)."
	fi

	if ! wait_for_health "$domain"; then
		print_rollback "$previous" "$backup_path"
		exit 1
	fi

	say "Deployed"
	info "previous commit: $(git log -1 --format='%h %s' "$previous")"
	info "now running:     $(git log -1 --format='%h %s' "$new")"
	info "https://$domain"
	print_rollback "$previous" "$backup_path"
}

# print_code_back <previous commit> <new commit>: after a --restore that
# changed nothing in the database, the way back for the code.
print_code_back() {
	printf '\n'
	info "The database was not changed, but the code is now ${2:0:12}. To put the code back:"
	info "  ops/server/deploy.sh $1"
}

# print_rollback <previous commit> <pre-deploy dump path or "">: the one
# command that undoes this deploy, code and data together.
print_rollback() {
	local previous="$1" backup_path="$2"
	printf '\n'
	if [[ -n "$backup_path" ]]; then
		info "To undo this deploy (the previous code, and the database as it was just before this deploy):"
		info "  ops/server/deploy.sh --restore $backup_path $previous"
		info "Anything changed in the app since this deploy is lost by that."
		info "Shortcut, ONLY if this deploy did not change the database (no migration; if unsure, use"
		info "the command above): the previous code, keeping the data as it is now:"
		info "  ops/server/deploy.sh $previous"
	else
		info "To go back to the previous code:"
		info "  ops/server/deploy.sh $previous"
		info "This deploy took no pre-deploy backup (first deploy, or --skip-backup), so there is no"
		info "copy of the database from just before it to go back to."
	fi
}

main "$@"
