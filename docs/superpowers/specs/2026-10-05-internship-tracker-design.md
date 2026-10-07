# Internship/Job Application Tracker — Phase 1 Design

**Date:** 2026-10-05
**Status:** Approved for planning
**Scope:** Phase 1 only (core tracker, dashboard, cross-device access, essay-prompt helper, Google Docs linking). Later phases (job discovery, interview prep, email sync) are explicitly out of scope for this spec and will each get their own design document.

## 1. Goals & Context

The user wants a personal, always-reachable system to track internship/job applications and their status, usable from phone, MacBook, and Windows PC — including when away from home Wi-Fi. It must be built so it can migrate cleanly onto a self-hosted local server in the future, and the stack should be resume-relevant for AI/SWE job applications.

Phase 1 delivers a usable application tracker with a kanban pipeline, a dashboard with recent-activity and reminder surfacing, and a lightweight essay-writing helper (prompt library + linked Google Docs). Later phases — job discovery (daily scan for new postings), interview prep (context/prep suggestions), and email sync (Gmail-based auto-detection of application-related emails) — are deliberately deferred, each being its own independently-scoped subsystem.

### Success criteria
- User can log in from phone, MacBook, or Windows PC over the public internet (not just home Wi-Fi) and see the same data.
- User can create, edit, and move applications through pipeline stages, with every status change recorded in history.
- Dashboard surfaces what's new and what needs attention without the user having to dig.
- The same Docker Compose stack that runs on the VPS today can be moved to a local server later with no code changes — only redeploying the containers and repointing DNS.

## 2. Architecture Overview

Single Docker Compose stack, three services behind a reverse proxy:

- **Backend** — Python 3.12 + FastAPI. REST API, auth (password + TOTP), business logic, Google OAuth flow for Docs access.
- **Database** — PostgreSQL 16. All application data, status history, and encrypted OAuth tokens.
- **Frontend** — Svelte + TypeScript (Vite build), compiled to static assets.
- **Reverse proxy** — Caddy. Automatic HTTPS via Let's Encrypt using the user's domain; routes `/api/*` to the backend, everything else to the frontend static build.

Deployment target for now: a small VPS (e.g. DigitalOcean/Linode droplet, ~$6/mo), chosen specifically because it's Docker Compose + a reverse proxy — nearly identical to what a future local server setup would look like. Migrating later means: stop containers on the VPS, start the same `docker-compose.yml` on the new machine, repoint the domain's DNS A record at the new IP. No application code changes.

Domain: user-provided (working name "internhelper" + a TLD the user registers themselves). DNS and registration are the user's own action, not automated by this project.

## 3. Data Model (PostgreSQL)

### `applications`
| column | type | notes |
|---|---|---|
| id | serial PK | |
| company | text | required |
| role_title | text | required |
| date_applied | date | |
| status | enum | `wishlist`, `applied`, `phone_screen`, `interview`, `offer`, `rejected` |
| job_link | text | nullable |
| notes | text | nullable |
| resume_version | text | nullable |
| contact_person | text | nullable |
| salary_range | text | nullable |
| location | text | nullable |
| source | text | e.g. LinkedIn, referral, company site |
| priority | enum | `low`, `medium`, `high` |
| follow_up_date | date | nullable; drives dashboard reminders |
| interview_datetime | timestamptz | nullable; hook for future interview-prep phase |
| google_doc_link | text | nullable; Drive file ID or URL for linked essay doc |
| archived | boolean | default false; hides closed-out rows from main views without deleting |
| created_at / updated_at | timestamptz | |

### `status_history`
| column | type | notes |
|---|---|---|
| id | serial PK | |
| application_id | FK → applications.id | |
| old_status | enum, nullable | null on initial creation |
| new_status | enum | |
| changed_at | timestamptz | |

Written automatically by the service layer on every status change. This is the sole source for the dashboard's "What's New" feed — no separate activity-log table needed.

### `oauth_tokens`
| column | type | notes |
|---|---|---|
| id | serial PK | |
| provider | text | `google` |
| encrypted_refresh_token | bytea | encrypted at rest (Fernet or equivalent, key from env var) |
| scopes | text | |
| created_at / updated_at | timestamptz | |

Single-user app — one row per provider is expected, not a multi-tenant design.

Schema changes over time go through **Alembic** migrations (versioned, reviewable, reversible) — never hand-edited schema changes. This directly answers "can I add more later": yes, via a new migration file each time.

