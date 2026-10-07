# Phase 1 Report: Internship Tracker Core

| | |
|---|---|
| **Status** | Complete. Merged to `main` on 2026-10-06 (merge commit `6a6d625`). |
| **Built** | 2026-10-05 → 2026-10-06 |
| **Branch** | `worktree-internship-tracker-phase1` (on GitHub at `9f834f1`) |
| **Spec** | [`docs/superpowers/specs/2026-10-05-internship-tracker-design.md`](../superpowers/specs/2026-10-05-internship-tracker-design.md) §1–§12 |
| **Plan** | [`docs/superpowers/plans/2026-10-05-internship-tracker-phase1.md`](../superpowers/plans/2026-10-05-internship-tracker-phase1.md) (19 tasks) |
| **Tests at finish** | Backend 189 passing · Frontend 143 passing · `svelte-check` 0 errors / 0 warnings · production build clean |

---

## 1. What Phase 1 delivers

A personal internship and job application tracker for a single user, reachable from a phone, a MacBook and a Windows PC over the public internet:

- **Secure login.** Username and password (bcrypt), plus a 6-digit code from an authenticator app (TOTP, Google Authenticator compatible). Sessions live in httpOnly, Secure, SameSite=Lax cookies. Sessions survive page reloads and renew themselves silently every 30 minutes.
- **Applications board.**
  - A kanban board with six stages: Wishlist, Applied, Phone Screen, Interview, Offer, Rejected.
  - Create and edit applications with every field: company, role, dates, links, notes, résumé version, contact, salary, location, source, priority, follow-up date, interview time and linked Google Doc.
  - Move cards by drag and drop on desktop, or with a status dropdown, which works on phones.
  - Archive applications.
  - Every status change is recorded in a history timeline.
- **Dashboard.** A drag-and-resize widget grid. Layout and per-widget settings are saved per device. It has four widgets:
  - What's New, an activity feed;
  - Reminders, with an Overdue group above upcoming follow-ups and interviews;
  - Undone / Working On / Completed buckets;
  - a kanban snapshot.
- **Google Docs (read-only).** Connect a Google account once. Each application can link a Google Doc, whose text is previewed in the app. If the doc can't be loaded, the app shows "Couldn't load doc" with an "Open in Google Docs" link instead of breaking.
- **Essays page.** A library of copy-paste prompt templates for drafting and reviewing essays, a link to claude.ai, and a place to attach or view each application's essay doc. This phase deliberately has no Claude API integration.
- **Deployment.** One Docker Compose stack (PostgreSQL, backend, Caddy) with automatic HTTPS. The same files run on a VPS now and on a home server later.
- **CI.** GitHub Actions runs the backend tests against a real Postgres, plus frontend type-checking, tests and build, on every push to `main` and on every pull request.

## 2. Architecture at a glance

```
Browser (phone / laptop / PC)
        │  HTTPS
        ▼
     Caddy ──── serves built Svelte app (static files)
        │  /api/*
        ▼
  FastAPI backend ── services ── SQLAlchemy models ── PostgreSQL 16
        │
        └── Google OAuth + Drive export (read-only), refresh token Fernet-encrypted at rest
```

- **Backend** (`backend/app/`). Thin routers in `api/` delegate to `services/`, which use `models/`, with Pydantic `schemas/`. Schema changes go only through Alembic migrations (`0001` auth, `0002` applications, `0003` TOTP replay guard). A `python -m app.cli create-user` command creates the single account and enrols the authenticator.
- **Frontend** (`frontend/src/`). Svelte 5 (runes) and TypeScript, built by Vite and served as static files. Routing uses hash URLs (`/#/applications`), so the server never needs fallback rules. All API calls go through one client (`lib/api/client.ts`), which handles credentials, silent refresh and readable error messages.
- **Data stays where the spec says.** Application data is in Postgres. Dashboard layout is in each browser's `localStorage`. Secrets come only from `.env`, never from git or images.

## 3. How it was built

The work was planned, then executed task by task. A fresh implementer built each task, and a separate reviewer checked it against the spec and for code quality before the next task started. Findings went back to the implementer, and every fix was re-reviewed. After all tasks, a whole-branch review ran on the most capable model, followed by one fix round and a final re-review.

### Task log

