# Internship Tracker

FastAPI + PostgreSQL backend, Svelte static frontend, served behind Caddy (automatic HTTPS).

## Deploying

The same `docker-compose.yml` runs on the server and on a local copy (Mac or PC).

**The server** (a DigitalOcean droplet): follow [`docs/deploy/server-setup.md`](docs/deploy/server-setup.md), a step-by-step guide from creating the accounts to the daily Claude job and an uptime check. It uses three scripts in `ops/server/`. `bootstrap.sh` runs once, as root, on a new Ubuntu 24.04 droplet: it creates the `deploy` user, turns SSH into keys-only with no root login, turns on the firewall (22, 80, 443), installs Docker, turns on automatic security updates, adds swap and sets the time zone. `deploy.sh [REF]` deploys `origin/main` (or a given commit): it checks `.env`, takes a pre-deploy database backup, rebuilds, waits for `/api/health` and prints the one command that undoes the deploy (`deploy.sh --restore <its pre-deploy backup> <previous commit>`, which also puts back the database from just before it). `restore.sh FILE` puts a backup back (see **Backups**).

**A local copy:**

1. Copy `.env.example` to `.env` and fill it in (use `DOMAIN=localhost`; generate the secrets with the commands in the file; keep the `POSTGRES_*` values consistent with `DATABASE_URL`). Never commit `.env`.
2. Start everything: `docker compose up -d --build`
3. Create your account: `docker compose exec backend python -m app.cli create-user --username <you>`
4. Log in at `https://<DOMAIN>/`.

The Google OAuth client in Google Cloud Console must list `https://<DOMAIN>/api/docs/google/callback` as an authorized redirect URI (it must match `GOOGLE_REDIRECT_URI`).

Creating the account is the only way to enroll an authenticator: there is no setup endpoint, and an account whose authenticator was never confirmed cannot log in (re-run the command with `--reset` to start over).

Login is throttled: after 5 consecutive failed attempts the server rejects all logins (HTTP 429) for a growing delay of 1, 2, 4, ... up to 300 seconds, and a successful login resets it. A TOTP code can only be used once.

## Required `.env` secrets

The backend refuses to start if `JWT_SECRET` is a placeholder (`change-me`, `changeme`, `secret`) or shorter than 32 bytes, or if `TOKEN_ENCRYPTION_KEY` is not a valid Fernet key. If `docker compose logs backend` shows a validation error mentioning one of these, regenerate the value with the command in `.env.example`.

## Google Docs setup

The Essays page reads Google Docs through a Google OAuth client you create yourself (read-only Drive scope).

