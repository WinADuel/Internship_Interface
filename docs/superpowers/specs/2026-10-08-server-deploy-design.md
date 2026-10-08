# Phase 3 Design: Server Deploy

**Date:** 2026-10-08
**Status:** Draft, awaiting owner approval
**Builds on:** the Phase 1 design (`2026-10-05-internship-tracker-design.md`, §1 success criteria, §11 deployment, §11a CI/CD), Phase 1b (§13.5 Claude job, §13.7 backup sheet) and Phase 2 (`2026-10-08-job-discovery-design.md`).

## 1. Goal

Put the tracker on the public internet so the owner reaches **one** tracker from phone, MacBook and Windows PC, anywhere. This meets the Phase 1 success criterion that has been open since Phase 1 ("log in from phone, MacBook, or Windows PC over the public internet and see the same data").

A public HTTPS address also unlocks three things that were waiting on it:
- the daily Claude research job (§13.5), which runs in the cloud and must reach the app;
- publishing the Google OAuth app, so Google tokens stop expiring every 7 days (Google requires a public homepage and privacy policy);
- Claude ranking of the Discover Inbox (a later phase).

The Mac and PC installs stay as local test copies. The server starts with a fresh, empty database.

## 2. Owner decisions (2026-10-08)

| Question | Choice |
|---|---|
| Phase 3 scope | Server deploy (before Gmail sync and interview prep) |
| Hosting | DigitalOcean droplet |
| Domain | Buy a `.com` |

## 3. Defaults chosen (owner can override)

- **Droplet:** Basic, Regular SSD, 1 vCPU / 1 GB RAM / 25 GB disk ($6/month), Ubuntu 24.04 LTS, region New York (closest to the `America/Chicago` timezone in `.env`). A 2 GB swap file covers image builds and the 13 MB list scan (155 MB peak, measured in Phase 2). If builds still run out of memory, resize to 2 GB ($12/month) from the DigitalOcean panel; no reinstall is needed.
- **Registrar:** Porkbun (about $11/year for `.com`, simple DNS, free WHOIS privacy). Cloudflare Registrar also works; if used, the DNS record must be "DNS only" (grey cloud) so Caddy can get its certificate directly.
- **Address:** the bare domain (for example `https://internhelper.com`). A subdomain such as `tracker.` works the same way.
- **Images are built on the server** (`docker compose up -d --build`), exactly as on the Mac. Pre-built images in a registry would add a moving part for no benefit at this size.
- **Deploys are manual**, with one command. Automatic deploy-on-merge stays deferred, as §11a decided: it gets added after a few manual deploys have gone smoothly.
- **Student credit:** if the owner qualifies, the GitHub Student Developer Pack's $200 DigitalOcean credit is applied first.

## 4. What gets built

### 4.1 Server bootstrap: `ops/server/bootstrap.sh`

A single script the owner runs once as root on a new droplet. It is safe to re-run, and it does the following:
- creates a `deploy` user with sudo, and copies root's authorized SSH key to it;
- turns off SSH password login and root login;
- enables the `ufw` firewall: allow 22, 80, 443 (TCP) and 443/udp (HTTP/3), deny the rest;
- installs Docker Engine and the Compose plugin from Docker's official apt repository, and adds `deploy` to the `docker` group;
- turns on `unattended-upgrades` for security patches, with an automatic reboot at 04:30 local time when a patch needs one (every service is `restart: unless-stopped`, so the app comes back by itself);
- adds a 2 GB swap file;
- sets the server timezone from an argument (default `America/Chicago`).

### 4.2 Deploy and rollback: `ops/server/deploy.sh`

The script runs on the server from the repo folder:
1. Refuses to run if `.env` is missing or still contains `change-me` values.
2. Takes a pre-deploy database backup (§4.4).
3. Runs `git fetch` and checks out `origin/main`, or a commit or tag given as an argument (that is the rollback path).
4. Runs `docker compose up -d --build`, then waits up to 2 minutes for `https://$DOMAIN/api/health`.
5. Prints the deployed commit and the result.

