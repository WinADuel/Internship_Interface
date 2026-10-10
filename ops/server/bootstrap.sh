#!/usr/bin/env bash
# Sets up a new Ubuntu 24.04 server for the tracker (Phase 3 spec §4.1).
# Run it once as root on a new droplet. It is safe to run again: each step
# checks what is already done.
#
# Usage: bash bootstrap.sh [--dry-run] [--force] [TIMEZONE]
#   TIMEZONE   the server's time zone (default America/Chicago); automatic
#              security reboots happen at 04:30 in it.
#   --dry-run  print every action without changing anything.
#   --force    run on something other than Ubuntu 24.04 (untested there).
#
# What it does:
#   - creates the "deploy" user with sudo and copies root's SSH key to it;
#   - turns off SSH password login and root login (only once deploy has a key);
#   - firewall (ufw): allows 22/tcp, 80/tcp, 443/tcp and 443/udp, denies the rest;
#   - installs Docker Engine and the Compose plugin from Docker's apt repository;
#   - turns on automatic security updates, rebooting at 04:30 when one needs it;
#   - adds a 2 GB swap file;
#   - sets the time zone.
#
# Not installed: fail2ban. SSH accepts keys only, so password guessing can't
# succeed, and the login page has its own throttle.
#
# Test hooks (for backend/tests/ops only; never set them on a server):
#   TRACKER_BOOTSTRAP_EUID         pretend to run with this user id
#   TRACKER_BOOTSTRAP_OS_RELEASE   read this file instead of /etc/os-release
#   TRACKER_BOOTSTRAP_ZONEINFO     time zone files (default /usr/share/zoneinfo)
#   TRACKER_BOOTSTRAP_ROOT_KEYS    root's authorized_keys (default /root/.ssh/authorized_keys)
#   TRACKER_BOOTSTRAP_DEPLOY_KEYS  deploy's authorized_keys (default /home/deploy/.ssh/authorized_keys)
#   TRACKER_BOOTSTRAP_DOCKER_KEY   Docker's apt key (default /etc/apt/keyrings/docker.asc)
#   TRACKER_BOOTSTRAP_SWAPFILE     the swap file (default /swapfile)
#   TRACKER_BOOTSTRAP_FSTAB        the fstab (default /etc/fstab)
# They let the tests choose what this "server" already has, instead of
# reading whatever the test machine happens to have.
set -euo pipefail

DEPLOY_USER=deploy
DEPLOY_HOME=/home/deploy
DEPLOY_KEYS="${TRACKER_BOOTSTRAP_DEPLOY_KEYS:-/home/deploy/.ssh/authorized_keys}"
ROOT_KEYS="${TRACKER_BOOTSTRAP_ROOT_KEYS:-/root/.ssh/authorized_keys}"
SSHD_DROPIN=/etc/ssh/sshd_config.d/10-tracker.conf
SUDOERS_FILE=/etc/sudoers.d/90-tracker-deploy
DOCKER_KEY="${TRACKER_BOOTSTRAP_DOCKER_KEY:-/etc/apt/keyrings/docker.asc}"
DOCKER_LIST=/etc/apt/sources.list.d/docker.list
AUTO_UPGRADES=/etc/apt/apt.conf.d/20auto-upgrades
UNATTENDED_CONF=/etc/apt/apt.conf.d/52tracker-unattended
SWAPFILE="${TRACKER_BOOTSTRAP_SWAPFILE:-/swapfile}"
FSTAB="${TRACKER_BOOTSTRAP_FSTAB:-/etc/fstab}"
ZONEINFO="${TRACKER_BOOTSTRAP_ZONEINFO:-/usr/share/zoneinfo}"
SWAPPINESS_CONF=/etc/sysctl.d/60-tracker-swappiness.conf
# A new droplet often runs its first automatic updates right after boot, which
# holds apt's lock: wait up to 10 minutes for it instead of failing at once.
APT_GET=(apt-get -o DPkg::Lock::Timeout=600)

