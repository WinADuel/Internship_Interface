# Phase 3 Plan: Server Deploy

Spec: `docs/superpowers/specs/2026-10-08-server-deploy-design.md` (approved by the owner 2026-10-08).
Branch: `phase-3-deploy` from `main` at `af2fd16`. Progress log: `docs/phases/phase-3-progress.md`.

Rules (unchanged from Phase 2):
- Test-first. Nothing in tests contacts Google, Anthropic, GitHub, DigitalOcean or any other external service; use fakes.
- One implementer agent at a time on the branch. The lead reviews every diff, logs rulings, and pushes each reviewed task.
- Run a secret check before every push: no `.env`, keys or tokens. Placeholders only in `.env.example`.
- Never commit to `main`.
- Backend: `pytest` on real PostgreSQL 16 (`filterwarnings=error`).
- Frontend: `npm run test -- --run`, `npm run check` and `npm run build`.
- Shell: `shellcheck` with no warnings.

## Task 1: Compose and image hardening (spec §4.3)
- Add an `x-logging` anchor (`json-file`, `max-size: 10m`, `max-file: "3"`) and apply it to every service.
- Give the backend a healthcheck on `http://localhost:8000/api/health` using Python's urllib (the slim image has no curl). Use interval 10s, timeout 5s, retries 6, `start_period` 30s.
- `caddy` waits for `backend: service_healthy`. `sheet-sync` waits for `db: service_healthy`.
- Backend image: install the PostgreSQL **16** client (`pg_dump`/`pg_restore`) from the PGDG apt repository, because Debian bookworm ships 15, which can't dump a 16 server. Pin the major version and keep layers small.
- Tests:
  - `backend/tests/test_compose_file.py` parses `docker-compose.yml` (add `pyyaml` to requirements-dev).
  - It asserts that every service has the logging anchor, the backend healthcheck, the `depends_on` conditions, that no `db` ports are published, and that only caddy publishes ports.

## Task 2: Caddy security headers and public pages (spec §4.3, §4.5)
- Caddyfile: add a Content-Security-Policy and `Permissions-Policy` (camera, microphone, geolocation, payment all `()`) to the existing header block.
  - CSP: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'`.
  - Keep HSTS.
- `frontend/public/about.html` and `frontend/public/privacy.html`: static HTML with inline-free CSS (a small `public/static.css`) and no scripts.
  - The contact email comes from `{{env "CONTACT_EMAIL" | html}}`, using Caddy `templates` limited to those two paths.
  - Privacy content follows spec §4.5: data stored, Google scopes and why, no sharing or selling, how to revoke at myaccount.google.com/permissions, how to request deletion, and a last-updated date.
- Compose: pass `CONTACT_EMAIL` to caddy (default empty; the pages say "the site owner" when empty).
- Tests:
  - A Vitest test checks that the pages exist, contain no `<script>`, link to each other, and reference the template variable.
  - A `scripts/check-caddyfile.sh` runs `caddy validate` through `docker run caddy:2` when Docker is available; CI wiring comes in Task 8.

