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
