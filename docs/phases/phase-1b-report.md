# Phase 1b Report: Outreach & Contacts

| | |
|---|---|
| **Status** | Complete on branch `phase-1b-outreach`. Waiting for the owner to read this report and merge. Nothing has been merged to `main`. |
| **Built** | 2026-10-06 (Task 1, local) → 2026-10-08 (Tasks 2–15, cloud session) |
| **Branch** | `phase-1b-outreach`, cut from `main` at `d31654f` |
| **Spec** | [`docs/superpowers/specs/2026-10-05-internship-tracker-design.md`](../superpowers/specs/2026-10-05-internship-tracker-design.md) §13 |
| **Plan** | [`docs/superpowers/plans/2026-10-06-outreach-contacts-phase1b.md`](../superpowers/plans/2026-10-06-outreach-contacts-phase1b.md) (15 tasks) |
| **Detailed log** | [`phase-1b-progress.md`](phase-1b-progress.md): one entry per task, with every finding, minor and ruling |
| **Tests at finish** | Backend 356 passing against real PostgreSQL 16 (baseline 189) · Frontend 232 passing (baseline 143) · `svelte-check` 0 errors / 0 warnings · production build clean · Alembic `upgrade` → `downgrade -1` → `upgrade` succeeds and `alembic check` reports no drift |

---

## 1. What Phase 1b delivers

Cold-outreach tracking for **professors** (research positions) and **company contacts** (managers, team leads and recruiters found for each application). A scheduled Claude Code job does the research and writes the drafts. The user sends every email personally; the app never sends mail.

- **Contacts page.**
  - A kanban board by status, filtered by Professors, Company or All.
  - Cards show title, an email-confidence badge (found, guessed or none), "Draft ready" and a nudge badge.
  - One-tap status buttons, with an optional "It was actually on…" date and a meeting time for Meeting set.
  - Every status button can be undone for 60 seconds.
- **Contact detail panel.**
  - Research summary, recent work, and sources shown as safe links.
  - Editable first-contact and follow-up drafts, with **Open in Gmail** (warns first when the address is a guess) and **Copy**.
  - "Did you send it?" → **Sent** when the user comes back from Gmail.
  - Status timeline, notes and Archive.
- **Research Queue page.**
  - Ask for a specific professor or give a search brief with a count.
  - See pending, done and failed items, with Claude's note on each.
- **Applications.**
  - Marking an application **Applied** automatically queues a search for company contacts, exactly once per application.
  - The application panel gains a **Contacts** section and a **Find contacts** button.
- **Dashboard.**
  - A **Needs attention** widget offers the right buttons for each nudge:
    - "Did you send this?";
    - "Follow-up due";
    - "Gone quiet";
    - "Replied — reply back?";
    - "How did it go?".
  - Recent activity now merges application and contact changes.
- **Settings page.**
  - Outreach profile, which Claude uses to personalize drafts.
  - The four nudge timings and the per-run item limit.
  - Claude tokens: create (shown once), list by prefix with last use, revoke.
  - Backup-sheet status: link, last sync, last error, **Sync now**, and **Connect Google** when needed.
- **Claude job API (`/api/claude/*`).** A narrow, token-authenticated interface for the daily routine:
  - read the work list;
  - post contacts in batches;
  - post follow-up drafts;
  - complete or fail queue items.
- **Routine instructions.** [`ops/claude-routine/outreach-job.md`](../../ops/claude-routine/outreach-job.md) is the complete brief for the daily Claude Code routine. Its appendix tells the owner how to schedule it.
- **Backup Google Sheet.**
  - A one-way mirror ("Internship Tracker Backup", with Applications, Professors and Company Contacts tabs) in the user's Drive, using the `drive.file` scope.
  - It re-syncs after every write and nightly via a new `sheet-sync` Compose service.
  - A sync failure never blocks or rolls back the user's edit.

## 2. Architecture additions

```
Daily Claude Code routine (cloud, user's plan)
        │  HTTPS, Authorization: Bearer ct_…
        ▼
     Caddy ── /api/* (5 MB body cap) ──► FastAPI
                                           ├─ /api/claude/*   (get_claude_token only; cookies ignored)
                                           ├─ /api/contacts, /api/research-queue, /api/settings  (session cookie)
                                           └─ BackgroundTasks ─► sheet sync ─► Google Sheets API (drive.file)
     sheet-sync service (Compose) ── nightly full re-sync
```

