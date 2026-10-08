"""ops/server/bootstrap.sh (Phase 3 spec §4.1, §6). It can't really run
outside a fresh Ubuntu 24.04 VM, so these check the refusals and that
--dry-run prints every step and changes nothing. Every command it could run
is a logging fake (conftest.py), so even a dry-run bug could not touch this
machine, and the files it checks (SSH keys, swap file, fstab, ...) are a
FakeHost under tmp_path, so the result never depends on this machine."""

from pathlib import Path

import pytest

from tests.ops.conftest import SCRIPTS

BOOTSTRAP = SCRIPTS / "bootstrap.sh"
# Read-only queries the dry run is allowed to make.
QUERIES = {
    "getent passwd deploy",
    "swapon --noheadings --show",
    "dpkg --print-architecture",
    "systemctl is-active --quiet ssh",
    "hostname -I",
}
# Files a real run writes; a dry run must leave each one as it was.
TOUCHED = [
    "/etc/ssh/sshd_config.d/10-tracker.conf",
    "/etc/sudoers.d/90-tracker-deploy",
    "/etc/apt/keyrings/docker.asc",
    "/etc/apt/sources.list.d/docker.list",
    "/etc/apt/apt.conf.d/20auto-upgrades",
    "/etc/apt/apt.conf.d/52tracker-unattended",
    "/etc/sysctl.d/60-tracker-swappiness.conf",
    "/swapfile",
    "/home/deploy",
]


def _snapshot():
    def state(path):
        p = Path(path)
        try:
            return (p.exists(), p.read_bytes() if p.is_file() and p.stat().st_size < 1_000_000 else None)
        except PermissionError:  # e.g. /etc/sudoers.d when the tests don't run as root
            return "unreadable"

    return {path: state(path) for path in TOUCHED + ["/etc/fstab"]}


def _bootstrap(fakes, *args, **env):
    return fakes.run(["bash", BOOTSTRAP, *args], cwd=fakes.home, **env)


def test_dry_run_prints_every_step_and_changes_nothing(bootstrap_fakes, fake_host):
    before = _snapshot()
    swapfile, fstab, docker_key = fake_host.swapfile, fake_host.fstab, fake_host.docker_key
    result = _bootstrap(bootstrap_fakes, "--dry-run")
    assert result.returncode == 0, result.stderr
    out = result.stdout

    for step in [
        "==> Dry run: nothing will be changed",
        "==> Installing base packages",
        "==> Setting up the deploy user",
        "==> Turning off SSH password login and root login",
        "==> Setting up the firewall (ufw)",
        "==> Installing Docker from Docker's apt repository",
        "==> Turning on automatic security updates (reboot at 04:30 when needed)",
        "==> Adding a 2 GB swap file",
        "==> Setting the time zone to America/Chicago",
        "==> Done (dry run: nothing was changed)",
    ]:
        assert step in out
    for action in [
        "[dry-run] apt-get install -y ca-certificates curl git ufw unattended-upgrades",
        "[dry-run] useradd --create-home --shell /bin/bash deploy",
        "[dry-run] usermod --append --groups sudo deploy",
        "[dry-run] write /etc/sudoers.d/90-tracker-deploy (mode 0440):",
        "| deploy ALL=(ALL) NOPASSWD:ALL",
        "[dry-run] visudo -cf /etc/sudoers.d/90-tracker-deploy",
        "[dry-run] ufw allow OpenSSH",
        "[dry-run] ufw allow 80/tcp",
        "[dry-run] ufw allow 443/tcp",
        "[dry-run] ufw allow 443/udp",
        "[dry-run] ufw default deny incoming",
        "[dry-run] ufw --force enable",
        f"[dry-run] curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o {docker_key}",
        f"| deb [arch=amd64 signed-by={docker_key}] https://download.docker.com/linux/ubuntu noble stable",
        "[dry-run] apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin",
        "[dry-run] usermod --append --groups docker deploy",
        '| APT::Periodic::Unattended-Upgrade "1";',
        '| Unattended-Upgrade::Automatic-Reboot "true";',
        '| Unattended-Upgrade::Automatic-Reboot-Time "04:30";',
        f"[dry-run] fallocate -l 2G {swapfile}",
        f"[dry-run] chmod 600 {swapfile}",
        f"[dry-run] mkswap {swapfile}",
        f"[dry-run] swapon {swapfile}",
        f"[dry-run] append to {fstab}: {swapfile} none swap sw 0 0",
        "| vm.swappiness=10",
        "[dry-run] timedatectl set-timezone America/Chicago",
    ]:
        assert action in out, action
    # SSH is allowed before the firewall goes on, so the root session survives.
    assert out.index("ufw allow OpenSSH") < out.index("ufw --force enable")
    # Root's key (a new droplet's) goes to deploy before SSH is locked down.
    assert f"[dry-run] install -m 600 -o deploy -g deploy {fake_host.root_keys} {fake_host.deploy_keys}" in out
    assert "SSH key copied from root" in out
    assert "ssh deploy@203.0.113.10" in out
    assert "| PasswordAuthentication no" in out
    assert "| KbdInteractiveAuthentication no" in out
    assert out.index("| PermitRootLogin no") < out.index("[dry-run] sshd -t")
    assert out.index("[dry-run] sshd -t") < out.index("[dry-run] systemctl reload ssh")
    assert "docs/deploy/server-setup.md, step 5" in out

    assert set(bootstrap_fakes.commands()) <= QUERIES
    assert _snapshot() == before