DRY_RUN=0

# apt must never stop to ask a question (needrestart included).
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a

say() {
	printf '\n==> %s\n' "$*"
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

# run <command...>: runs the command, or only prints it with --dry-run.
run() {
	if ((DRY_RUN)); then
		printf '    [dry-run]'
		printf ' %q' "$@"
		printf '\n'
		return 0
	fi
	printf '    +'
	printf ' %q' "$@"
	printf '\n'
	"$@"
}

# write_file <path> <mode> <content>: replaces the file, or only prints it with --dry-run.
write_file() {
	local path="$1" mode="$2" content="$3"
	if ((DRY_RUN)); then
		printf '    [dry-run] write %s (mode %s):\n' "$path" "$mode"
		printf '%s\n' "$content" | sed 's/^/      | /'
		return 0
	fi
	printf '    + write %s\n' "$path"
	printf '%s\n' "$content" >"$path"
	chmod "$mode" "$path"
}

# append_line <path> <line>: adds the line unless the file already has it.
append_line() {
	local path="$1" line="$2"
	if grep -qsxF -- "$line" "$path"; then
		info "$path already has: $line"
		return 0
	fi
	if ((DRY_RUN)); then
		printf '    [dry-run] append to %s: %s\n' "$path" "$line"
		return 0
	fi
	printf '    + append to %s: %s\n' "$path" "$line"
	printf '%s\n' "$line" >>"$path"
}

usage() {
	sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

main() {
	local timezone="" force=0
	while (($# > 0)); do
		case "$1" in
		-h | --help)
			usage
			return 0
			;;
		--dry-run)
			DRY_RUN=1
			;;
		--force)
			force=1
			;;
		-*)
			die "unknown option: $1" "see bash bootstrap.sh --help"
			;;
		*)
			if [[ -n "$timezone" ]]; then
				die "give one time zone (got '$timezone' and '$1')."
			fi
			timezone="$1"
			;;
		esac
		shift
	done
	timezone="${timezone:-America/Chicago}"

	# ---- Checks before changing anything --------------------------------
	if [[ "${TRACKER_BOOTSTRAP_EUID:-$EUID}" != 0 ]]; then
		die "this must run as root." "log in as root (ssh root@<server-ip>) and run it again"
	fi

	local os_release="${TRACKER_BOOTSTRAP_OS_RELEASE:-/etc/os-release}"
	local os_id os_version codename
	# os-release is a shell-style file the system ships; Docker's own install steps read it this way.
	# shellcheck source=/dev/null
	os_id="$(. "$os_release" && echo "${ID:-}")"
	# shellcheck source=/dev/null
	os_version="$(. "$os_release" && echo "${VERSION_ID:-}")"
	# shellcheck source=/dev/null
	codename="$(. "$os_release" && echo "${VERSION_CODENAME:-}")"
	if [[ "$os_id" != ubuntu || "$os_version" != 24.04 ]]; then
		if ((force)); then
			warn "this is $os_id $os_version, not Ubuntu 24.04; going on because of --force."
		else
			die "this script is written for Ubuntu 24.04, and this is '$os_id $os_version'." \
				"create the droplet with Ubuntu 24.04 (LTS), or pass --force to try anyway"
		fi
	fi
	if [[ -z "$codename" ]]; then
		die "VERSION_CODENAME is missing from $os_release, so Docker's apt repository can't be chosen."
	fi

	if [[ ! "$timezone" =~ ^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+)*$ || ! -f "$ZONEINFO/$timezone" ]]; then
		die "unknown time zone: '$timezone'." \
			"use a name like America/Chicago or Europe/London (list them with: timedatectl list-timezones)"
	fi

	if ((DRY_RUN)); then
		say "Dry run: nothing will be changed"
	fi

	# ---- Packages ---------------------------------------------------------
	say "Installing base packages"
	run "${APT_GET[@]}" update
	run "${APT_GET[@]}" install -y ca-certificates curl git ufw unattended-upgrades

	# ---- The deploy user --------------------------------------------------
	say "Setting up the $DEPLOY_USER user"
	if getent passwd "$DEPLOY_USER" >/dev/null; then
		info "user $DEPLOY_USER already exists"
	else
		run useradd --create-home --shell /bin/bash "$DEPLOY_USER"
	fi
	run usermod --append --groups sudo "$DEPLOY_USER"
	# deploy logs in with a key and has no password, so sudo can't ask for one.
	# (deploy is in the docker group too, which is root-equivalent anyway.)
	write_file "$SUDOERS_FILE" 0440 "$DEPLOY_USER ALL=(ALL) NOPASSWD:ALL"
	if ! run visudo -cf "$SUDOERS_FILE"; then
		run rm -f "$SUDOERS_FILE"
		die "the sudoers file did not validate, so it was removed."
	fi
	run install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$DEPLOY_HOME/.ssh"
	local deploy_has_key=0 key_note
	if [[ -s "$DEPLOY_KEYS" ]]; then
		deploy_has_key=1
		key_note="kept its existing SSH key(s)"
		info "$DEPLOY_KEYS already has keys; leaving it as it is"
	elif [[ -s "$ROOT_KEYS" ]]; then
		run install -m 600 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$ROOT_KEYS" "$DEPLOY_KEYS"
		deploy_has_key=1
		key_note="SSH key copied from root"
	else
		key_note="NO SSH KEY (root has none to copy)"
		warn "root has no SSH key in $ROOT_KEYS to copy, so $DEPLOY_USER can't log in yet."
	fi

	# ---- SSH --------------------------------------------------------------
	say "Turning off SSH password login and root login"
	local ssh_note
	if ((deploy_has_key)); then
		# sshd uses the first value it reads, and Ubuntu reads sshd_config.d/*.conf
		# in name order before sshd_config, so 10-... wins over cloud-init's 50-....
		write_file "$SSHD_DROPIN" 0644 "# Written by ops/server/bootstrap.sh: keys only, no root login.
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no"
		# sshd -t needs /run/sshd, which only exists once sshd has started
		# (with ssh.socket that is the first login); ssh.service makes it the same way.
		run install -d -m 0755 /run/sshd
		if ! run sshd -t; then
			run rm -f "$SSHD_DROPIN"
			die "sshd rejected the new settings, so they were removed; SSH is unchanged."
		fi
		# Ubuntu 24.04 starts sshd on demand (ssh.socket). If it isn't running,
		# the next login starts it with the new settings.
		if systemctl is-active --quiet ssh; then
			run systemctl reload ssh
		else
			info "ssh.service isn't running; the next SSH login uses the new settings"
		fi
		ssh_note="keys only, no root login"
	else
		warn "skipped: root and password login stay ON until $DEPLOY_USER has a key."
		info "Add your public key to $DEPLOY_KEYS, then run this script again."
		ssh_note="UNCHANGED (root and password login still on)"
	fi

	# ---- Firewall ---------------------------------------------------------
	say "Setting up the firewall (ufw)"
	# SSH is allowed before the firewall is switched on, so this session survives.
	# Ports Docker publishes skip ufw's rules; the stack publishes only 80 and 443.
	run ufw allow OpenSSH
	run ufw allow 80/tcp
	run ufw allow 443/tcp
	run ufw allow 443/udp
	run ufw default deny incoming
	run ufw default allow outgoing
	run ufw --force enable

	# ---- Docker -----------------------------------------------------------
	say "Installing Docker from Docker's apt repository"
	local arch
	arch="$(dpkg --print-architecture)"
	run install -m 0755 -d /etc/apt/keyrings
	if [[ -s "$DOCKER_KEY" ]]; then
		info "$DOCKER_KEY already present"
	else
		run curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o "$DOCKER_KEY"
	fi
	run chmod a+r "$DOCKER_KEY"
	write_file "$DOCKER_LIST" 0644 \
		"deb [arch=$arch signed-by=$DOCKER_KEY] https://download.docker.com/linux/ubuntu $codename stable"
	run "${APT_GET[@]}" update
	run "${APT_GET[@]}" install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
	run usermod --append --groups docker "$DEPLOY_USER"
	run systemctl enable --now docker

	# ---- Automatic security updates ----------------------------------------
	say "Turning on automatic security updates (reboot at 04:30 when needed)"
	write_file "$AUTO_UPGRADES" 0644 'APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";'
	# Every service is restart: unless-stopped, so the app comes back after a reboot.
	write_file "$UNATTENDED_CONF" 0644 '// Written by ops/server/bootstrap.sh.
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:30";'
	run systemctl enable --now unattended-upgrades

	# ---- Swap -------------------------------------------------------------
	say "Adding a 2 GB swap file"
	local swap_note
	if [[ -n "$(swapon --noheadings --show)" ]]; then
		info "swap is already on:"
		swapon --show | sed 's/^/      /'
		swap_note="already on"
		# A run that stopped right after swapon left no fstab line yet.
		if swapon --noheadings --show=NAME | grep -qxF "$SWAPFILE"; then
			append_line "$FSTAB" "$SWAPFILE none swap sw 0 0"
		fi
	else
		# Without swap the app still runs, but image builds may run out of
		# memory, so a failure here is a warning and the other steps go on.
		local swap_file_ok=1
		if [[ -e "$SWAPFILE" ]]; then
			info "$SWAPFILE exists; turning it on"
		elif ! run fallocate -l 2G "$SWAPFILE"; then
			# No half-made file left behind, so the next run makes it again.
			run rm -f "$SWAPFILE" || true
			swap_file_ok=0
		fi
		if ((swap_file_ok)) && run chmod 600 "$SWAPFILE" && run mkswap "$SWAPFILE" && run swapon "$SWAPFILE"; then
			# Turn it on again after every reboot.
			append_line "$FSTAB" "$SWAPFILE none swap sw 0 0"
			swap_note="2 GB at $SWAPFILE"
		else
			warn "could not turn on swap (see the error above); builds may run out of memory."
			swap_note="FAILED (see the warning above; run this script again to retry)"
		fi
	fi
	# Use swap only when memory is really short; the default (60) swaps eagerly.
	write_file "$SWAPPINESS_CONF" 0644 "vm.swappiness=10"
	run sysctl -p "$SWAPPINESS_CONF"

	# ---- Time zone --------------------------------------------------------
	say "Setting the time zone to $timezone"
	run timedatectl set-timezone "$timezone"

	# ---- Summary ----------------------------------------------------------
	local ip
	ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
	ip="${ip:-<server-ip>}"
	if ((DRY_RUN)); then
		say "Done (dry run: nothing was changed)"
	else
		say "Done"
	fi
	info "user:      $DEPLOY_USER, with sudo and Docker; $key_note"
	info "SSH:       $ssh_note"
	info "firewall:  on; open: 22/tcp (SSH), 80/tcp, 443/tcp, 443/udp"
	info "Docker:    Engine + Compose plugin from download.docker.com"
	info "updates:   security updates install automatically; reboot at 04:30 if needed"
	info "swap:      $swap_note (swappiness 10)"
	info "time zone: $timezone"
	printf '\nNext:\n'
	if ((deploy_has_key)); then
		info "1. Keep this root window open. In a NEW terminal on your Mac, check you can log in:"
		info "     ssh $DEPLOY_USER@$ip"
		info "2. As $DEPLOY_USER, add the GitHub deploy key and clone the repo"
		info "   (docs/deploy/server-setup.md, step 5)."
	else
		info "1. Put your public SSH key in $DEPLOY_KEYS"
		info "   (owner $DEPLOY_USER, mode 600), then run this script again to turn off password login."
	fi
}

main "$@"
