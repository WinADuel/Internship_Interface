# Phase 3 (Server Deploy) Progress Log

Recovery map for the build. Each task appends one line: task, commits, test counts, review outcome, rulings.
Plan: `docs/superpowers/plans/2026-10-08-server-deploy-phase3.md`. Spec: `docs/superpowers/specs/2026-10-08-server-deploy-design.md`.

Baseline on `main` (af2fd16): backend 1171 passed (Postgres 16), frontend 389 passed.

- Owner choices 2026-10-08 (decision cards): Phase 3 = server deploy; hosting DigitalOcean; domain = buy a .com. Owner said "set up phase 3" on the design (approval); plan written.
- Sandbox notes: Docker daemon can be started (`dockerd`), Docker Hub pulls work but can hit 429 rate limits; `shellcheck` installed in the venv (shellcheck-py); a Caddy 2.10.2 binary is in the session scratchpad for `caddy validate`.
- Task 1 done: 5675593. 11 new tests (compose file parsed with pyyaml); backend 1182 passed; `docker compose config -q` passes. Review (lead, diff read): no Critical/Important. Rulings: base image pinned to `python:3.12-slim-bookworm` (plain `3.12-slim` moved to trixie, which would not match the `bookworm-pgdg` suite); PGDG key fetched over HTTPS without a gpg fingerprint check (as PGDG docs describe; adding gpg isn't worth the layer); healthcheck via urllib (raises on non-2xx). Not verifiable here: the sandbox blocks apt.postgresql.org/deb.debian.org, so the image build and `pg_dump --version` = 16 move to the Task 8 CI job (GitHub runners build the image) and the Task 9 smoke test uses a sandbox-only build variant.