## Task 3: Phone home-screen support (spec §4.6)
- Add `public/manifest.webmanifest` (name, short_name "Tracker", `start_url "/"`, `display: standalone`, theme/background colours from the app's CSS variables) and icons at 192, 512 and 180 (`apple-touch-icon`). Generate the icons from one committed SVG.
- `index.html`: add the manifest link, apple-touch-icon, `theme-color`, `apple-mobile-web-app-capable` and the status-bar style.
- Load Dashboard, Applications, Discover, Contacts, Essays and Settings at 390×844 in headless Chromium against the Vite preview with the API mocked, and fix horizontal overflow.
- Tests: Vitest for the `index.html` links and the manifest fields. Phone-width overflow fixes get component tests where practical.

## Task 4: Local database backups (spec §4.4, part 1)
- `app/services/backup/dump.py`:
  - Run `pg_dump --format=custom` via `subprocess.run` with an argument list (never `shell=True`) and a timeout. Take the connection from `DATABASE_URL` and pass the password through the `PGPASSWORD` env, never on the command line.
  - Write the dump to `<BACKUP_DIR>/<label>/tracker-<UTC timestamp>.dump` (labels `nightly` / `pre-deploy` / `manual`).
  - Write atomically: a temp file, then rename.
- `retention.py`: keep 14 nightly, 5 pre-deploy and 5 manual dumps; never delete the newest file.
- `app/jobs/db_backup.py`:
  - A nightly loop at 02:30 local time, the same pattern as `nightly_sheet_sync`.
  - `--once --label pre-deploy` for `deploy.sh`.
  - Exit code non-zero on failure.
- Migration `0006`: `app_settings` gains `last_backup_at`, `last_backup_error`, `last_offsite_at`, `last_offsite_error`.
- Compose: a `db-backup` service using the backend image, with `./backups:/backups` bind-mounted, `BACKUP_DIR=/backups`, waiting for a healthy db, and logging. Add `backups/` to `.gitignore`.
- CLI: `python -m app.cli restore-check <dump>` lists a dump's contents with `pg_restore --list`, to verify a file is readable.
- Tests:
  - Unit tests for the command line, the env (password not in argv), retention and the schedule.
  - Integration test on the real test Postgres: dump, `pg_restore` into a scratch database, compare row counts per table, drop the scratch database.
- Config: `BACKUP_DIR` (default `/backups`) and `BACKUP_ENCRYPTION_KEY` are optional. Missing keys never stop the app starting.

## Task 5: Off-site encrypted copy in Google Drive, plus status API (spec §4.4, part 2)
- `crypto.py`: Fernet encrypt/decrypt with `BACKUP_ENCRYPTION_KEY`, validated as a Fernet key when present.
  - Encrypted file name: `tracker-<timestamp>.dump.enc`.
  - CLI `python -m app.cli decrypt-backup <in> <out>`.
- `drive_client.py`, following `sheets_client.py`'s style:
  - Find or create the folder "Internship Tracker Backups" (app-created, so `drive.file` covers it).
  - Multipart upload; list the app's files in that folder; delete beyond the newest 30.
  - Error messages carry no tokens or response bodies, and reuse `RECONNECT_HINT` on 403.
- After each nightly backup (not pre-deploy or manual), encrypt and upload if Google is connected and the key is set. Otherwise record a clear `last_offsite_error` ("connect Google in Settings" / "set BACKUP_ENCRYPTION_KEY in .env").
- Routes, cookie-authenticated with the Claude token rejected, added to the boundary-list test:
  - `GET /api/backups/status` returns `{last_backup_at, last_backup_error, last_offsite_at, last_offsite_error, offsite_configured}`.
  - `POST /api/backups/run` runs a manual local backup synchronously under an advisory lock (409 if one is running) and returns the status.
- Tests: Fernet round trip, a wrong key fails cleanly, Drive client against a fake transport (folder create/reuse, upload, pruning, 401/403/5xx mapping), status writes, routes.

## Task 6: Settings → Backups card (frontend)
- Add `lib/api/backups.ts` and types.
- Add `components/settings/BackupSettings.svelte`: last backup ("2 hours ago" with exact time on hover), last off-site copy, any errors, and a **Back up now** button with busy state and a toast. Explain where backups live in one sentence.
- Add it to `routes/Settings.svelte` after the backup-sheet card.
- Tests: Vitest for the states (never run, ok, error, off-site not configured, 409, busy).

## Task 7: Server scripts (spec §4.1, §4.2)
- `ops/server/bootstrap.sh` (bash, `set -euo pipefail`, must run as root, idempotent):
  - creates the `deploy` user, copies authorized_keys, and writes an sshd drop-in `/etc/ssh/sshd_config.d/10-tracker.conf` (`PasswordAuthentication no`, `PermitRootLogin no`, `KbdInteractiveAuthentication no`), refusing to disable root login unless `deploy` has a key;
  - configures ufw (22/tcp, 80/tcp, 443/tcp, 443/udp);
  - installs Docker from Docker's apt repo, with the keyring in `/etc/apt/keyrings`;
  - sets up unattended-upgrades with an automatic reboot at 04:30;
  - adds a 2 GB swapfile with fstab;
  - sets the timezone (argument, default `America/Chicago`);
  - prints a summary.
  - Add a `--dry-run` that prints the actions only.
- `ops/server/deploy.sh [ref]`:
  - refuses without `.env`, or with `change-me` in `.env`, or with `.env` mode wider than 600;
  - takes the pre-deploy backup via `docker compose run --rm db-backup python -m app.jobs.db_backup --once --label pre-deploy` (skipped with a note on the very first deploy, when no db container exists yet);
  - runs `git fetch --tags origin` and `git checkout --detach <ref or origin/main>`;
  - runs `docker compose up -d --build --remove-orphans`;
  - polls `https://$DOMAIN/api/health` for 120 s;
  - prints the old and new commit, plus a rollback hint.
- `ops/server/restore.sh <dump|dump.enc>`:
  - confirms by asking the user to type the database name (skippable with `--yes`);
  - decrypts `.enc` via the CLI;
  - stops the app services;
  - runs `pg_restore --clean --if-exists` inside the db container;
  - starts everything and checks health.
- Tests: pytest drives the scripts with fake `docker`, `git` and `curl` executables on `PATH` that log their argv. It covers the refusal cases, the first-deploy skip, the ref handling, a health timeout giving a non-zero exit, the restore confirmation, and `bootstrap.sh --dry-run` output. All scripts must be shellcheck-clean.

## Task 8: Guides, env template, CI checks (spec §4.7)
- `docs/deploy/server-setup.md`: the owner's step-by-step guide covering spec §4.7 steps 1–9, with exact clicks and commands for a first-timer on a Mac, and what success looks like at each step.
- `.env.example`:
  - add `CONTACT_EMAIL` and `BACKUP_ENCRYPTION_KEY`;
  - give generation commands that work on a stock Mac (openssl) alongside the Python ones;
  - make the production `GOOGLE_REDIRECT_URI` example clear.
- README: rewrite "Deploying" as a short summary pointing to the guide; add a "Backups" update (automatic nightly + Drive copy + restore script).
- CI: add a `deploy-config` job that runs:
  - shellcheck on `ops/**/*.sh`;
  - `docker compose config -q` with `.env.example` copied to `.env`;
  - `caddy validate` via the `caddy:2` image, with sample env.

## Task 9: Full-stack smoke test (lead)
- In the sandbox (Docker available): `docker compose up -d --build` with `DOMAIN=localhost`.
- Then check:
  - health and the backend healthcheck;
  - the CSP across every page in headless Chromium (zero violations; log in through a test account);
  - `/about.html` and `/privacy.html` render with the email filled;
  - a manual backup, then `restore.sh` on it;
  - `deploy.sh` against the local clone.
- Fix anything found, and record the results in the progress log.

## Finish
- A whole-branch review (backend and ops reviewer, plus a frontend reviewer), fixes, the final test counts, `docs/phases/phase-3-report.md`, the phases index, and a PR for the owner to merge.
- After the merge: the live deploy walkthrough with the owner, using `docs/deploy/server-setup.md`.