The server gets the private repo with a read-only GitHub **deploy key** (an SSH key the owner adds under the repo's Settings → Deploy keys). A deploy key can read only this repo and cannot push.

**Rollback:** `deploy.sh <previous-commit>`. If the bad deploy ran a migration, the rollback restores the pre-deploy backup (`restore.sh`, §4.4), because Alembic downgrades aren't guaranteed to be lossless.

### 4.3 Production hardening of the Compose stack and Caddy

- **Log rotation** on every service (`json-file`, 10 MB × 3 files), so logs can't fill the 25 GB disk.
- **Backend healthcheck** on `/api/health`. Caddy starts after the backend is healthy, and `docker compose ps` shows the state.
- **Security headers** in the Caddyfile, added to the existing HSTS, `X-Frame-Options`, `nosniff` and `Referrer-Policy`:
  - a Content-Security-Policy: `default-src 'self'`; scripts from `'self'` only; `style-src 'self' 'unsafe-inline'`, because Svelte transitions inject styles; `img-src 'self' data:`; `frame-ancestors 'none'`; `base-uri 'self'`; `form-action 'self'`;
  - `Permissions-Policy`, turning off camera, microphone and geolocation.
  The production build is checked page by page for CSP violations.
- **Real client IP for login throttling:** Caddy already forwards `X-Forwarded-For`. The login throttle (Phase 1) is global, not per-IP, so nothing needs to change. This is recorded so nobody adds a per-IP limit that trusts a spoofable header.
- The same `docker-compose.yml` still runs locally with `DOMAIN=localhost`. Nothing about the Mac or PC setup changes.

### 4.4 Backups: a `db-backup` service, with an off-site copy in Google Drive

- A new Compose service runs `pg_dump --format=custom` nightly at 02:30 local time, and on demand from `deploy.sh`.
- Dumps go to `./backups/` on the server. It keeps 14 nightly dumps plus the 5 most recent pre-deploy dumps.
- **Off-site copy:** each nightly dump is encrypted, then uploaded to a Drive folder "Internship Tracker Backups" through the Google connection the app already has.
  - The `drive.file` permission covers files the app creates, so no new Google permission is needed.
  - Encryption uses Fernet with a new `BACKUP_ENCRYPTION_KEY` in `.env`, so Google never sees plaintext data.
  - Drive keeps the 30 most recent copies.
  - If Google isn't connected, the local dump still happens, and the error shows in Settings, the same way sheet-sync errors do.
- **Settings → Backups** shows the last successful local backup and the last off-site upload, plus a **Back up now** button.
- **`ops/server/restore.sh <dump>`** restores a dump into the stack, decrypting it first when given a Drive copy. The restore is tested in CI against a real Postgres: dump, wipe, restore, compare.
- **Optional:** DigitalOcean's weekly droplet backups ($1.20/month) as a second, whole-machine safety net. It's documented as optional, not required.

The owner keeps `.env` (which holds `TOKEN_ENCRYPTION_KEY` and `BACKUP_ENCRYPTION_KEY`) in a password manager. Without it, neither the database's encrypted fields nor the Drive backups can be read. The README's "Moving to a new server" section already covers this for `TOKEN_ENCRYPTION_KEY`.

### 4.5 Public homepage and privacy policy

Google needs both URLs before the OAuth app can be published.
- `https://<domain>/about.html`: a short static page saying what the app is (a personal, single-user internship tracker), with a link to the privacy policy and a "Log in" link.
- `https://<domain>/privacy.html`: what data the app stores, which Google permissions it uses and why (`drive.readonly` to show essays, `drive.file` for the backup sheet and backup files), that nothing is shared or sold, how to revoke access, and a contact email.
- The contact email comes from a new `CONTACT_EMAIL` value in `.env`. Caddy fills it in when it serves the page, so no personal address is committed to the repo.
- Both are plain HTML served by Caddy outside the app. They load no scripts and need no login.

### 4.6 Phone: add to home screen

- A web app manifest, app icons and an `apple-touch-icon`, so "Add to Home Screen" on an iPhone opens the tracker full-screen with its own icon.
- No offline mode and no service worker; the tracker needs the server anyway.
- The main pages are checked at phone width (390 px), and anything that overflows is fixed.

### 4.7 Guides for the owner

`docs/deploy/server-setup.md` is a step-by-step guide written for someone doing this for the first time, with every command and every website click:
1. Create the DigitalOcean account (Student Pack credit first) and buy the domain.
2. Make an SSH key on the Mac (`ssh-keygen`), create the droplet with it, and run `bootstrap.sh`.
3. Point the domain's A record at the droplet, and check it with `dig`.
4. Add the deploy key, clone, and fill in `.env` on the server (new secrets, generated with the Mac commands from the local setup).
5. Run `deploy.sh`, then `create-user`, then log in from the phone, Mac and PC.
6. Google Cloud: add the new redirect URI and authorized domain, add the homepage and privacy URLs, then **Publish app**. Reconnect Google once.
7. Claude daily job: create a Claude token in Settings and schedule the routine (§13.5 appendix) with the real `APP_BASE_URL`.
8. A free uptime check (UptimeRobot) on `/api/health` that emails the owner if the site goes down.
9. Day-to-day: how to deploy, roll back, restore, and read logs.

The README's Deploying section gets a short summary that points to this guide.

## 5. Security notes

- The only open ports are 22, 80 and 443. Postgres has no published port (unchanged).
- SSH accepts keys only, and there is no root login. Login to the app remains password plus TOTP, with throttling (Phase 1).
- All secrets live only in the server's `.env` (mode 600, owned by `deploy`) and the owner's password manager. They never go in the repo, a CI log or a chat.
- The deploy key is read-only and limited to this repo.
- Off-site backups are encrypted before upload.

## 6. Testing

- **Shell scripts:** checked with `shellcheck`. `deploy.sh` and `restore.sh` have their logic tested against a fake `docker`/`git` on `PATH`. `bootstrap.sh` can't be fully exercised without a real VM; it is checked for syntax and idempotence and reviewed line by line, and the owner's first run is its live test, with the guide saying what each step prints.
- **Backup service:** unit tests for scheduling, retention, encryption and the Drive upload (Google faked, as always). An integration test on real Postgres covers dump, restore and compare.
- **Caddy config:** `caddy validate`, plus a test that serves the production build and checks the headers. The CSP is checked by loading every page in headless Chromium and asserting no CSP violations.
- **Frontend:** Vitest for the Backups settings card and the manifest links; phone-width checks.
- The existing suites stay green, and nothing contacts external services from tests.

## 7. Out of scope

- Automatic deploy-on-merge (after a few manual deploys, per §11a).
- Claude ranking of the Inbox, Gmail sync and interview prep (later phases).
- Copying the Mac or PC test data to the server.
- Multiple users, a staging server, Kubernetes, and managed databases.
- Moving to a home server later: still a stop, copy and repoint-DNS job, as the README's "Moving to a new server" section describes.

## 8. What only the owner can do

These happen during the deploy walkthrough, guided step by step:
- Create the DigitalOcean account and add payment or student credit.
- Buy the domain.
- Make the SSH key and create the droplet.
- Set the DNS record.
- Add the deploy key on GitHub.
- Put the secrets in the server's `.env`.
- Make the Google Cloud console changes and click Publish.
- Schedule the Claude routine.
- Set up the uptime monitor.

Nothing here spends money or changes an account without the owner doing it.
