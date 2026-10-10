# Phase 3 Report: Server Deploy

| | |
|---|---|
| **Status** | Complete on branch `phase-3-deploy`. The owner reads this report and merges the PR; nothing has been merged to `main`. After the merge, the owner and Claude do the live deploy together using the guide. |
| **Built** | 2026-10-08 to 2026-10-09, one cloud session. The owner made the choices on decision cards and approved the design the same day. |
| **Branch** | `phase-3-deploy`, cut from `main` at `af2fd16` |
| **Spec** | [`docs/superpowers/specs/2026-10-08-server-deploy-design.md`](../superpowers/specs/2026-10-08-server-deploy-design.md) |
| **Plan** | [`docs/superpowers/plans/2026-10-08-server-deploy-phase3.md`](../superpowers/plans/2026-10-08-server-deploy-phase3.md) (9 tasks) |
| **Detailed log** | [`phase-3-progress.md`](phase-3-progress.md): one entry per task, with every finding and ruling |
| **Owner guide** | [`docs/deploy/server-setup.md`](../deploy/server-setup.md) |
| **Tests at finish** | Backend: 1537 passing against real PostgreSQL 16, up from a baseline of 1171. Frontend: 440 passing, up from 389. `svelte-check`: 0 errors, 0 warnings. Production build: clean. `alembic check`: no drift. `shellcheck`: clean. CI now runs four jobs, including a full-stack smoke test of the real images. |

---

## 1. What Phase 3 delivers

The tracker is ready to run on a public server. You will reach one tracker, with one set of data, from your phone, Mac and PC, wherever you are.

- **Server setup in one script.** `ops/server/bootstrap.sh` turns a new DigitalOcean Ubuntu 24.04 droplet into a locked-down Docker host:
  - a `deploy` user;
  - SSH that accepts keys only, with root login off;
  - a firewall open only for SSH and the website;
  - automatic security updates, with a reboot at 04:30 if one is needed;
  - 2 GB of swap;
  - your time zone.

  It is safe to run again, and `--dry-run` shows what it would do.
- **Deploys in one command.** `ops/server/deploy.sh`:
  1. checks `.env`;
  2. takes a pre-deploy backup;
  3. checks out `main`, or any commit you name;
  4. rebuilds;
  5. waits until the site answers over HTTPS.

  It then prints the single command that undoes the deploy. `deploy.sh --restore <dump> <commit>` is a one-step rollback, including past a database migration.
- **Automatic backups.**
  - **On the server.** A new `db-backup` service backs up the database every night at 02:30 your time. It keeps 14 nightly, 5 pre-deploy and 5 manual copies.
  - **In Google Drive.** Each nightly backup is encrypted and copied to an "Internship Tracker Backups" folder in your Drive, which keeps the newest 30. This uses the Google permission the app already has, and Google never sees unencrypted data.
  - **In the app.** **Settings → Backups** shows the last backup, the last Drive copy, any problem, and **Back up now**.
  - **Restoring.** `ops/server/restore.sh` restores any copy, including a downloaded Drive copy. It is all-or-nothing: if anything goes wrong, the database is unchanged.
- **Security headers.** Every response now carries a strict Content-Security-Policy and a Permissions-Policy, on top of the existing HSTS, frame and sniffing protections. A headless-browser walk through every page found no violations.
- **Public homepage and privacy policy** at `/about.html` and `/privacy.html`. Google requires them before the OAuth app can be published, and publishing ends the 7-day reconnects. Your contact email is filled in from `.env` when the page is served, so it never goes into the repository.
- **Phone.** You can add the tracker to your home screen, with its own icon, and it opens full-screen. Three phone-width problems are fixed:
  - Essays scrolled sideways;
  - Settings scrolled sideways;
  - the menu hid Settings and Log out off the edge of the screen.
- **A step-by-step guide** for everything only you can do: accounts, domain, SSH key, droplet, DNS, deploy key, `.env`, Google console, the Claude daily job, uptime alerts, plus day-to-day deploy, rollback, restore and troubleshooting.
- **No new Google permissions, and no paid services** beyond the droplet and domain.

## 2. Architecture additions

- **Backend `app/services/backup/`:**
  - `dump.py`: `pg_dump`/`pg_restore` with the password in the environment, never on the command line.
  - `retention.py`.
  - `service.py`: `run_backup`, which never raises and records its status.
  - `crypto.py`: Fernet, capped at 100 MB.
  - `drive_client.py`: Drive v3, with multipart or resumable upload.
  - `offsite.py`.
  - `lock.py`: a Postgres advisory lock shared by the job and the route.
  - `restore.py`: restore in one transaction.