## 4. Backend Structure (`backend/app/`)

Layered by responsibility, not dumped into one file:

```
app/
  main.py              # FastAPI app creation, router registration — minimal
  api/
    auth.py            # login, TOTP verification, token refresh
    applications.py    # CRUD + status-change endpoints
    docs.py            # Google OAuth callback, doc-content fetch endpoint
  services/
    application_service.py   # status-change rules, writes status_history
    auth_service.py           # password hashing, TOTP verification, JWT issuance
    google_docs_service.py    # OAuth token exchange/refresh, Docs API calls
  models/
    application.py
    status_history.py
    oauth_token.py
  schemas/
    application.py      # Pydantic request/response shapes
    auth.py
  core/
    config.py            # settings (env-driven)
    security.py          # password hashing, JWT, TOTP helpers
  db/
    session.py           # engine/session setup
  alembic/                # migrations
```

Rule of thumb enforced throughout: API routers stay thin (HTTP concerns only) and delegate to services; no file is allowed to silently grow into a multi-responsibility dumping ground — when one does, it gets split.

## 5. Frontend Structure (`frontend/src/`)

```
src/
  routes/
    Login.svelte
    Dashboard.svelte
    Applications.svelte
    Essays.svelte
  lib/
    components/
      KanbanBoard.svelte
      ApplicationCard.svelte
      ApplicationDetailPanel.svelte
      StatusBadge.svelte
      DashboardGrid.svelte        # Gridstack.js wrapper, loads/saves layout to localStorage
      DashboardWidget/
        RecentActivityFeed.svelte
        RemindersList.svelte
        BucketPreview.svelte     # Undone / Working On / Completed preview columns
        KanbanSnapshot.svelte
    api/
      applications.ts   # typed fetch wrappers to backend
      auth.ts
      docs.ts
    stores/
      session.ts
      applications.ts
    types/
      application.ts
```

Same rule as the backend: components stay small and single-purpose; a growing component gets decomposed rather than accumulating responsibilities.

## 6. UI / Page Structure

- **Login** — username + password + TOTP code field.
- **Dashboard (home)** — a customizable widget grid (see §6a). Default widgets:
  - Kanban snapshot (counts per stage)
  - "What's New" feed, sourced from `status_history` (e.g. "Moved Stripe to Interview — 2h ago")
  - Reminders block: upcoming `follow_up_date` and `interview_datetime` entries
  - Three-bucket recent-applications preview: **Undone** (wishlist), **Working On** (applied/phone_screen/interview), **Completed** (offer/rejected) — each showing the most recently updated applications in that bucket, derived from existing `status`, no new data required

### 6a. Customizable Dashboard Layout

The dashboard is a draggable, resizable widget grid, built on **Gridstack.js** (a mature library purpose-built for this — dashboard-style drag/resize grids, not a custom-built interaction).