- **Migration `0004_outreach_contacts`** adds five tables:
  - `contacts`;
  - `contact_status_history`;
  - `research_queue`;
  - `app_settings`, a single row enforced by `CHECK (id = 1)`;
  - `claude_tokens`, which stores only the SHA-256 hash, never the token.

  It also adds six enums. `contacts.priority` reuses Phase 1's `application_priority` enum.
- **Backend services:**
  - `contact_service`, with the status-button table in `contact_transitions`;
  - `nudges`, a pure function;
  - `settings_service`;
  - `research_queue_service`;
  - `claude_token_service`;
  - `claude_ingest_service`;
  - `sheet_sync_service`, behind a `SheetsClient` protocol with a fake for tests;
  - `app/jobs/nightly_sheet_sync.py`.
- **Frontend:**
  - API clients that use a generic snake/camel case converter;
  - a shared contacts store and a shared undo-deadline store;
  - components under `lib/components/contacts`, `lib/components/settings` and `widgets/NeedsAttention`;
  - routes `/contacts`, `/research-queue` and `/settings`.

## 3. How it was built

Task 1 was built locally. The owner then moved Tasks 2–15 to a cloud session (`docs/phases/phase-1b-cloud-handoff.md`).

Every task followed the same steps:
1. Test-driven implementation.
2. The task's own tests, plus the full suite (backend against real Postgres 16), plus `svelte-check` and the build for frontend work.
3. A commit.
4. A **fresh reviewer subagent** that reported Critical, Important and Minor findings.
5. Fixes for every Critical and Important finding, and for cheap Minors.
6. A secret check, then a push to `phase-1b-outreach`.

After Task 15, a whole-branch review ran in two halves, backend and frontend, followed by one fix round.

### Task log

| # | Task | Commits | Review outcome |
|---|---|---|---|
| 1 | Outreach data models & migration 0004 | `8b1e817` | Important 1: evidence of the migration cycle requested and supplied, no code change |
| — | Cloud setup: ignore passlib's `crypt` DeprecationWarning | `1189ab5` | Needed for the suite to import on Linux / Python 3.12 |
| 2 | Contact service (actions, undo, snooze, history) | `4b5e931` | Clean |
| 3 | Nudges & app settings | `8a957f3`, `0c95ef4` | Clean; one test strengthened |
| 4 | Research queue & auto-enqueue on applied | `9c00078`, `d4cf5c5` | Important 1 fixed: the status change and its queue item now commit together |
| 5 | Contacts, research-queue & settings routes | `63e737c` | Clean |
| 6 | Claude tokens & auth boundary | `b71d69a` | Clean (security-focused review) |
| 7 | Claude job API | `dc9ef0d`, `e360cdd` | Important 2 fixed: single-address email only; drafts are never refreshed after sending |
| 8 | Backup Google Sheet sync | `e40489a`, `5ecc770` | Important 1 fixed: old Google tokens get a "reconnect Google" hint |
| 9 | Frontend types, API clients, store, helpers | `9fbc02d` | Clean; every field checked against the backend schemas |
| 10 | Contact card, status buttons & board | `e85887f`, `b56af1a` | Clean; three cheap Minors fixed |
| 11 | Contact detail panel & draft editor | `a09c5ea`, `e2471cb` | Important 2: 1 fixed (newer server drafts load unless edited), 1 ruled |
| 12 | Contacts & Research Queue pages, navigation | `1bc63aa`, `d7cab1f` | Clean; one Minor fixed |
| 13 | Needs Attention, merged activity, application contacts | `038bdaf`, `803ec29` | Important 3 fixed: Undo from the widget, panel moved out of the drag handle, company wording in the feed |
| 14 | Settings page | `43325d9`, `df05119` | Important 1 fixed: the token plaintext is also cleared on `pagehide` |
| 15 | Routine instructions & end-to-end job contract test | `d298b19`, `099a387` | Important 4 fixed: UTC nudge dates; token sent only to the app; 422 retry per contact; user data kept out of web requests |
| — | Whole-branch review fix round | `169a450`, `ebc4d50` | No Critical or Important findings; Minors fixed (see §5) |

Progress-log commits (`docs: Phase 1b progress log …`) sit between the tasks and are not listed.

### Work added beyond the plan