- **Jobs:** `app/jobs/db_backup.py`, plus `app/jobs/schedule.py`, a time-zone-aware nightly scheduler now shared with the sheet sync. Both jobs had drifted by an hour across daylight-saving changes.
- **Routes:** `GET /api/backups/status` and `POST /api/backups/run`. Both are cookie-only, and the Claude token is refused.
- **Data:** migration `0006_backup_status` adds four status columns to `app_settings`.
- **CLI:** `restore-check`, `decrypt-backup` and `restore`.
- **Compose:**
  - log rotation on every service;
  - a backend healthcheck;
  - Caddy waits for a healthy backend;
  - the `db-backup` service;
  - a `./backups` folder.
- **Backend image:** pinned to Debian bookworm, with the PostgreSQL 16 client from PGDG.
- **Ops:** `ops/server/{bootstrap,deploy,restore,lib}.sh`, `ops/checks/{check-caddyfile,stack-smoke}.sh`.
- **Frontend:** `BackupSettings.svelte`, `lib/api/backups.ts`, a manifest and icons (rendered from one SVG by `scripts/render-icons.cjs`), and the static `about.html`, `privacy.html` and `static.css`.
- **CI:**
  - `deploy-config`: shellcheck, Compose config, `caddy validate`, and a build of the real backend image that confirms `pg_dump` 16.
  - `stack-smoke`: brings up the whole real stack, checks headers and pages, backs up, restores, redeploys and rolls back.

## 3. How it was built

The owner made the choices on decision cards:
- Phase 3 is the server deploy, not Gmail sync or interview prep.
- The server is a DigitalOcean droplet.
- The address is a new `.com`.

The owner then approved the design. The 9-task plan ran task by task, one implementer at a time. The lead read each report and diff, recorded rulings, and pushed each reviewed task. A draft PR was opened early, so CI checked every push.

Two reviewers covered the whole branch at the end: one for backend, ops and docs, one for the frontend. Their findings were fixed in one round.

### Task log

| Task | Commit(s) | Outcome |
|---|---|---|
| 0. Design, plan, progress log | `f4faa18`, `bf01474` | |
| 1. Compose and image hardening | `5675593` | Clean. The base image is pinned to bookworm, because `3.12-slim` moved to Debian trixie. |
| 2. Security headers, public pages | `6742db5` | Clean. Verified with a real backend behind Caddy and a Chromium walk of every route. |
| 3. Phone home-screen support | `23cf87d` | Clean. Three real overflow problems found and fixed. |
| 4. Local database backups | `72bf7d3` | Clean. A dump/restore round trip runs on real Postgres in CI. |
| 5. Encrypted Drive copy, status API | `c033d8c` | Clean |
| 6. Settings → Backups card | `34964bc` | Clean |
| 7. Server scripts | `8b7cf36` | `bootstrap.sh` ran in a real Ubuntu 24.04 systemd container and found one bug (`sshd -t` needs `/run/sshd`), which was fixed. |
| CI fix | `6d2f894` | A bootstrap test read the CI runner's own swap settings. It now uses a fake host. |
| 8. Guide, `.env` template, CI checks | `f30396a` | Clean. GitHub's SSH fingerprint in the guide was checked against GitHub's docs. |
| 9. Full-stack smoke test | `8bc6dc6` | All steps passed on a real stack. It found no bugs in earlier tasks. |
| Review fixes | `450f15d`, `62d6550` (backend/ops), `a3fbafc` (frontend) | See §5 |

## 4. Quality and security

- **No test touches the internet.** Google, GitHub and DigitalOcean are always faked.
- **Real-system checks beyond the unit tests:**
  - backup and restore on real PostgreSQL 16;
  - Caddy 2.10 serving the real Caddyfile;
  - headless Chromium checking the CSP and phone layout;
  - `bootstrap.sh` run in a real Ubuntu 24.04 container, confirming key login works and root and password login are refused;
  - the full stack in Docker, through the smoke script, both in the sandbox and in CI.
- **Secrets:**
  - `.env` must be mode 600, and `deploy.sh` refuses `change-me` and `@example.com` values.
  - The database password goes through the environment, never on a command line.
  - Drive errors never include tokens or response bodies, and the upload session URL is kept out of logs.
  - Backups are root-only on disk, and encrypted before they leave the server.
