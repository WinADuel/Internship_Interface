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

### Tasks 2–4: routes, calendar export, Claude brief, Interviews tab — `6ea6d94`, `84534fe`, `4c657f2`
Backend 1696 passed. Rulings:
- The `.ics` prep-page link uses the origin of `GOOGLE_REDIRECT_URI` (there's no app-URL setting, and behind Caddy the backend sees plain http). A round with no time gives 409 on the calendar route.
- `ROUND_SYNC_TABS` moved to `sheet_sync_service` to avoid an import cycle. The Interviews tab writes UTC ISO times and includes archived applications' rounds (it's a backup).
- The brief GET returns 404 when there is no brief yet (as specified); the prep page shows "Requested" from the pending research-queue item. The browser logs the 404 as a console error; accepted.

### Tasks 5–7: frontend — `4ca76c1`, `c1f5796`, `0ee591c` (worktree branch `phase-4-frontend`, merged in `64eb18f`)
Frontend 513 passed. Rulings:
- One **Mark sent** per round (the round has a single `thank_you_sent_at`); each interviewer gets their own **Draft thank-you**. Accepted.
- The create form keeps an interview date field (the backend turns it into the first round); the edit form shows **Next interview** read-only. Accepted.
- Prep notes autosave is new code (contact drafts use a Save button): 1 s after typing stops, on blur and on leaving. Accepted.
- An extra **Add round** on the Interview Prep page with an application picker. Accepted.

### Task 8 (part 1): end-to-end walk and docs — `d01bfbf`, `b74fd17`
The merged frontend and backend were walked together in headless Chromium against a scratch database: rounds, prep page autosave across reloads, stories, interviewers, brief request → simulated routine post → brief rendered as text (a `<b>` tag shown literally, a `javascript:` source dropped), `.ics`, thank-you due and Mark sent, Dashboard widget, 390 px. One bug found, pre-existing: a contact created with a typed email was stored as "email not found". Fixed in `ContactCreate`.

### Review — fixes `75067f9`, `f04e08e`
Backend reviewer: 1 Important, 4 Minor; frontend reviewer: 1 Important, 6 Minor. All fixed with tests that fail on the old code:
- Important: the 0007 downgrade left `interview_brief` rows that Phase 3 code can't load (500 on the research queue). The downgrade now deletes them.
- Important: an older save response could replace the round and undo a newer checklist tick. Round writes now go through one request-ordered `write()`; stale answers are dropped.
- Row locks (`FOR NO KEY UPDATE` on the application, so concurrent round creates can't deadlock) for the derived `interview_datetime` and the one-pending-brief rule; the brief ingest locks the queue item (a concurrent duplicate gets 409, not 500).
- PATCH re-syncs the sheet only when an exported field changes (autosaves no longer trigger a sync).
- The prep page is keyed on the round id; autosave runs through one loop; outcome select resets on a failed save; an over-long thank-you draft offers Copy instead of failing silently; a failed interviewer link retries without creating a duplicate contact; countdowns tick every minute; a deleted round says so.
Final: backend 1711 passed, `alembic check` clean; frontend 527 passed, `svelte-check` 0/0, build clean.
