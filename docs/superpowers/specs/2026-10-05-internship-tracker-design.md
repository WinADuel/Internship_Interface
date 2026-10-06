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
- Google OAuth (for Docs viewing) uses a separate, narrowly-scoped (`drive.readonly` or doc-specific) consent flow; refresh token stored encrypted in `oauth_tokens`, never exposed to the frontend.
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

## 12. Explicitly Out of Scope (Phase 1)

- Job discovery feed (community internship-list feed + Greenhouse/Lever API polling) — future phase.
- Interview prep assistant (context/info/prep suggestions per interview) — future phase.
- Email sync (Gmail OAuth, auto-detect application-related emails) — future phase.
- In-app Claude API-powered essay drafting/review — deferred; Phase 1 only links out to claude.ai with copyable prompts.
- CD (automated deploy-on-merge to the VPS) — deferred until manual VPS deploys are proven reliable (see §11a). CI (automated tests on push/PR) is in scope and built in Task 19.
