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
