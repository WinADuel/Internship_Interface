#!/usr/bin/env bash
# Deploys the tracker on the server (Phase 3 spec §4.2). Run it as the deploy
# user; it works from the repo folder whatever directory you start it in.
#
# Usage: ops/server/deploy.sh [--skip-backup] [REF]
#   REF            what to deploy: a commit, a tag or origin/<branch>
#                  (default origin/main). Rolling back is deploying the
#                  previous commit, which every deploy prints at the end.
#   --skip-backup  deploy without the pre-deploy database backup.
#                  DANGEROUS: if the deploy breaks the data, there is no copy
#                  from just before it. Only for when the backup itself is broken.
#
# Steps: check .env and Docker, fetch, back up the database, check out REF,
# rebuild and start the stack, then wait up to 2 minutes for /api/health.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
# shellcheck source=lib.sh
source "$script_dir/lib.sh"

usage() {
	sed -n '2,13p' "$script_dir/deploy.sh" | sed 's/^# \{0,1\}//'
}

# Everything runs inside main, which bash reads in full before running it, so
# the checkout replacing this file on disk can't change what runs mid-deploy.
main() {
	local ref="" skip_backup=0
	while (($# > 0)); do
		case "$1" in
		-h | --help)
			usage
			return 0
			;;
		--skip-backup)
			skip_backup=1
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

	cd "$repo_root"

	say "Checking .env"
	check_env_file
	local domain
	domain="$(env_value DOMAIN)"
	check_domain "$domain"
	info "DOMAIN=$domain"

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

# print_rollback <previous commit> <pre-deploy dump path or "">
print_rollback() {
	local previous="$1" backup_path="$2"
	printf '\n'
	info "To roll back to the previous version:"
	info "  ops/server/deploy.sh $previous"
	if [[ -n "$backup_path" ]]; then
		info "If this deploy changed the database (a migration), restore its pre-deploy backup right"
		info "after that (until then the old version may not start and show as unhealthy):"
		info "  ops/server/restore.sh $backup_path"
	fi
}

main "$@"