def test_without_any_ssh_key_root_and_password_login_stay_on(bootstrap_fakes, fake_host):
    fake_host.root_keys.unlink()
    result = _bootstrap(bootstrap_fakes, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "root and password login stay ON" in result.stderr
    assert "NO SSH KEY (root has none to copy)" in result.stdout
    assert "10-tracker.conf" not in result.stdout
    assert "sshd -t" not in result.stdout
    assert "then run this script again to turn off password login" in result.stdout


def test_existing_deploy_keys_are_kept(bootstrap_fakes, fake_host):
    fake_host.deploy_keys.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOtherFakeKey laptop\n")
    result = _bootstrap(bootstrap_fakes, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "already has keys; leaving it as it is" in result.stdout
    assert "kept its existing SSH key(s)" in result.stdout
    assert f"{fake_host.root_keys} {fake_host.deploy_keys}" not in result.stdout
    assert "| PermitRootLogin no" in result.stdout


def test_existing_docker_key_is_not_downloaded_again(bootstrap_fakes, fake_host):
    fake_host.docker_key.write_text("-----BEGIN PGP PUBLIC KEY BLOCK-----\n")
    result = _bootstrap(bootstrap_fakes, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert f"{fake_host.docker_key} already present" in result.stdout
    assert "download.docker.com/linux/ubuntu/gpg" not in result.stdout


def test_existing_swapfile_that_is_off_is_turned_on(bootstrap_fakes, fake_host):
    # As on a GitHub runner: /swapfile and its fstab line exist, swap is off.
    swap_line = f"{fake_host.swapfile} none swap sw 0 0"
    fake_host.swapfile.write_bytes(b"")
    fake_host.fstab.write_text(f"LABEL=root / ext4 defaults 0 1\n{swap_line}\n")
    result = _bootstrap(bootstrap_fakes, "--dry-run")
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert f"{fake_host.swapfile} exists; turning it on" in out
    assert "fallocate" not in out
    assert f"[dry-run] mkswap {fake_host.swapfile}" in out
    assert f"[dry-run] swapon {fake_host.swapfile}" in out
    assert f"{fake_host.fstab} already has: {swap_line}" in out
    assert "append to" not in out


def test_swap_on_from_our_swapfile_without_fstab_line_adds_it(bootstrap_fakes, fake_host):
    # A run that stopped right after swapon: swap is on, fstab has no line yet.
    result = _bootstrap(
        bootstrap_fakes, "--dry-run", FAKE_SWAP=str(fake_host.swapfile)
    )
    assert result.returncode == 0, result.stderr
    assert "swap is already on" in result.stdout
    assert f"[dry-run] append to {fake_host.fstab}: {fake_host.swapfile} none swap sw 0 0" in result.stdout
    assert "mkswap" not in result.stdout


def test_existing_swap_is_left_alone(bootstrap_fakes):
    result = _bootstrap(bootstrap_fakes, "--dry-run", FAKE_SWAP="/dev/vda2 partition 1G 0B -2")
    assert result.returncode == 0, result.stderr
    assert "swap is already on" in result.stdout
    assert "mkswap" not in result.stdout
    assert "fstab" not in result.stdout


def test_an_existing_deploy_user_is_not_created_again(bootstrap_fakes):
    result = _bootstrap(bootstrap_fakes, "--dry-run", FAKE_GETENT_EXIT="0")
    assert result.returncode == 0, result.stderr
    assert "user deploy already exists" in result.stdout
    assert "useradd" not in result.stdout


def test_timezone_argument(bootstrap_fakes):
    result = _bootstrap(bootstrap_fakes, "--dry-run", "Europe/London")
    assert result.returncode == 0, result.stderr
    assert "[dry-run] timedatectl set-timezone Europe/London" in result.stdout


@pytest.mark.parametrize("zone", ["Mars/Olympus_Mons", "../../etc/passwd", "America/Chicago;reboot", "/etc"])
def test_unknown_timezone_is_refused(bootstrap_fakes, zone):
    result = _bootstrap(bootstrap_fakes, "--dry-run", zone)
    assert result.returncode == 1
    assert f"unknown time zone: '{zone}'" in result.stderr
    assert bootstrap_fakes.calls() == []


def test_only_one_timezone(bootstrap_fakes):
    result = _bootstrap(bootstrap_fakes, "--dry-run", "America/Chicago", "Europe/London")
    assert result.returncode == 1
    assert "give one time zone" in result.stderr


def test_refuses_to_run_as_a_normal_user(bootstrap_fakes):
    result = _bootstrap(bootstrap_fakes, TRACKER_BOOTSTRAP_EUID="1000")
    assert result.returncode == 1
    assert "this must run as root" in result.stderr
    assert "ssh root@" in result.stderr
    assert bootstrap_fakes.calls() == []


def test_refuses_other_systems_unless_forced(bootstrap_fakes, tmp_path):
    debian = tmp_path / "debian-os-release"
    debian.write_text('ID=debian\nVERSION_ID="12"\nVERSION_CODENAME=bookworm\n')
    result = _bootstrap(bootstrap_fakes, "--dry-run", TRACKER_BOOTSTRAP_OS_RELEASE=str(debian))
    assert result.returncode == 1
    assert "written for Ubuntu 24.04, and this is 'debian 12'" in result.stderr
    assert "--force" in result.stderr
    assert bootstrap_fakes.calls() == []

    forced = _bootstrap(bootstrap_fakes, "--dry-run", "--force", TRACKER_BOOTSTRAP_OS_RELEASE=str(debian))
    assert forced.returncode == 0, forced.stderr
    assert "going on because of --force" in forced.stderr
    assert "linux/ubuntu bookworm stable" in forced.stdout


def test_older_ubuntu_is_refused(bootstrap_fakes, tmp_path):
    jammy = tmp_path / "jammy"
    jammy.write_text('ID=ubuntu\nVERSION_ID="22.04"\nVERSION_CODENAME=jammy\n')
    result = _bootstrap(bootstrap_fakes, "--dry-run", TRACKER_BOOTSTRAP_OS_RELEASE=str(jammy))
    assert result.returncode == 1
    assert "'ubuntu 22.04'" in result.stderr


def test_unknown_option_is_refused(bootstrap_fakes):
    result = _bootstrap(bootstrap_fakes, "--dryrun")
    assert result.returncode == 1
    assert "unknown option: --dryrun" in result.stderr
    assert bootstrap_fakes.calls() == []


def test_help(bootstrap_fakes):
    result = _bootstrap(bootstrap_fakes, "--help")
    assert result.returncode == 0
    assert "Usage: bash bootstrap.sh [--dry-run] [--force] [TIMEZONE]" in result.stdout
    assert bootstrap_fakes.calls() == []
