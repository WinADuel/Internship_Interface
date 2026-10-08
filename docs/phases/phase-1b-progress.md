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
- **Cloud session setup (2026-10-08).** Fresh Linux container: Python 3.12 venv, Postgres 16 via apt (`app`/`app`, `internship_tracker_test`), Node 22. Baselines reproduced: backend 195 passed, frontend 143 passed, check 0/0, build clean.
  - Commit `1189ab5` "test: ignore passlib's stdlib crypt deprecation warning on Linux": on Linux Python 3.12 passlib imports the deprecated `crypt` module, and `filterwarnings = error` turned that into a conftest import error (likely also why backend CI is red on `main`; inferred, not confirmed from CI logs).
  - Ruling: ignore only that exact third-party warning in `pytest.ini` — it is import-time noise from pinned passlib, not our code — cost if wrong: none; the filter is message-specific.
- **Task 2: Contact service.** DONE. Commit `4b5e931`. Tests: 22 new (transitions + service); full backend 217 passed (Postgres 16). Review (fresh reviewer subagent): Critical none, Important none.
  - Minor, logged not fixed: undo does not restore `nudge_snoozed_until` cleared by the action; undo doesn't assert `status == last.new_status`; `move_status` rejection test doesn't assert no history row; clearing a draft (explicit null) marks it edited, blocking a Claude redraft; no unarchive path (matches plan).
  - Minor, deferred to Task 5: naive `now`/`on`/`meeting_at` would raise TypeError — Task 5's request schemas require timezone-aware datetimes.
  - Ruling: `create_contact`/`update_contact` reject an unknown `application_id` with `ApplicationNotFoundError` instead of letting the FK raise a 500 — cost if wrong: none.
- **Task 3: Nudges & app settings.** DONE. Commits `8a957f3`, `0c95ef4` (review fix: strengthen the replied-stale DB test). Tests: 23 new; full backend 240 passed (Postgres 16). Review (fresh reviewer subagent): Critical none, Important none.
  - Minor, logged not fixed: `get_settings` commits on first read and two simultaneous first reads could race on `id=1` (single user, low risk); nudge day boundaries use the UTC date of stored timestamps vs. the caller's `today` (routes pass `date.today()` as the plan says); `list_needs_attention` DB tests live in `test_settings_service.py`; `schemas/contact.py` imports `services/nudges.py` (no cycle today).
- **Task 4: Research queue & auto-enqueue on applied.** DONE. Commits `9c00078`, `d4cf5c5` (review fix). Tests: 11 new; full backend 251 passed (Postgres 16). Review (fresh reviewer subagent): Critical none, Important 1 — fixed.
  - Important (fixed in `d4cf5c5`): the status change was committed before the enqueue, so a DB error during enqueue would leave the status saved with no queue item and a 500. Now `add_company_contacts_item` flushes only, and `create_application`/`change_status` commit once after it.
  - Minor, logged not fixed: one-item-per-application is check-then-insert with no unique index (a simultaneous auto-enqueue and Find contacts click could double-insert; single user, unlikely); `complete_item`/`fail_item` default clock and `fail_item` on an unknown id untested; duplicate `_now()` helper.
  - Ruling: `AlreadyQueuedError` counts items in any state, including done/failed — the plan says "any queue item (any state)" — cost if wrong: a user can't re-run Find contacts after a failed item.
- **Task 5: Contacts, research queue & settings routes.** DONE. Commit `63e737c`. Tests: 33 new route tests; full backend 284 passed (Postgres 16). Review (fresh reviewer subagent): Critical none, Important none.
  - Ruling: `ContactActionIn.on`/`meeting_at` are `AwareDatetime` (naive → 422) — stored timestamps are aware and naive values would raise TypeError (500) in undo/nudge comparisons; the frontend sends `toISOString()` (Z) — cost if wrong: a client sending naive datetimes must add an offset.
  - Ruling: an unknown `application_id` on contact create/PATCH → 422 `{"detail": "application not found"}` (plan silent; §10 error contract) — cost if wrong: none.
  - Minor, logged not fixed: list reads group the whole history table for nudges (one query, scales with all contacts); `find-contacts` router fetches the application itself; `/needs-attention` builds `ContactOut` separately from `_out`; `date.today()` is server-local while timestamps are UTC (matches plan text); undo-expiry route test backdates via the shared test session.
