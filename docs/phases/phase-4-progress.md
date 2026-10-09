# Phase 4 Progress Log: Interview Prep

Spec: `docs/superpowers/specs/2026-10-09-interview-prep-design.md`. Plan: `docs/superpowers/plans/2026-10-09-interview-prep-phase4.md`.
Branch `phase-4-interview-prep` from `phase-3-deploy` at `b49f4ec`.

The owner asked on 2026-10-09 for interview prep, Discover inbox ranking and Gmail sync to be built overnight ("i would like for A B and C to all be set up if possible"). The designs use the defaults listed in each spec's §2; the owner reviews them with the PRs.

## Task log

### Task 1: Data model, migration and service core — `3ca4668`
Backend 1610 passed (+73). `alembic check` clean.
Rulings:
- The migration also nulls past `interview_datetime` values after turning them into `done` rounds, so the column matches the derivation rule; downgrade copies them back. Accepted.
- Sheet sync is scheduled by the routes (only they have `BackgroundTasks`), using `ROUND_SYNC_TABS`, plus `CONTACT_TABS` after interviewer linking. Accepted; Task 2 wires it.
- Fixed in passing: `add_company_contacts_item` counted any queue item on the application as a duplicate; it now counts only `company_contacts` items, so a brief request doesn't block Find contacts.
- Test teardown: scratch-database drops retry while autovacuum holds the new database (`tests/scratch_db.py`). Accepted.
- `thank_you_due` is "done, not sent, scheduled within the last 3 days". Accepted.
- Open questions ruled: Upcoming/Past lists hide rounds of archived applications (the per-application list still shows them); newly linking an archived story is rejected (422), already-linked ones stay; Task 3 must make contact ingest refuse `interview_brief` items and keep `/work` explicit about kinds.

Parallel build from here: Tasks 2–4 (backend) run in this checkout; Tasks 5–7 (frontend) run in a worktree on `phase-4-frontend` and are merged back. Phases 5 and 6 start in their own worktrees and test databases.