| # | Task | Key commits | Review outcome |
|---|---|---|---|
| 1 | Backend scaffolding & test harness | `534f91e`, `0f3220a` | 1 fix round: test isolation now survives `commit()` via nested savepoints |
| 2 | Auth model & security helpers | `6d612aa`, `1375ab8` | 1 fix round: token type check and required JWT claims |
| 3 | Auth service, routes, `get_current_user` | `b256f5e`, `1447089` | 1 fix round: Secure cookie flag and 401 edge-case tests |
| 4 | Application / history / OAuth models + migration | `797875d` | Clean |
| 5 | Application service | `8b39450`, `5cbb0e7` | 1 fix round: creation writes a history row, per spec §3 |
| 6 | Applications API routes | `9910de0`, `79b6532` | 1 fix round: invalid status proven to leave no trace |
| 7 | Google OAuth flow | `d734669` | Clean (CSRF state check added at dispatch) |
| 8 | Google Docs fetch | `a1c4469` | Clean (doc-ID validation and graceful 502s added at dispatch) |
| 9 | Frontend scaffold, router, API client, login | `3f095dd` | Clean |
| 10 | Applications API client, types, store | `f80c3c6`, `5b534ae` | 1 fix round: safe undo for rapid repeated moves |
| 11 | Kanban board & card | `3756ec3` | Clean |
| 12 | Detail panel & Google Doc viewer | `bbca9bc` | Clean |
| 13 | Applications page | `6240ada`, `ca04fe1` | 1 fix round: keyboard activation (Enter/Space) |
| 14 | Dashboard grid (Gridstack) | `3959659`, `254cfa4` | Clean |
| 15 | Dashboard widgets | `ec3a44b` | Clean |
| 16 | Dashboard page | `a7faa8c` | Clean |
| 17 | Essays page | `1999000` | Clean |
| 18 | Docker Compose, Caddy, env | `bb5aea6`, `d03330d` | 1 fix round: dev OAuth redirect URI, LF line endings |
| 19 | CI (GitHub Actions) | `0478c41` | Clean |

### Work added beyond the plan

These gaps were found during execution. Each was decided, recorded and reviewed like a planned task.

| Addition | Commits | Why |
|---|---|---|
| TOTP accepts ±30 s clock drift | `fe490a5` | Codes were rejected at 30-second boundaries. This also explained two intermittent test failures. |
| Session restore (`/api/auth/me`) | `19b7164` | Every page reload, and every return from Google sign-in, logged the user out. |
| Silent token refresh and retry | `e3f83ee` | Without it, users were logged out every 30 minutes while using the app. |
| `create-user` CLI | `f75ef60`, `570f2b7` | No planned task created the first account or enrolled the authenticator. |
| Type-check cleanup, with `npm run check` in CI | `8fab5c9` | Type errors had built up unseen across tasks. |
| Final-review fix round | `29bb9a1` … `9f834f1` (11 commits) | See §5. |

## 4. Quality & security

- **Tests.** 189 backend tests (pytest against real Postgres) and 143 frontend tests (Vitest), with zero `svelte-check` errors or warnings. Each Review Focus item from the plan is covered by a test:
  - invalid status → 422, with no change and no history row;
  - same-status change → no duplicate history row;
  - archived applications excluded by default;
  - unauthenticated or expired requests → structured 401;
  - Google failures → 502 plus a fallback link.
- **Authentication hardening.**
  - Tokens are typed (access vs refresh), so one can't stand in for the other.
  - Required JWT claims are enforced.
  - A dummy bcrypt hash prevents username enumeration by timing.
  - TOTP is enforced on every login. The setup endpoints were removed, and only the CLI enrols the authenticator.
  - Each TOTP code works once.
  - After 5 failed logins, a global backoff kicks in (429, up to 5 minutes).
  - The app refuses to start with a weak or placeholder `JWT_SECRET` or an invalid encryption key.
- **Google integration.**
  - Read-only scope.
  - The OAuth `state` is checked against a cookie (CSRF).
  - The refresh token is encrypted at rest.
  - Doc IDs are validated before any outbound request (SSRF).
  - Error messages never contain tokens or response bodies.