- **Lockout safety:** SSH password and root login are switched off only after the `deploy` user has a key, and the new config is checked with `sshd -t` first.
- **Restore safety:**
  - A restore asks you to type the database name.
  - It takes a safety backup first.
  - It runs in one transaction.
  - If the app doesn't come back, it prints the exact undo command.

## 5. Final whole-branch review

There were no Critical findings. Three Important findings were fixed:

1. **Rollback past a migration pointed at the wrong backup.** When the old code couldn't start on the migrated database, the rollback's own output suggested the wrong backup file and commit. The fix is a one-step `deploy.sh --restore <dump> <commit>`: it builds first, then stops the app, restores, starts and health-checks. Each deploy prints the one correct command to undo it.
2. **`restore.sh` didn't print its undo command when the app failed to come back.** It does now.
3. **The Backups card showed a failing Drive copy as a yellow warning.** Days of failed uploads looked like a minor issue. Only the "uploaded, but old copies were not removed" case is a warning now; everything else is red.

Minor fixes in the same round:
- Nightly jobs keep local time across daylight-saving changes. Before, the fall-back night ran twice.
- HTTP client logs no longer show the Drive upload URL.
- First-deploy detection ignores other Compose projects.
- `apt` waits for the lock that fresh droplets hold for their first-boot updates.
- A failed swap step warns instead of stopping the script.
- The guide notes that the Claude routine's environment must be allowed to reach your domain.
- The `@example.com` contact email is refused.
- "Moving to a new server" now stops writes before the final backup.
- The Essays dropdown showed blank while "Save link" went to the first application. This dates from before this phase and is fixed.
- The Backups card: quieter toasts, a refresh after an unclear result, and a screen-reader status line.
- Privacy page: accurate cookie wording, plus a sentence about the Claude assistant.
- The manifest has an `id`.

## 6. Decisions and trade-offs

Every ruling is in [`phase-3-progress.md`](phase-3-progress.md). These are the ones you are most likely to notice:

- **Deploys are manual, one command.** Automatic deploy-on-merge waits until a few manual deploys have gone smoothly, as decided in Phase 1 (§11a).
- **Images are built on the server.** On a 1 GB droplet the first build takes several minutes. If it ever runs out of memory, resize to 2 GB ($12/month) in the DigitalOcean panel.
- **Drive copies are nightly only.** "Back up now" and pre-deploy backups stay on the server. Drive copies are capped at 100 MB so encryption can't exhaust a 1 GB server; today's database is a few MB.
- **The `deploy` user has passwordless sudo.** It has no password, and Docker access is root-equivalent anyway. SSH is key-only, so fail2ban was left out.
- **The server starts with an empty database.** Your Mac and PC copies stay as test copies.
- **Google console and website click-paths** in the guide are written from current knowledge. Button names change, so we'll confirm them as we go during the walkthrough.

## 7. Known limitations

- **Not yet run on a real droplet.** Everything that can be tested without one has been. The first real run of `bootstrap.sh` and `deploy.sh` happens during our walkthrough.
- **The Drive upload hasn't talked to real Google yet**; it was tested against a fake Drive. The first nightly backup after you connect Google is its live check, and Settings → Backups shows the result.
- **Docker Hub rate limits** could occasionally slow the new CI jobs, which pull public images without logging in. It hasn't happened yet.
- **Rollback output can't tell whether a deploy included a migration**, so it always shows the safe `--restore` command first.

## 8. What's next: what the owner does

**To merge:** read this report, then merge the PR from `phase-3-deploy` into `main`.

**To go live**, follow [`docs/deploy/server-setup.md`](../deploy/server-setup.md), and Claude can walk you through it live:
1. Check the GitHub Student Developer Pack for DigitalOcean credit, then create the DigitalOcean account.
2. Buy the `.com`.
3. Make an SSH key on the Mac, then create the $6 droplet.
4. Run `bootstrap.sh`, then point the domain at the droplet.
5. Add the deploy key, clone, and fill in `.env`. Keep a copy of `.env` in a password manager.
6. Run `deploy.sh`, then create your login, then sign in from the phone, Mac and PC.
7. In Google Cloud, add the new redirect URI, the homepage and privacy URLs, then **Publish app**. Then connect Google in the app.
8. Create a Claude token and schedule the daily routine.
9. Set up the UptimeRobot alert.

**Later:** Claude ranking of the Discover inbox (now possible with a public address), then Gmail sync or interview prep.
