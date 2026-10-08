# Phase 1b Progress Log

Recovery map for Phase 1b (Outreach & Contacts) on branch `phase-1b-outreach`. There is one line per task. Resume at the first task that has no completed line here.

Plan: `docs/superpowers/plans/2026-10-06-outreach-contacts-phase1b.md`. Spec: §13 of `docs/superpowers/specs/2026-10-05-internship-tracker-design.md`.

**Baseline** (branch cut from `origin/main` at `d31654f`): backend 189 passed (pytest against Postgres 16), frontend 143 passed, `svelte-check` 0 errors / 0 warnings, build clean.

## Task log

- **Task 1: Outreach data models & migration.** DONE.
  - Commit: `8b1e817`.
  - Tests:
    - Task 1 tests: 6 passed (`tests/models/test_outreach_models.py`).
    - Full backend suite: 195 passed against real Postgres 16.
  - Migration 0004: `alembic upgrade head`, `downgrade -1` and `upgrade head` all succeed. `alembic check` reports "No new upgrade operations detected".
  - Review (fresh reviewer subagent): Critical none; Important 1.
    - The Important finding asked for evidence that the migration cycle and drift check had run. They had (results above), and no code change was needed.
  - Minor findings, logged and not fixed:
    - The enum columns have only Python-side defaults, with no DB server default. This matches the Phase 1 pattern.
    - Missing tests:
      - `research_queue.application_id` SET NULL;
      - the `app_settings` id=1 CHECK;
      - the raw-SQL server defaults of `followup_edited`, `target_count` and `app_settings`.
    - `app_settings.id` has no `server_default`.
  - Ruling: `contacts.priority` reuses the PG enum `application_priority`.
    - Why: the as-built corrections say so. The migration declares it with `create_type=False` and neither creates nor drops it. The model uses the same `enum_column(Priority, "application_priority")` helper, so `create_all` in the tests sees a single type.
    - Cost if wrong: none at runtime; a cosmetic difference in the model declaration.
  - Ruling: `research_queue.application_id` uses `ondelete="SET NULL"`, mirroring `contacts`.
    - Why: the spec is silent, applications are archived rather than deleted, and keeping queue history is harmless.
    - Cost if wrong: an orphaned queue item could survive a hard-deleted application.
  - Ruling: `app_settings` has a `CHECK (id = 1)` constraint.
    - Why: it enforces the single-row design at the DB level.
    - Cost if wrong: none.
  - Ruling: migration 0004 was applied only to the test DB, not to the local dev DB `internship_tracker`.
    - Why: `main` has no 0004, so a migrated dev DB would break the `main` checkout until merge.
    - Cost if wrong: the dev DB needs `alembic upgrade head` after merge.
  - Environment: local Windows worktree, Python 3.12, Postgres 16 in the Docker container `internship-tracker-test-db`, Node 24 (CI uses 22).
- **Handoff.** The owner moved Tasks 2–15 to a fresh cloud session. Instructions are in `docs/phases/phase-1b-cloud-handoff.md`. Task 2 was not started: no Task 2 code or tests are committed.