- Each widget (What's New, Reminders, Bucket Preview, Kanban Snapshot) can be dragged to a new position and resized by dragging a corner handle; the grid snaps widgets into place.
- Each widget also exposes a small content-amount setting independent of its physical size — e.g. a dropdown on "What's New" for "show 3 / 5 / 10 items."
- Layout (widget positions, sizes, and per-widget content settings) is persisted in browser **`localStorage`**, per device — not synced via the backend. This is deliberate: the user's phone, MacBook, and PC have different screen sizes and are expected to want different arrangements, so a per-device layout is actually the better fit than forcing one synced layout across all of them.
- **Applications** — full kanban board, drag-and-drop between stages; clicking a card opens a detail panel showing every field, the status-history timeline, notes, and the linked Google Doc (read-only preview) if attached.
- **Essays** — prompt-template library with copy-to-clipboard buttons and a link out to claude.ai; attach/view a linked Google Doc per application here as well.
- Sidebar includes visible-but-disabled "coming soon" slots for **Job Discovery**, **Interview Prep**, and **Email Sync** so the nav doesn't need restructuring when those phases land.

## 7. Auth & Security

- Single-user login: username + password (hashed with bcrypt/argon2) plus **TOTP** second factor (compatible with the Google Authenticator app — standard RFC 6238, not Google-account-specific). Setup flow shows a QR code once; subsequent logins require the 6-digit rotating code.
- Session handled via JWT (short-lived access token + refresh).
- Google OAuth (for Docs viewing) uses a separate, narrowly-scoped (`drive.readonly` or doc-specific) consent flow; refresh token stored encrypted in `oauth_tokens`, never exposed to the frontend. Phase 1b (§13.7) adds exactly one write scope, `drive.file` (only files the app itself creates), for the backup sheet; no other Google write access is ever requested.
- The scheduled Claude job authenticates with a separate, revocable bearer token restricted to `/api/claude/*` (§13.5); it can never use or obtain a session.
- All traffic over HTTPS via Caddy/Let's Encrypt — no plaintext login over the public internet.

## 8. Google Docs Integration

- One-time OAuth consent grants read-only Docs/Drive access.
- User creates/writes essays in Google Docs normally (outside the app).
- `google_doc_link` on an application stores the Drive file reference.
- The detail panel and Essays page fetch the doc's text content via the Docs API and render it read-only in the app — refreshed on page load / manual refresh button, not live character-by-character sync.
- Fetch failures degrade gracefully: show "couldn't load doc — [open in Google Docs]" rather than breaking the page.

## 9. Essay Prompt Helper

- No Claude API integration in Phase 1 (deliberately deferred/simplified per user decision).
- Essays page provides: a link out to claude.ai, and a static/DB-backed library of copy-paste prompt templates (e.g. "draft an essay for ...", "review this essay for succinct, authentic writing") with copy-to-clipboard buttons.

## 10. Error Handling & Testing

- API errors return structured JSON (`{"detail": "..."}`) with correct HTTP status codes; frontend surfaces them via toast notifications rather than failing silently.
- OAuth/Docs-fetch failures degrade gracefully (see §8).
- Backend: pytest for service-layer and API route tests.
- Frontend: Vitest for component tests.
- Coverage goal: protect core flows (auth, status changes, doc linking) — not exhaustive coverage for its own sake.

## 11. Deployment & Migration Path

- `docker-compose.yml` at repo root defines all services (backend, db, frontend build, Caddy).
- Environment-driven config (`.env`, not committed) for secrets: DB credentials, JWT signing key, Google OAuth client secret, token-encryption key.
- Now: deployed to a VPS (~$6/mo), domain DNS pointed at it, Caddy handles TLS automatically.
- Later: identical `docker-compose.yml` runs on the user's local server; migration is stop/start + DNS repoint, not a rewrite.

### 11a. CI/CD

- **CI now:** a GitHub Actions workflow runs the backend pytest suite (against a Postgres service container) and the frontend Vitest suite on every push/PR to `main`. This is built as part of Phase 1 (Task 19) since the test suites it runs already exist by the end of this plan.
- **CD deferred:** automated deploy-on-merge to the VPS is explicitly *not* built in Phase 1. Rationale: automating a deploy process that hasn't yet been done manually and verified trustworthy is itself a risk. CD is a candidate for a short follow-up task once a few manual VPS deploys have gone smoothly.

### 11b. Development Workflow & Phase Documentation (added 2026-10-06; binds every phase)

- **Branch per phase.** Each phase is built on its own feature branch, never directly on `main`.
- **Commit and push at every task completion.** When a plan task passes its review (including any fix rounds), its commits are pushed to the phase's feature branch on GitHub (`origin`) right away, before the next task starts. Pushes contain only reviewed work; in-progress fixes are never pushed mid-review. Commit history is never rewritten or backdated.
- **Secret check before every push.** No `.env`, private keys, OAuth client secrets, or real tokens may be in the commits being pushed. Only the placeholder values in `.env.example` files are allowed.
- **Merge at phase end.** After the phase's final whole-branch review is clean, the branch is merged into `main` and `main` is pushed so every device can sync (`git pull`).
- **One report per phase.** Each phase ends with a report at `docs/phases/phase-<id>-report.md`, committed with the merge and indexed in `docs/phases/README.md`. A report covers:
  - what was delivered;
  - the task log with commit SHAs;
  - review outcomes;
  - work added beyond the plan;
  - quality and security;
  - key decisions with their trade-offs;
  - known limitations and deferred items;
  - what's next.

## 12. Explicitly Out of Scope (Phase 1)

- Job discovery feed (community internship-list feed + Greenhouse/Lever API polling) — future phase.
- Interview prep assistant (context/info/prep suggestions per interview) — future phase.
- Email sync (Gmail OAuth, auto-detect application-related emails) — future phase. Phase 1b outreach (§13) deliberately holds no Gmail permission: drafts open in Gmail compose and the user sends them.
- Restoring app data from the backup sheet (§13.7) — the sheet is a read-only failsafe mirror.
- In-app Claude API-powered essay drafting/review — deferred; Phase 1 only links out to claude.ai with copyable prompts.
- CD (automated deploy-on-merge to the VPS) — deferred until manual VPS deploys are proven reliable (see §11a). CI (automated tests on push/PR) is in scope and built in Task 19.

---

## 13. Outreach & Contacts (Phase 1b — added 2026-10-06)

Added after Phase 1 execution began, at the user's request. Built as new tasks **after** the core tracker (plan Tasks 4–18); it changes none of those tasks. Nothing here uses the Claude API: all research and drafting is done by a scheduled Claude Code job running on the user's Claude plan (no API billing), which talks to the app over a narrow, token-authenticated endpoint set (§13.5).

### 13.1 Goals

- Track cold outreach to **professors** (research positions) and to **company people** (likely hiring managers, team leads, recruiters) found for each internship application, through a simple pipeline with one-tap status buttons.
- Claude researches each contact and writes an email draft (and later a follow-up draft); the user reviews, edits, and sends every email personally. The app never sends email.
- The app flags anything that has gone too long without a reply or without being logged.
- Applications and contacts are mirrored to a Google Sheet in the user's Drive as a read-only failsafe.

### 13.2 Data Model

#### `contacts`
| column | type | notes |
|---|---|---|
| id | serial PK | |
| kind | enum | `professor`, `company` |
| name | text | required |
| organization | text | required — university (professor) or company |
| department | text | nullable — department (professor) or team/org (company) |
| title | text | nullable — e.g. "Associate Professor", "Engineering Manager, ML Platform" |
| lab_name | text | nullable, professors |
| email | text | nullable |
| email_confidence | enum | `found` (published; a source link is required), `pattern_guess` (inferred from the org's address format; unverified), `not_found` |
| website_url | text | nullable — lab/personal/team page |
| profile_url | text | nullable — public LinkedIn/Scholar/etc. profile |
| application_id | FK → applications.id, nullable | set for company contacts found for an application |
| relevance_note | text | nullable — Claude's one-line reason this person is relevant |
| research_summary | text | nullable — Claude-written |
| recent_work | text | nullable — Claude-written: papers/projects/talks relevant to the user |
| sources | jsonb | list of `{label, url}` Claude cited for the facts above |
| draft_subject / draft_body | text | nullable — first-contact email draft |
| draft_edited | boolean | default false; set true when the user edits the draft. Claude never overwrites an edited draft |
| followup_subject / followup_body | text | nullable — follow-up draft |
| followup_edited | boolean | default false; same rule as `draft_edited` |
| draft_ready_at | timestamptz | nullable — when Claude first delivered `draft_body` |
| status | enum | `to_contact`, `sent`, `followed_up`, `replied`, `meeting`, `accepted`, `declined` |
| closed_reason | text | nullable — e.g. `no_response` when closed via the No Response button |
| priority | enum | `low`, `medium`, `high` |
| sent_at / followed_up_at / replied_at | timestamptz | nullable — set by the matching buttons (user may backdate) |
| meeting_at | timestamptz | nullable |
| nudge_snoozed_until | date | nullable — set by "Not yet" / "Wait longer" / "Still talking" |
| notes | text | nullable, user-owned |
| origin | enum | `claude`, `manual` |
| archived | boolean | default false |
| created_at / updated_at | timestamptz | |

For company contacts the UI labels `accepted` as **"Positive (referral/interview)"**; the stored value is the same.

**Dedup on ingest:** a Claude-delivered contact matches an existing row by case-insensitive `email`, else by case-insensitive (`name`, `organization`). On a match Claude may update only research fields (`title`, `department`, `lab_name`, `email`, `email_confidence`, URLs, `relevance_note`, `research_summary`, `recent_work`, `sources`) and drafts whose `*_edited` flag is false. Claude never changes `status`, dates, `priority`, `notes`, or `archived`.

#### `contact_status_history`
Same shape and purpose as `status_history` (§3), keyed by `contact_id`; written by the service layer on every contact status change. The dashboard "What's New" feed merges both history tables.

#### `research_queue`
| column | type | notes |
|---|---|---|
| id | serial PK | |
| kind | enum | `professor_person` (a named professor), `professor_search` (a brief, e.g. "5 ML-for-robotics professors at UIUC or CMU"), `company_contacts` (find 3+ people for an application) |
| request_text | text | the name or brief; for `company_contacts`, generated from the application's company, role, and job link |
| application_id | FK → applications.id, nullable | set for `company_contacts` |
| target_count | int | 1 for `professor_person`, 3 for `company_contacts`, user-set for `professor_search` |
| state | enum | `pending`, `done`, `failed` |
| result_note | text | nullable — Claude's note on completion/failure (e.g. "found 2 of 3; no public emails") |
| created_at / completed_at | timestamptz | |

A `company_contacts` item is enqueued automatically when an application transitions to `applied` (only if none exists yet for that application), and manually via a **Find contacts** button on any application.

#### `app_settings`
Single-row settings table: `outreach_profile` (text — the user's background, interests, and goals, used to personalize every draft); nudge timings `nudge_unsent_days`=5, `nudge_followup_days`=10, `nudge_gone_quiet_days`=10, `nudge_replied_stale_days`=14; `claude_job_max_items`=8; `backup_sheet_id` (nullable); `last_sheet_sync_at`; `last_sheet_sync_error`.

#### `claude_tokens`
| column | type | notes |
|---|---|---|
| id | serial PK | |
| token_hash | text | SHA-256 of the token; the token itself is shown once and never stored |
| token_prefix | text | first 8 chars, for display |
| created_at / last_used_at / revoked_at | timestamptz | |

### 13.3 Status Buttons

Each contact card and detail panel shows only the buttons valid for the current status. A button sets the status, stamps the matching date (today by default, with an "it was actually on…" date picker), writes a `contact_status_history` row, and offers an Undo for 60 seconds. Undo restores the previous status and date fields and deletes that history row; after 60 seconds the change can only be corrected with another button or a drag. Kanban drag-and-drop remains available and follows the same transition rules.

| Current status | Buttons → resulting status |
|---|---|
| `to_contact` | **Sent** → `sent` |
| `sent` | **Followed up** → `followed_up` · **Replied** → `replied` · **Declined** → `declined` |
| `followed_up` | **Replied** → `replied` · **Declined** → `declined` · **No response** → `declined` with `closed_reason=no_response` |
| `replied` | **Meeting set** → `meeting` (asks for `meeting_at`) · **Accepted** → `accepted` · **Declined** → `declined` |
| `meeting` | **Accepted** → `accepted` · **Declined** → `declined` |

An invalid transition requested via the API is rejected with 422 and neither mutates the contact nor writes history.

### 13.4 Nudges

Computed on read from dates and status by a pure function (no background job). Shown as badges on cards and in a **Needs Attention** dashboard widget. A nudge is hidden while `today < nudge_snoozed_until`.

| Condition | Nudge | Actions |
|---|---|---|
| `to_contact` and `draft_ready_at` older than `nudge_unsent_days` | "Did you send this?" | Sent (date picker) · Not yet (snooze 3 days) · Skip (archive) |
| `sent` and `sent_at` older than `nudge_followup_days` | "Follow-up due" | Open follow-up draft · Followed up |
| `followed_up` and `followed_up_at` older than `nudge_gone_quiet_days` | "Gone quiet — close it out?" | No response · Wait longer (snooze 7 days) |
| `replied` with no status change for `nudge_replied_stale_days` | "Any update?" | Status buttons |
| `meeting` and `meeting_at` before today | "How did it go?" | Accepted · Declined · Still talking (snooze 7 days) |

Contacts at "Follow-up due" are included in the Claude job's work list, so a follow-up draft is waiting by the time the user sees the nudge.

### 13.5 Claude Job Interface

**Scheduled job.** A Claude Code scheduled cloud routine runs daily (default 07:00 local). Its instructions live in the repo at `ops/claude-routine/outreach-job.md`; the app's base URL and Claude token are stored in the routine's configuration, never in the repo. Each run:
1. `GET /api/claude/work` → pending queue items (up to `claude_job_max_items`), the `outreach_profile`, existing contacts' (name, organization, email) for dedup awareness, and contacts needing a follow-up draft (id, name, organization, original draft, `sent_at`).
2. Researches each queue item using web search/fetch on public sources (faculty/team pages, papers, talks, GitHub, press, public search results). It does not log into or scrape sites that require an account (e.g. LinkedIn).
3. `POST /api/claude/contacts` — batch upsert of contacts with research, sources, email + `email_confidence`, and draft, each linked to its queue item.
4. `POST /api/claude/followups` — follow-up drafts for the listed contacts.
5. `POST /api/claude/queue/{id}/complete` or `/failed` with a `result_note`.

Leftover queue items roll to the next run. The routine runs in the cloud, so it only works once the app is deployed at its public HTTPS address (§11); before deployment the queue simply accumulates. If the app is unreachable during a run, that run's work is lost and redone the next day, because queue items stay `pending` until completed.

**Auth and trust boundary.**
- `/api/claude/*` routes live in their own router behind a `get_claude_token` dependency that accepts only `Authorization: Bearer <token>` matching a non-revoked `claude_tokens` row. These routes never accept session cookies, and the Claude token is rejected on every other route.
- The token can read only what step 1 lists and write only contacts' research/draft fields and queue completion. It cannot read applications (beyond the company/role/job link embedded in a `company_contacts` queue item), notes, or statuses, and cannot change statuses.
- Settings page: create a token (shown once), list tokens by prefix with `last_used_at`, revoke.
- All Claude-delivered content is untrusted (it originates from arbitrary web pages): Pydantic schemas cap every field's length and the batch size; URLs must be `http`/`https` (anything else is dropped); the frontend renders it as plain text only — `{@html}` is never used for contact content.

### 13.6 Sending

Every draft has an **Open in Gmail** button that opens a Gmail compose URL (`https://mail.google.com/mail/?view=cm&to=…&su=…&body=…`) pre-filled with address, subject, and body, plus a **Copy** button (the fallback when the body exceeds a safe URL length). If `email_confidence` is `pattern_guess`, the button warns first ("this address is a guess and may bounce"). When the user returns from Gmail, the card prompts "Did you send it?" → **Sent**. The app holds no Gmail permission.

### 13.7 Backup Google Sheet

- The Google consent flow (§7, §8) additionally requests the **`drive.file`** scope, which grants access only to files the app itself creates. On first sync the app creates **"Internship Tracker Backup"** in the user's Drive with tabs **Applications**, **Professors**, **Company Contacts**. Rows are keyed by record id and include status, key dates, draft text, and a **Needs Attention** column (from §13.4). Row 1 states that the sheet is a one-way mirror and edits will be overwritten.
- **On change:** after an application/contact write commits, its row is re-synced via a FastAPI background task. A sync failure never fails or rolls back the user's write; it is recorded in `last_sheet_sync_error` and shown in Settings.
- **Nightly:** a small scheduler service in the Docker Compose stack runs a full re-sync of all three tabs, repairing anything missed.
- One-way only (app → sheet). Restoring the app from the sheet is out of scope.

### 13.8 UI

- **Contacts** page: kanban by status with a Professors / Company / All filter. Cards show name, organization, title, email-confidence badge, "draft ready" badge, nudge badge, and status buttons. The detail panel shows research, sources (as links), editable drafts with Open in Gmail / Copy, status timeline, and notes.
- **Research Queue** page: add a named professor or a search brief; see pending/done/failed items with Claude's `result_note`.
- **Application detail panel** gains a **Contacts** section listing that application's company contacts and drafts, plus the **Find contacts** button.
- **Dashboard** gains a **Needs Attention** widget (Gridstack-compatible, per §6a).
- **Settings** gains: outreach profile editor, nudge timings, Claude token management, backup-sheet status (link, last sync, last error, "Sync now").
- Sidebar: Contacts and Research Queue become real entries.

### 13.9 Error Handling & Testing

- Same structured-JSON error contract as §10. A missing, revoked, or invalid Claude token → 401. A malformed or oversized Claude payload → 422 with nothing written.
- Backend tests must cover: dedup matching; Claude never overwriting edited drafts or user-owned fields; valid and invalid status-button transitions (invalid → 422, no history row); nudge computation as a pure function over a fixed "today" (each row of §13.4, plus snooze); token scoping in both directions (Claude token rejected on cookie routes, cookies rejected on `/api/claude/*`, revoked token rejected); auto-enqueue on `applied` happening exactly once per application; sheet sync via a fake Sheets client, including the "sync failure doesn't break the write" rule; non-http(s) URLs dropped.
- Frontend tests: status buttons render per status; Open in Gmail URL encoding and the pattern-guess warning; contact content rendered as text, not HTML.