| Addition | Commits | Why |
|---|---|---|
| `pytest.ini` ignore for passlib's `crypt` warning | `1189ab5` | With `filterwarnings = error`, the backend suite could not even import on Linux / Python 3.12. This probably also explains red backend CI on `main` (inferred, not confirmed from CI logs). |
| `get_sheets_client_factory` dependency and a test-wide sync-scheduler override | `e40489a` | Lets Sync now run against a fake client in tests, and stops background syncs from opening a second DB connection during tests. |
| "Reconnect Google" hint on Sheets 401/403 | `5ecc770` | Google connections made in Phase 1 have only `drive.readonly`, so syncs would otherwise fail with a bare 403. |
| `ApplicationContacts.svelte` component and `lib/actions/portal.ts` | `038bdaf`, `803ec29` | Keeps the application panel small, and moves the follow-up slide-over out of GridStack's drag handle. |
| `nudges.utc_today()` used by every caller | `099a387` | The server's local date (compose `TZ=America/Chicago`) was compared with the UTC dates of stored timestamps, so nudges and follow-up drafts were a day late for part of each day. |
| README section on the backup sheet and the Claude job | `e29b5dc` | The owner must enable the Google Sheets API and reconnect Google once. Neither step was documented. |
| Caddy 5 MB request-body cap on `/api/*` | `ebc4d50` | FastAPI parses a body before auth runs, so an anonymous caller could send arbitrarily large bodies. |
| Browser smoke run | (no commit; see the progress log) | Replaces the plan's manual `npm run dev` check (Task 12). |

## 4. Quality & security

- **Tests.**
  - 167 new backend tests (356 total) and 89 new frontend tests (232 total).
  - Every item in spec §13.9 is covered:
    - dedup matching;
    - Claude never overwriting edited drafts or user-owned fields;
    - valid and invalid transitions (invalid → 422 with no history row);
    - nudges as a pure function over a fixed "today", including snooze;
    - token scoping in both directions, including revoked tokens;
    - auto-enqueue happening exactly once;
    - sheet sync through a fake client, including "sync failure doesn't break the write";
    - non-http(s) URLs dropped;
    - Gmail URL encoding and the guess warning;
    - contact content rendered as text.
- **End-to-end contract test** (`backend/tests/api/test_claude_job_flow.py`).
  - It walks the documented job through the real API with a real token: queue, work list, post contacts, complete items, backdate a send, follow-up listed, post follow-up, final DB state.
  - It also passes under `TZ=Etc/GMT+12` and `Etc/GMT-14`.
- **Browser smoke run.**
  - Ran on real uvicorn, Postgres, the Vite dev server and headless Chromium.
  - Covered: login with TOTP; save the profile; create and dismiss a token; Sync now shows "google not connected" with Connect Google; queue a professor; create an applied application; act as the Claude job with the token; the contact panel shows an `<img onerror>` payload as literal text and drops a `javascript:` source; Sent shows Undo; the application panel lists its company contact; the dashboard shows Needs attention and merged activity.
  - No page errors.
- **Claude token boundary.**
  - `/api/claude/*` reads only `Authorization: Bearer`, and its router-level dependency guards every route.
  - Cookie routes never read the header.
  - Tokens are 256-bit random values with a `ct_` prefix. Only the SHA-256 hash is stored.
  - A revoked token and an invalid token get the same 401.
  - The plaintext appears only in the create response. In the UI it is cleared on Done, on navigation and on `pagehide`. A token that arrives after the user has navigated away is revoked at once.
- **Untrusted content** (everything Claude sends comes from arbitrary web pages):
  - every string is stripped, NUL-free and length-capped;
  - batches are capped at 25 and sources at 20;
  - URLs must be `http`/`https`;
  - an email must be exactly one plain address;
  - a "found" email with no surviving source is downgraded to a guess;
  - drafts and the email address are settled once the first email is sent, and only research fields are ever refreshed;
  - the frontend never uses `{@html}`, checks links with `isSafeHttpUrl`, and leaves Gmail's `to=` empty unless it holds a single plain address;
  - sheet writes use `RAW`, so no formulas.
- **Routine instructions** (`outreach-job.md`):
  - public sources only;
  - no logins and no LinkedIn scraping;
  - web content is data, not instructions;
  - the token goes only to `$APP_BASE_URL` over https;
  - `outreach_profile`, `known_contacts` and drafts never go into web requests;
  - a guess is never presented as found.

## 5. Final whole-branch review