- **Task 6: Claude tokens & auth boundary.** DONE. Commit `b71d69a`. Tests: 20 new (service + boundary); full backend 304 passed (Postgres 16). Review (fresh security-focused reviewer subagent): Critical none, Important none.
  - Ruling: `revoke_token` is idempotent (keeps the first `revoked_at`) and an unknown id → 404 `{"detail": "claude token not found"}` — cost if wrong: none.
  - Ruling: the `Bearer` scheme is matched case-insensitively (RFC 7235) — cost if wrong: none.
  - Minor, logged not fixed: token-create response lacks `Cache-Control: no-store`; 401 lacks `WWW-Authenticate: Bearer`; `authenticate` commits `last_used_at` inside the dependency (separate from the route's transaction, harmless); no structural test walking `app.routes` to pin which dependency guards each router; `/api/docs/*` not pinned against a Claude bearer token.
- **Task 7: Claude job API.** DONE. Commits `dc9ef0d`, `e360cdd` (review fixes). Tests: 26 new (service + routes), boundary tests moved from `/ping` to `/work`; full backend 330 passed (Postgres 16). Review (fresh security-focused reviewer subagent): Critical none, Important 2 — both fixed.
  - Important (fixed): the email field accepted any text, so a hostile page could get `a@uni.edu, attacker@evil.com` or `x@y.com?bcc=…` into the Gmail compose `to=`. Now only one plain address is kept; anything else is dropped and confidence becomes `not_found`. Dedup matches on the sanitized email.
  - Important (fixed): an unedited draft was refreshed even after the contact was sent, overwriting the record of what went out (and the basis of the follow-up). Drafts now refresh only while `status == to_contact`.
  - Minor (fixed, cheap): a re-delivered body without a subject no longer clears the subject; NUL bytes are stripped (Postgres would 500); follow-ups apply only to non-archived `sent` contacts.
  - Minor, logged not fixed: re-delivering the same FOUND email without sources downgrades it to PATTERN_GUESS even though stored sources remain, and a guess can replace a FOUND email; `QueueItemOut` from complete/failed includes `application_id`; `date.today()` is server-local; no test for an archived contact matched by email.
  - Ruling: a re-delivery that omits a field (None, empty sources, no email) never erases a known value; email and confidence change together only when a new valid email arrives — the spec lets Claude update research fields, not wipe them — cost if wrong: a stale value Claude meant to retract survives until the user edits it.
  - Ruling: on a match Claude does not change `name`/`organization` (identity, not a §13.2 research field) — cost if wrong: none.
- **Task 8: Backup Google Sheet sync.** DONE. Commits `e40489a`, `5ecc770` (review fix). Tests: 20 new (service, hooks, nightly job) plus a scope assertion; full backend 350 passed (Postgres 16). `docker compose config` (with `.env.example` copied to a temporary `.env`) parses and lists `sheet-sync`. Review (fresh reviewer subagent): Critical none, Important 1 — fixed.
  - Important (fixed): a Google connection made before this change has only `drive.readonly`, so every sync would fail with a bare "status 403". A 401/403 from Sheets now adds "reconnect Google to grant the drive.file permission"; Settings (Task 14) shows the Connect Google link for it.
  - Minor, logged not fixed: two simultaneous first syncs could each create a sheet (one orphaned in Drive); a sheet or tab deleted in Drive is never recreated (every sync fails until `backup_sheet_id` is cleared); nudges in the sheet use `date.today()`, not `now`; any `GoogleAuthError` (including a failed refresh) reads "google not connected" (plan's exact string); overlapping syncs can briefly leave an older snapshot until the nightly run; a non-Sheets exception's text (up to 300 chars) is stored in `last_sheet_sync_error`; compose `TZ` repeats `env_file`.
  - Ruling: `GOOGLE_SCOPE` is now the space-joined pair `drive.readonly drive.file` (the value stored with the token) — cost if wrong: none.
  - Ruling: added a `get_sheets_client_factory` dependency so "Sync now" is testable with a fake client, and the test `client` fixture overrides the scheduler for every test (the real one would open a second DB connection and could block on the test transaction) — cost if wrong: none.
  - Ruling: `sync_tabs` commits `backup_sheet_id` right after creating the sheet so a later tab failure can't orphan it; `safe_sync` rolls back before recording an error — cost if wrong: none.
- **Task 9: Frontend contact types, API clients, store & helpers.** DONE. Commit `9fbc02d`. Tests: 14 new; frontend 157 passed, check 0/0. Review (fresh reviewer subagent): Critical none, Important none; every camelCase field verified against the backend schemas.
  - Ruling: the clients use a small generic snake/camel key converter (`lib/api/case.ts`) instead of hand-written field maps — fewer places to drift; the full-object `toEqual` mapping test locks `Contact` — cost if wrong: a future field with a digit after an underscore would map lossily (noted in the file's review; none exist).
  - Minor, logged not fixed: `keysToCamel` copies unknown keys through a cast; queue/settings/token types lack a full-object mapping test; `addQueueItem` builds its body by hand; `includeArchived`, `findContacts`, `listQueue(state)`, `syncSheetNow` untested (simple).
