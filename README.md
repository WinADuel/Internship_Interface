# Internship Tracker

FastAPI + PostgreSQL backend, Svelte static frontend, served behind Caddy (automatic HTTPS).

## Deploying

The same `docker-compose.yml` runs on a VPS or a local server.

1. Copy `.env.example` to `.env` and fill it in (generate `JWT_SECRET` and `TOKEN_ENCRYPTION_KEY` with the commands in the file; keep the `POSTGRES_*` values consistent with `DATABASE_URL`). Never commit `.env`.
2. Point your domain's DNS A/AAAA record at the server, and open ports 80 and 443.
3. Start everything: `docker compose up -d --build`
4. Create your account: `docker compose exec backend python -m app.cli create-user --username <you>`
5. Log in at `https://<DOMAIN>/`.

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

1. Create a token in **Settings → Claude tokens**.
2. Schedule the routine daily with `APP_BASE_URL` and `CLAUDE_TOKEN` in its configuration.

The routine runs in the cloud, so it only works once the app is reachable at its public HTTPS address. Revoking the token stops it.

## Job discovery

The **Discover** page finds internship postings for you. It scans two community lists on GitHub ([SimplifyJobs](https://github.com/SimplifyJobs/Summer2027-Internships) and [vanshb03](https://github.com/vanshb03/Summer2027-Internships)) plus a watchlist of companies whose careers pages run on Greenhouse, Lever, Ashby or Workday. Matches land in the Inbox; Save keeps one, and Apply turns a saved posting into an Applied application. You can also paste any posting link.

Google, Microsoft, Apple, Meta and Amazon use their own careers sites, so they can't be watched. Their internships come in through the community lists, or you can paste a posting.

**Workday** has no official public API. The app uses the endpoint Workday's own career pages call. If Workday changes it, only the scans of your Workday companies fail (the error shows on the Watchlist tab); everything else keeps working.

- **Add a company:** Discover → Watchlist, paste its careers page URL (for example `https://job-boards.greenhouse.io/<company>` or `https://jobs.lever.co/<company>`), and press Add. Its postings arrive with the next scan.
- **Filters** (terms, categories, keywords, locations, sponsorship, scan interval, list URLs) live in **Settings → Job discovery**. Changing them re-sorts existing postings straight away.
- **Scanning:** `docker compose up -d --build` also starts the `job-scan` service, which scans every 6 hours by default. **Scan now** on the Discover page runs one immediately.
- Saved postings are also mirrored to a "Saved postings" tab in the backup sheet. Discovery needs no Google permissions or secrets of its own.

The board formats were written from vendor documentation, because the build environment could not reach those sites. The first real scan is their live check: if a watched company shows an error, compare its response with [`backend/tests/fixtures/discovery/README.md`](backend/tests/fixtures/discovery/README.md).

## Backups

The database lives in the `pgdata` Docker volume. Take a dump regularly (cron, or before every upgrade):

```
docker compose exec -T db pg_dump -U <POSTGRES_USER> <POSTGRES_DB> > backup.sql
```

Restore into an empty database (start only the db first, so the backend has not already created tables):

```
docker compose up -d db
docker compose exec -T db psql -U <POSTGRES_USER> <POSTGRES_DB> < backup.sql
docker compose up -d --build
```

Keep the dump somewhere other than the server. Also keep a copy of `.env` (see below): the dump alone is not enough to use the encrypted data in it.

## Moving to a new server

1. On the old server, take a dump as above.
2. On the new server, clone the repository and copy the old `.env` over **verbatim**. Do not regenerate `JWT_SECRET` or `TOKEN_ENCRYPTION_KEY`: your TOTP secret and the stored Google token are encrypted with `TOKEN_ENCRYPTION_KEY`, and a different key makes them undecryptable. (A changed `JWT_SECRET` just logs you out.) Only change `DOMAIN` and `GOOGLE_REDIRECT_URI` if the hostname changes, and then also update the redirect URI in Google Cloud Console.
3. Start the database and restore the dump as in **Backups**, then `docker compose up -d --build`.
4. Repoint the domain's DNS A/AAAA record at the new server and keep ports 80 and 443 open. Caddy obtains a certificate once DNS resolves to the new host.
5. Log in and check that the Essays page can still load a doc.

**If login returns 500 after a move, the encryption key changed**: `TOKEN_ENCRYPTION_KEY` in the new `.env` is not the one the data was encrypted with. Put the original key back. If it is lost, recreate the account with `docker compose exec backend python -m app.cli create-user --username <you> --reset` and reconnect Google from the Essays page.