Two fresh reviewers split `git diff origin/main...HEAD` into a backend half and a frontend half, focusing on security, cross-task contracts, frontend↔backend field names and the migration.

- **Result: no Critical or Important findings** in any area.
- **Checks the reviewers ran or confirmed:**
  - every client path, method, query parameter, field and enum matches the backend;
  - migration 0004 matches the models;
  - `downgrade -1` drops exactly the new tables and enums and keeps `application_priority`;
  - `alembic check` is clean;
  - the Claude token cannot reach any non-Claude route.
- **The fix round** (`169a450`, `ebc4d50`) took the cheap Minors:
  - Draft editor: text typed while a save is in flight is no longer replaced by the saved copy.
  - Needs Attention: Undo stays available when an acted-on contact stays listed under a different nudge. The panel is keyed by contact, so button state can't leak between contacts.
  - Gmail links drop a `to` that isn't a single plain address.
  - A matched contact's email can't be replaced once the user has emailed them. This blocks a hostile page from redirecting the follow-up.
  - Nudge dates use the UTC date whatever zone a timestamp carries, so a non-UTC DB session can't bring back the off-by-one.
  - Contacts whose follow-up the user cleared are no longer offered to Claude every day.
  - The first sync fills every tab.
  - A company contact who matches an existing unlinked contact is linked to the application.
  - Caddy caps API bodies at 5 MB.
- **Re-verified afterwards:** backend 356, frontend 232, check 0/0, build, and the Alembic cycle with `alembic check`.

## 6. Decisions and trade-offs (all rulings)

Each ruling: decision — why — cost if wrong.

**Data and backend**

- `contacts.priority` reuses the PG enum `application_priority` (declared with `create_type=False`) — the as-built corrections say so, and `create_all` sees one type — cost if wrong: none at runtime.
- `research_queue.application_id` is `ON DELETE SET NULL`, mirroring `contacts` — the spec is silent, and applications are archived rather than deleted — cost if wrong: an orphaned queue item could survive a hard delete.
- `app_settings` has `CHECK (id = 1)` — enforces the single-row design in the DB — cost if wrong: none.
- Migration 0004 was applied only to test DBs, never to the local dev DB — `main` has no 0004 until merge — cost if wrong: the dev DB needs `alembic upgrade head` after merge.
- `pytest.ini` ignores only passlib's exact `crypt` DeprecationWarning — import-time noise from a pinned dependency — cost if wrong: none.
- Creating or updating a contact with an unknown `application_id` → 422 `application not found`, not a 500 from the FK — cost if wrong: none.
- `ContactActionIn.on` and `meeting_at` are `AwareDatetime` (a naive value → 422) — naive values would 500 in the undo and nudge comparisons — cost if wrong: clients must send an offset (the frontend sends `Z`).
- `AlreadyQueuedError` counts queue items in any state — the plan says "any state" — cost if wrong: Find contacts can't be re-run after a failed item.
- `revoke_token` is idempotent, and an unknown id → 404 — cost if wrong: none.
- The `Bearer` scheme matches case-insensitively (RFC 7235) — cost if wrong: none.
- A re-delivery that omits a field never erases a known value. Email and confidence change together only when a new valid email arrives — the spec lets Claude update research fields, not wipe them — cost if wrong: a stale value Claude meant to retract survives until the user edits it.
- On a match, Claude never changes `name` or `organization` — they identify the person and are not research fields — cost if wrong: none.
- *(whole-branch round)* A matched contact's email is refreshed only while it is `to_contact` — same reasoning as drafts; stops a hostile page redirecting the follow-up — cost if wrong: a genuinely changed address must be edited by the user after the first send.
- *(whole-branch round)* A matched, unlinked company contact gets the item's `application_id` — so it shows in that application's Contacts section — cost if wrong: a contact found for one role shows under that role's application.
- `GOOGLE_SCOPE` is the space-joined pair `drive.readonly drive.file` — cost if wrong: none.
- Added `get_sheets_client_factory`, and the test `client` fixture overrides the sync scheduler — makes Sync now testable and avoids a second DB connection in tests — cost if wrong: none.
- `sync_tabs` commits `backup_sheet_id` as soon as the sheet is created, and `safe_sync` rolls back before recording an error — cost if wrong: none.
- Nudge "today" is the UTC date — stored timestamps are compared by their UTC date — cost if wrong: for a Chicago user a nudge can appear around 7 pm the evening before, rather than at midnight; early, never late.

