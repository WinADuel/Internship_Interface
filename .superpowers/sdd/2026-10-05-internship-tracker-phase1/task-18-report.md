# Task 18 report
Implemented: backend/Dockerfile (python:3.12-slim, alembic upgrade head then uvicorn), frontend/Dockerfile (node:20 build -> caddy:2 with dist in /srv), .dockerignore x2, docker-compose.yml (db with healthcheck and no published ports, backend, caddy 80/443 + volumes), Caddyfile (handle /api/* -> backend:8000, else file_server), .env.example, root .gitignore (.env), README Deploying section.
Verification (project itverify, temp override mapping Caddy to 18080/18443, temp .env DOMAIN=localhost; both deleted):
- curl -sk https://localhost:18443/api/health -> {"status":"ok"}
- curl -sk https://localhost:18443/ -> contains <div id="app"></div>
- docker compose -p itverify exec backend python -m app.cli --help -> usage with create-user
- Cleanup: docker compose -p itverify ... down -v; docker ps afterwards shows internship-tracker-test-db and odysseus-* still running.
Self-review: db not published; secrets only in .env (ignored). Redirect URI uses /api/docs/google/callback (matches route; backend/.env.example's oauth/callback is stale).
Concerns: first verification run had empty secrets (system python missing) and was fixed by recreating backend; real ACME HTTPS not tested (localhost uses internal CA). Backend/.env.example redirect URI stale.
