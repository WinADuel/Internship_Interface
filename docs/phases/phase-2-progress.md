# Phase 2 (Job Discovery) Progress Log

Recovery map for the build. Each task appends one line: task, commits, test counts, review outcome, rulings.
Plan: `docs/superpowers/plans/2026-10-08-job-discovery-phase2.md`. Spec: `docs/superpowers/specs/2026-10-08-job-discovery-design.md`.

Baseline on `main` (bbc05c3): backend 356 passed (Postgres 16), frontend 232 passed.

- Spec approved by the owner 2026-10-08; plan written.
- Task 1 done: 1c2b56f. Backend 384 passed (+28). Migration 0005 up/down/up and `alembic check` clean. Review (lead, diff read): no Critical/Important. Rulings: FK indexes on postings.application_id/watch_company_id; `state` server_default 'new'; list caps counted after de-dup; list URL must be https with a host; `discovery_list_etags` server-owned (ignored in updates); Python/server defaults share module constants.
