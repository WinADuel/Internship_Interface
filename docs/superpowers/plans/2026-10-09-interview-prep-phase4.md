# Phase 4 Plan: Interview Prep

Spec: `docs/superpowers/specs/2026-10-09-interview-prep-design.md`.
Branch: `phase-4-interview-prep`, cut from `phase-3-deploy` at `b49f4ec` (Phase 3 is not merged yet; this PR includes it until it is). Progress log: `docs/phases/phase-4-progress.md`.

Rules (unchanged from Phase 3):
- Test-first. Nothing in tests contacts Google, Anthropic, GitHub or any other external service; use fakes.
- One implementer agent at a time on the branch. The lead reviews every diff, logs rulings, and pushes each reviewed task.
- Secret check before every push. Never commit to `main`.
- Backend: `pytest` on real PostgreSQL 16 (`filterwarnings=error`). Frontend: `npm run test -- --run`, `npm run check`, `npm run build`.

## Task 1: Data model, migration and service core (spec §3, §4 service)
- Models `InterviewRound`, `Story`, `PrepBrief`, the two link tables; enums as in §3.
- Migration `0007_interview_prep` with the data migration from `applications.interview_datetime`; `research_queue` kind enum gains `interview_brief`.
- `app/services/interview_service.py`: create/update/delete/list rounds, default checklist, derived `interview_datetime` recompute after every write (and sheet sync scheduling, as application writes do), contact and story linking rules, `thank_you_due`.
- Stories service (CRUD, archive, tag filter).
- `ApplicationUpdate` drops `interview_datetime`; `ApplicationCreate` turns a supplied value into a first round.
- Tests: services, migration up/down on real Postgres including the data migration, existing application tests updated.

## Task 2: Routes and calendar export (spec §4 routes)
- `app/api/interviews.py`, `app/api/stories.py`, registered in `main.py`, cookie auth; add to the Claude-token boundary test.
- `.ics` builder in `app/services/ics.py` (RFC 5545 escaping, CRLF, 75-octet folding, UTC times, stable UID).
- Tests: every route, validation caps, 404s, `.ics` content.

## Task 3: Claude company brief (spec §4 Claude routine)
- `POST /api/applications/{id}/brief/request`, `GET /api/applications/{id}/brief`.
- `/api/claude/work` includes `interview_brief` items; `POST /api/claude/briefs` ingest with sanitising.
- Update `ops/claude-routine/outreach-job.md` with the brief section and payload.
- Tests: queue rules (one pending per application), work payload contains no private fields, ingest caps/URL filter/state checks, boundary.

## Task 4: Sheet sync Interviews tab (spec §4 sheet sync)
- Add the tab with the existing tab pattern; scheduled after round writes.
- Tests with the fake Sheets client.

## Task 5: Frontend data layer, Interview Prep page and story bank (spec §5)
- `lib/types/interview.ts`, `lib/api/interviews.ts`, `lib/api/stories.ts`.
- Route `#/interviews` with Upcoming / Past / Story bank tabs; nav slot enabled.
- Tests: tabs, ordering, countdown text, story CRUD flows.

## Task 6: Prep page (spec §5 prep page)
- Route `#/interviews/:id` with the eight sections; `lib/prep/prompts.ts` prompt builders; thank-you Gmail compose URL builder (reuse the Phase 1b compose helper if one exists).
- Tests: each section, prompt text, compose URL, brief rendering as text with safe links, request-brief states.

## Task 7: Application panel, form and Dashboard widget (spec §5)
- "Interviews" section in `ApplicationDetailPanel`, Add round, Move to Interview.
- Read-only "Next interview" in `ApplicationForm`.
- `UpcomingInterviews` widget registered in the Dashboard with layout reconciliation.
- Tests for each.

## Task 8: Phone width, docs, review and report
- Check `#/interviews` and the prep page at 390 px in headless Chromium against the Vite preview with the API mocked; fix overflow.
- README feature list; phases index row.
- Whole-branch review (backend and frontend reviewers), fixes, final counts, `docs/phases/phase-4-report.md`, PR.