1. In [Google Cloud Console](https://console.cloud.google.com/), create (or pick) a project.
2. Enable the **Google Drive API** for it (APIs & Services, Library).
3. Configure the **OAuth consent screen** (External). While the app is in *Testing*, add your own Google account under **Test users**, or Google will refuse the sign-in.
4. Create credentials: **OAuth client ID**, application type **Web application**. Under **Authorized redirect URIs** add exactly `https://<DOMAIN>/api/docs/google/callback`. It must match `GOOGLE_REDIRECT_URI` in `.env` character for character.
5. Put the client ID and secret in `.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, then `docker compose up -d` to apply them.
6. Open the Essays page and connect Google.

**Refresh tokens expire after 7 days while the consent screen is in Testing mode.** Once that happens, Google docs fail to load (the backend logs a warning such as `google token request rejected (status 400)`) until you reconnect. Either reconnect from the Essays page weekly, or click **Publish app** on the consent screen to make the token long-lived (an unverified published app only shows an "unverified app" warning during consent, which is fine for a single user).

If docs fail to load, `docker compose logs backend` shows why: every failure logs a one-line warning with an HTTP status or error type (never a token or a response body).

## Outreach: backup sheet and the daily Claude job

**Backup Google Sheet.** The app mirrors applications and contacts to a sheet called "Internship Tracker Backup" in your Drive. It needs the `drive.file` permission, which only covers files the app creates.

1. In the same Google Cloud project, also enable the **Google Sheets API**.
2. If you connected Google before this feature existed, reconnect it once. Use **Settings → Backup sheet → Connect Google**, or the Essays page. Until then, syncs fail with "reconnect Google to grant the drive.file permission".
3. Press **Sync now** in Settings. After that, the sheet updates after every change, and the `sheet-sync` service in `docker-compose.yml` re-syncs everything nightly. Sync errors are shown in Settings and never block your edits.

**Daily Claude research job.** A Claude Code scheduled routine, running on your Claude plan, researches the people in the Research Queue and writes email drafts. Its instructions are in [`ops/claude-routine/outreach-job.md`](ops/claude-routine/outreach-job.md). The appendix there covers setup:

The same routine writes the company briefs you request for interviews (see **Interview prep**).

1. Create a token in **Settings → Claude tokens**.
2. Schedule the routine daily with `APP_BASE_URL` and `CLAUDE_TOKEN` in its configuration.

The routine runs in the cloud, so it only works once the app is reachable at its public HTTPS address. Revoking the token stops it.

## Job discovery

The **Discover** page finds internship postings for you. It scans two community lists on GitHub ([SimplifyJobs](https://github.com/SimplifyJobs/Summer2027-Internships) and [vanshb03](https://github.com/vanshb03/Summer2027-Internships)) plus a watchlist of companies whose careers pages run on Greenhouse, Lever, Ashby or Workday. Matches land in the Inbox; Save keeps one, and Apply turns a saved posting into an Applied application. You can also paste any posting link.

Google, Microsoft, Apple, Meta and Amazon use their own careers sites, so they can't be watched. Their internships come in through the community lists, or you can paste a posting.

**Workday** has no official public API. The app uses the endpoint Workday's own career pages call. If Workday changes it, only the scans of your Workday companies fail (the error shows on the Watchlist tab); everything else keeps working.

- **Add a company:** Discover → Watchlist, paste its careers page URL (for example `https://job-boards.greenhouse.io/<company>` or `https://jobs.lever.co/<company>`), and press Add. Its postings arrive with the next scan.
- **Filters** (terms, categories, keywords, locations, sponsorship, scan interval, list URLs) live in **Settings → Job discovery**. Changing them re-filters the postings already found straight away.
- **Scanning:** `docker compose up -d --build` also starts the `job-scan` service, which runs its first scan about a minute after it starts, then every 6 hours by default. **Scan now** on the Discover page runs one immediately.
- Saved postings are also mirrored to a "Saved postings" tab in the backup sheet. Discovery needs no Google permissions or secrets of its own.

The board formats were written from vendor documentation, because the build environment could not reach those sites. The first real scan is their live check: if a watched company shows an error, compare its response with [`backend/tests/fixtures/discovery/README.md`](backend/tests/fixtures/discovery/README.md).

## Interview prep

The **Interview Prep** page tracks every interview round of every application and helps you get ready for each one.

- **Rounds:** add them from an application's panel (**Add round**) or from Interview Prep, with the kind, date and time, length, format, meeting link or address, and interviewers. An application can have several rounds. Its **Next interview** is now derived from them (the earliest scheduled round) and is read-only in the application form; giving a new application an interview date adds its first round. When an application with rounds is still before Interview, the panel offers **Move to Interview**.
- **Prep page** for each round: a checklist (it starts with six standard steps), prep notes and questions to ask (saved as you type), the stories you plan to tell, the interviewers (tracked contacts, so thank-you notes have an address), a company brief, ready-made Claude prompts to copy into claude.ai (company research, likely questions, a mock interview, "tell me about yourself", a thank-you note), and **Add to calendar**, which downloads an `.ics` file.
- **After the interview:** mark it done, record the outcome and how it went, and draft thank-you notes, which open in Gmail compose for you to send (the app never sends email). A round shows **Thank-you due** for 3 days after it, until you press **Mark sent**.
- **Story bank:** reusable stories in STAR form (situation, task, action, result) with tags; link them to any round.
- **Company brief:** **Ask Claude for a brief** queues a request for the daily Claude job, which researches the company from public sources and writes a plain-text brief with its sources. It is shared by every round of that application. This is the only part that needs the server.
- **Dashboard:** the **Upcoming interviews** widget lists rounds in the next 14 days with their checklist progress, and any thank-you that is due.
- The backup sheet gains an **Interviews** tab (company, role, round, time, state, outcome, thank-you sent). Prep notes and reflections are not exported.

## Gmail sync (optional)

Gmail sync watches your mail for application updates so you don't have to move cards by hand. It is off until you turn it on; [`docs/deploy/server-setup.md`](docs/deploy/server-setup.md) step 8 ("Turn on Gmail sync") walks through the Google side.

- **Connect:** Settings → Gmail → **Connect Gmail** asks Google for read-only mail access (`gmail.readonly`), separately from the Drive permissions. Then tick **Sync Gmail**. The `gmail-sync` service checks every 30 minutes by default (15–240), looking back 30 days the first time (1–90); **Sync now** checks at once.
- **What it reads:** the headers and Gmail's short preview of recent Inbox and Sent mail (not Promotions, Social or chats). Bodies are never downloaded, nothing is sent, and no email data goes to the Claude job.
- **What it finds:** confirmations, rejections, interview invitations, online assessments and offers from companies you track (directly or through applicant-tracking systems like Greenhouse or Lever), replies from contacts you emailed, emails you sent to contacts, and application emails from companies you don't track yet.
- **Email updates** (menu, with a count) lists each one with the sender, subject, preview and what it would do: mark applied, move to Rejected or Offer, add an interview round (the round form opens prefilled), add an assessment note with a 7-day follow-up, mark a contact replied or sent, or add a new application (edit the company and role first). **Accept** applies it through the same steps as clicking in the app; **Dismiss** drops it; **Open in Gmail** shows the thread. The Dashboard's Needs Attention widget and each application's panel show them too.
- **Auto-apply** (off by default) applies confirmations and contact replies/sent mail without asking; rejections, interviews, assessments and offers always wait for you.
- **What it keeps:** for matched emails only, the Gmail IDs, date, sender, subject and preview (300 characters each). Unmatched mail leaves no trace, and decided updates are deleted after 90 days.
- Changing your Google password disconnects it (Google's rule for mail access); Settings then offers **Reconnect Gmail**.

## Backups

The database lives in the `pgdata` Docker volume. The `db-backup` service backs it up by itself:

- **Nightly** at 02:30 (in `TZ`), a `pg_dump` to `backups/nightly/`; the newest 14 are kept. `deploy.sh` also takes one before every deploy (`backups/pre-deploy/`, newest 5 kept).
- **Off-site copy:** when `BACKUP_ENCRYPTION_KEY` is set in `.env` and Google is connected, each nightly dump is encrypted and uploaded to the "Internship Tracker Backups" folder in your Google Drive; the newest 30 copies are kept. Google only ever sees encrypted data. Dumps over 100 MB aren't copied (Settings shows the error).
- **Settings → Backups** shows the last backup and the last off-site copy, with any error, and has **Back up now**, which adds a copy on the server only (`backups/manual/`, newest 5 kept).

The files in `backups/` belong to root, so read them through the scripts rather than directly.

**Restore** with `ops/server/restore.sh <file>`, from the repo folder. The file is a dump from `backups/`, or a `.dump.enc` copy downloaded from Drive (it needs the `BACKUP_ENCRYPTION_KEY` that made it). The script checks the file, asks you to type the database name, backs up the current data first, then replaces all data in one transaction and restarts the app. [`docs/deploy/server-setup.md`](docs/deploy/server-setup.md) step 11 has the details.

Keep a copy of `.env` in a password manager (see below): a dump alone is not enough to use the encrypted data in it, and the Drive copies can't be read without `BACKUP_ENCRYPTION_KEY`.

## Moving to a new server

1. On the old server, in the repo folder, stop the app so nothing changes after the last backup, then take it:

   ```
   docker compose stop backend caddy job-scan sheet-sync
   docker compose run --rm db-backup python -m app.jobs.db_backup --once --label manual
   ```

   Copy the newest file in `backups/manual/` to the new server (it belongs to root: `sudo cp` it to your home folder and `sudo chown deploy:` it first). The newest Drive copy works too, but it misses anything changed since the last nightly backup.
2. On the new server, clone the repository and copy the old `.env` over **verbatim**. Do not regenerate `JWT_SECRET`, `TOKEN_ENCRYPTION_KEY` or `BACKUP_ENCRYPTION_KEY`: your TOTP secret and the stored Google token are encrypted with `TOKEN_ENCRYPTION_KEY`, and a different key makes them undecryptable; the Drive backups can only be read with the `BACKUP_ENCRYPTION_KEY` that made them. (A changed `JWT_SECRET` just logs you out.) Only change `DOMAIN` and `GOOGLE_REDIRECT_URI` if the hostname changes, and then also update the redirect URI in Google Cloud Console.
3. Repoint the domain's DNS A/AAAA record at the new server and keep ports 80 and 443 open. Caddy obtains a certificate once DNS resolves to the new host, so do this before deploying (the scripts check the site over HTTPS).
4. Run `ops/server/deploy.sh`, then `ops/server/restore.sh <the copied file>`.
5. Log in and check that the Essays page can still load a doc.

**If login returns 500 after a move, the encryption key changed**: `TOKEN_ENCRYPTION_KEY` in the new `.env` is not the one the data was encrypted with. Put the original key back. If it is lost, recreate the account with `docker compose exec backend python -m app.cli create-user --username <you> --reset` and reconnect Google from the Essays page.