- **Frontend.** No `{@html}` anywhere, so all user and doc content renders as text. Links built from data are restricted to `https://docs.google.com/`.
- **Deployment.**
  - Caddy sends HSTS, `X-Frame-Options: DENY`, `nosniff` and `Referrer-Policy` headers.
  - The database port is not exposed.
  - The backend waits for a healthy database, and migrations run before the server starts.
  - Backend dependencies are pinned, and test tools are kept out of the production image.

## 5. Final whole-branch review

The final review initially returned **"not ready to merge"**. Its findings:

- **Critical (a gap in the plan):** there was no UI to create or edit applications, so a fresh install could not be used.
- **Important:**
  - Status could only be changed by drag and drop, which doesn't work on phones.
  - A placeholder `JWT_SECRET` was accepted.
  - TOTP enrollment failed open.
  - Login had no throttling.
  - Dependencies were unpinned.
  - Backup and migration documentation was missing.
  - Google setup was undocumented, and failures were silent.
  - The layout was unusable on phones.
  - Overdue follow-ups disappeared from Reminders.

All of these were fixed in a single fix round (11 commits), and an independent re-review confirmed **every finding addressed, with no new Critical or Important issues**.

## 6. Key decisions

These decisions were made during execution where the spec or plan was silent or conflicted.

| Decision | Reason | Trade-off |
|---|---|---|
| Creating an application records a "created" history entry | Spec §3 says `old_status` is null on creation | One extra feed item per new application |
| Hash routing (`/#/…`), with backend redirects to match | The router library is hash-based | None while hash routing is kept |
| Google Docs read via Drive's plain-text export | Works under the read-only scope | Doc formatting isn't shown |
| Login throttle is global and in memory | The backend sees Caddy's IP, not the client's | Anyone can delay the owner's login by up to 5 minutes, and a restart clears the lockout |
| TypeScript 6 instead of 7 | `svelte-check` doesn't support TS 7 yet | Upgrade once it does |
| Reminders show an Overdue group | A missed follow-up is what needs attention most | None |
| Outreach (professors and company contacts) became its own phase | It's a separate subsystem with its own spec section (§13) | Separate plan and report |

## 7. Known limitations & deferred items

- **Not yet verified on a real server:** the Let's Encrypt certificate on the real domain, the Google OAuth round trip with a real client, and Docker builds of the final configuration.
- **Dashboard on narrow windows.** Windows narrower than about 950 px switch to one column and stop saving drag changes. The planned fix is one line (`breakpointForWindow: true`).
- **Encryption key changes.** Changing `TOKEN_ENCRYPTION_KEY` makes login return an error. The README says to copy `.env` exactly when moving servers.
- **Small items:**
  - Notes are trimmed on save.
  - Interview times are kept to the minute.
  - The setup code entered in the CLI can log in once more within its 30-second window. The password is still required.
- **Dependencies.** Indirect backend dependencies are not pinned.
- **Out of scope by design (spec §12):** job discovery feed, interview prep, email sync, in-app Claude API, and automated deploys (CD).

## 8. Operating the app

The repo root `README.md` covers deploying, first-time account creation, Google Docs setup, backups and moving servers. In short:

1. Copy `.env.example` to `.env` and fill in the secrets. Generation commands are in the file.
2. Run `docker compose up -d --build`.
3. Run `docker compose exec backend python -m app.cli create-user --username <you>`, then scan the QR code with your authenticator app.
4. Log in at `https://<your-domain>/`.

## 9. Process notes for later phases

- **Commit and push at every completed task.** After each task passes review, its commits are pushed to the phase's feature branch on GitHub, so history grows steadily with reviewed work. This rule is now in the spec (§11b) and the Phase 1b plan.
- **One report per phase.** Each phase ends with a report like this one in `docs/phases/`.
- **Lessons from this phase:**
  - Plans should include a "first-run" task (account bootstrap) and a "create and edit" UI task explicitly.
  - Helper processes must stop only processes they started.
  - Scratch workspace files must never be force-added to git.

## 10. What's next

**Phase 1b — Outreach & Contacts** (spec §13, plan [`2026-10-06-outreach-contacts-phase1b.md`](../superpowers/plans/2026-10-06-outreach-contacts-phase1b.md)):

- Track cold outreach to professors and to company contacts found for each application.
- A scheduled Claude Code job, running on the user's plan with no API billing, researches each contact and drafts emails.
- One-tap status buttons and "needs attention" nudges.
- A one-way Google Sheet backup.