**Frontend**

- A small generic snake/camel key converter (`lib/api/case.ts`) instead of hand-written field maps — fewer places to drift — cost if wrong: a field with a digit after an underscore would map lossily (none exist).
- Cards open through an `onopen` callback prop, from a button on the name — Phase 1's pattern; avoids nested buttons — cost if wrong: none.
- One shared, collapsed "It was actually on…" date input per button group — less clutter — cost if wrong: cosmetic.
- Undo deadlines live in a shared store — Undo survives a card changing columns — cost if wrong: none.
- "Did you send it?" is offered only while the matching action is valid — otherwise Sent would just 422 — cost if wrong: re-opening Gmail on an already-sent draft shows no prompt.
- The application Contacts section is its own component, with read-only compact cards and an "Open in Contacts" link — keeps the application panel small — cost if wrong: one extra click to reach a contact.
- Feed lines read "Moved {company — role} to X" and "{name (org)}: {status}" — so the two sources are distinguishable — cost if wrong: cosmetic.
- The Connect Google link also shows for the "reconnect Google" error — cost if wrong: none.
- The plan's manual `npm run dev` check was replaced by one scripted browser smoke run after Task 14 — it covers more and is repeatable — cost if wrong: none.

## 7. Known limitations

- **Not verified on a real server:**
  - the Google Sheets round trip with a real Google client;
  - the scheduled routine against the deployed app;
  - the Docker build of the new `sheet-sync` service and the Caddy body-cap directive. The cloud session had no Docker daemon or Caddy binary to build or validate with; `docker compose config` parses.
- **Main's CI is probably red** because of the passlib `crypt` warning (inferred). The fix (`1189ab5`) arrives with this merge.
- **Logged Minors not fixed.** Each is listed in the progress log. The ones the owner may notice:
  - One application-per-queue-item is check-then-insert with no unique index. A simultaneous Find contacts click and auto-enqueue could double-insert; unlikely for one user.
  - A sheet or tab deleted in Drive is never recreated. Syncs fail until `backup_sheet_id` is cleared. Two simultaneous first syncs could each create a sheet.
  - Very long user text (over 50,000 characters in one cell) would make sheet syncs fail until edited.
  - The number of contacts Claude can attach to one pending queue item is not capped.
  - The Google OAuth callback always returns to the Essays page. Settings says to come back and press Sync now.
  - Undo doesn't restore a snooze that the undone action cleared. Snooze and Skip have no undo.
  - Switching contacts discards unsaved draft edits without a prompt.
  - Token-create responses lack `Cache-Control: no-store`.
  - The Claude routes return 401 without `WWW-Authenticate: Bearer`.
- **Out of scope by design:** sending email from the app; restoring from the backup sheet; a Gmail permission; Claude API billing (the job runs on the user's Claude plan).

## 8. What's next — what the owner must do

**To merge.** Read this report, then merge `phase-1b-outreach` into `main` (spec §11b). Nothing on the branch touches `main`.

**To deploy** (see the README section "Outreach: backup sheet and the daily Claude job"):

1. `git pull` on the server and `docker compose up -d --build`. Migration `0004` runs automatically before the backend starts. The new `sheet-sync` service starts alongside it.
2. In Google Cloud Console, enable the **Google Sheets API** for the existing project.
3. Reconnect Google once, from **Settings → Backup sheet → Connect Google** or from the Essays page, to grant `drive.file`. Then press **Sync now**.
4. In **Settings**, write your **outreach profile**, and adjust the nudge timings and max items per run if you like.

**To schedule the daily Claude job** (the plan's post-deployment step; deliberately not done here):

1. Confirm `https://<your-domain>/api/health` responds from the internet.
2. **Settings → Claude tokens → Create token**, and copy it. It is shown once.
3. In Claude Code, use the `schedule` skill to create a routine that:
   - runs **daily at 07:00** local;
   - uses `ops/claude-routine/outreach-job.md` as its instructions;
   - stores `APP_BASE_URL` and `CLAUDE_TOKEN` in its configuration, never in the repo;
   - is allowed web search and web fetch.
4. Run it once by hand, and check that Research Queue items move to Done and contacts appear.
5. To stop or rotate it, revoke the token in Settings.

**Later phases:** job discovery, interview prep, email sync and CD remain out of scope (spec §12).
