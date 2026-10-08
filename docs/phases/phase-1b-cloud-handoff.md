# Phase 1b Cloud Handoff: Resume Instructions

You are the lead engineer continuing Phase 1b ("Outreach & Contacts") of a personal, single-user internship-tracker web app. You work alone and unattended in a fresh Linux cloud container (claude.ai/code), on the GitHub repository github.com/WinADuel/Internship_Interface. The repo owner approved this plan and asked for it to be built. Work autonomously to completion. The owner is not available to answer questions.

**Task 1 is already done** and pushed on branch `phase-1b-outreach`. Resume from the progress log (see "Resume rule" below).

## Read first
All of these are in the repo, on branch `phase-1b-outreach`:
- **Plan.** `docs/superpowers/plans/2026-10-06-outreach-contacts-phase1b.md` is the binding task list (15 tasks). Read the WHOLE plan. Pay special attention to:
  - its "Phase 1 as-built: corrections" block near the top, which overrides the task text wherever they conflict;
  - its Global Constraints and Review Focus sections.
- **Spec.** `docs/superpowers/specs/2026-10-05-internship-tracker-design.md` is the binding authority. Read §13, plus §7, §11b and §12.
- **What already exists:** `docs/phases/phase-1-report.md` and the root `README.md`.
- **Progress so far:** `docs/phases/phase-1b-progress.md`, the recovery map. It records which tasks are done and every ruling made so far.
- **Existing code:** follow the established patterns in each part.
  - `backend/`: FastAPI, SQLAlchemy 2.0, Alembic, pytest.
  - `frontend/`: Svelte 5 runes + TS, Vite, Vitest, svelte-check.

## Environment setup (fresh Linux cloud container — do this first)
1. Run `git fetch origin && git checkout phase-1b-outreach`. All work happens on this branch.
   - **Never commit to, merge into, or push `main`.**
   - Always push with the explicit form `git push origin phase-1b-outreach`.
2. Backend:
   - Create a Python 3.12 venv, then run `pip install -r backend/requirements-dev.txt`.
   - Install and start PostgreSQL 16. Use apt (`postgresql`) or a docker `postgres:16` container, whichever works.
   - Create user `app` with password `app`, and database `internship_tracker_test` owned by it. It must listen on localhost:5432.
   - Export the env values from the backend job's `env:` block in `.github/workflows/ci.yml`. They are valid test-only secrets.
     - The backend reads `backend/.env` (gitignored), so an alternative is to put the same values there. Never commit it.
   - From `backend/`, run `alembic upgrade head`, then `pytest -q`. The expected baseline is **195 passed** (189 from Phase 1 plus 6 from Task 1).
3. Frontend:
   - Install Node 22, then run `npm ci` in `frontend/`.
   - Run `npm run check`, `npm run test -- --run` and `npm run build`. The baseline is 143 tests passing, with 0 check errors.
4. If Postgres truly cannot run here:
   - continue with everything else;
   - mark every backend task as "untested against Postgres" in the progress log;
   - **never fake test results.**

## Resume rule
Read `docs/phases/phase-1b-progress.md` and continue at the first task without a completed line. Task 1 is done (commit `8b1e817`), so this session normally starts at **Task 2**. If a later session finds more tasks logged, resume from the first incomplete one.

## Carry-forward notes from Task 1
- **Migration testing.** The test harness builds tables with `Base.metadata.create_all` (`backend/tests/conftest.py`), not with migrations. Exercise each migration by hand: `alembic upgrade head`, then `alembic downgrade -1`, then `alembic upgrade head`. Run `alembic check` to confirm the models and migrations agree.
- **New columns on existing tables.** If a later task changes a model, the test DB will already have tables created by `create_all`. Add an Alembic migration and run `alembic upgrade head` against the test DB.
- **Warnings fail tests.** `backend/pytest.ini` sets `filterwarnings = error`, so any deprecation warning fails a test. For example, use `datetime.now(timezone.utc)`, not `utcnow()`.
- **Enum helper.** Models use `enum_column(EnumCls, "pg_type_name")` from `app/models/application.py`, which stores lowercase values. Task 1's model enums are:
  - `ContactKind`, `EmailConfidence`, `ContactStatus` and `ContactOrigin` in `app/models/contact.py`;
  - `QueueKind` and `QueueState` in `app/models/research_queue.py`.
- **`AppSettings`** is a single row with `id = 1`, enforced by a CHECK constraint.
- **Services commit themselves.** Existing services (for example `application_service`) call `db.commit()`. The test session fixture uses SAVEPOINTs, so commits inside tests are safe.
- **One commit for Claude ingest.** Task 7 requires one transaction per request, so a 422 writes nothing. Commit once at the end of an ingest call.

## How to execute each task (Tasks 2 through 15, in order)
For each task:
1. **Implement** exactly what the plan's task specifies, as corrected by the as-built block.
   - Use TDD: write the failing test, watch it fail, implement, then watch it pass.
   - Keep routers thin and files single-purpose.
   - Never use `{@html}`.
2. **Verify:**
   - run the task's own tests, then the full backend and/or frontend suite;
   - run `npm run check` for any frontend change;
   - for migration tasks, run alembic upgrade, then downgrade -1, then upgrade.
3. **Commit** with conventional messages. End every commit message with the line `Co-Authored-By: Claude <noreply@anthropic.com>`.
4. **Review before moving on.**
   - If you can dispatch a subagent, have a fresh reviewer check the task's diff against the task text, the Global Constraints and the Review Focus. The reviewer reports Critical, Important and Minor issues and must not edit files.
   - If you can't dispatch one, do a separate, deliberate review pass yourself: re-read the task text, then read the diff line by line.
   - Fix every Critical and Important finding, then re-verify.
   - Log Minor findings without fixing them.
5. **Push the reviewed work** (spec §11b).
   - First run a secret check on the commits being pushed. No `.env`, no private keys, no real OAuth secrets or tokens. Only `.env.example` placeholders and the ci.yml test values are allowed.
   - Then run `git push origin phase-1b-outreach`.
   - Never force-push, rewrite or backdate history.
6. **Log progress.** Append a line to `docs/phases/phase-1b-progress.md` and commit it with the task.
   - The line gives the task number, commit SHAs, test counts, review outcome, and any ruling you made.
   - This file is the recovery map if the session is interrupted. If you find it already populated, resume from the first incomplete task.

**Rulings.** When the plan is ambiguous or conflicts with the code, decide yourself.
- The spec wins over the plan, and the as-built block wins over the plan's task text.
- Record each ruling in the progress log as `Ruling: <decision> — <why> — <cost if wrong>`.
- Only stop for something destructive or irreversible beyond this branch.

## Hard rules
- Never push to or modify `main`.
- Never add real secrets.
- Never contact Google, Anthropic or other external APIs from tests. Use mocks and fakes, as the plan says.
- Task 15's "Post-deployment" step (setting up the scheduled routine) is NOT yours, because the app isn't deployed. Write `ops/claude-routine/outreach-job.md` as specified, and skip the scheduling.
- Be cost-conscious, because this run uses limited cloud credits:
  - don't re-run full suites needlessly;
  - prefer focused tests while iterating;
  - keep reviewer passes scoped to each task's diff.

## After Task 15
1. **Whole-branch review.** Review `git diff origin/main...HEAD` against spec §13 and the plan. Pay special attention to:
   - security: the Claude token boundary, untrusted content, URL filtering;
   - cross-task contracts;
   - frontend↔backend field names;
   - migrations.

   Fix all Critical and Important findings in one fix round, then re-verify the full suites.
2. **Write the report** at `docs/phases/phase-1b-report.md`, following the structure of `docs/phases/phase-1-report.md`. Cover:
   - what was delivered;
   - a task log with SHAs and review outcomes;
   - additions beyond the plan;
   - quality and security;
   - key decisions and trade-offs, including all rulings (the Task 1 rulings are in the progress log);
   - known limitations;
   - what's next, including what the owner must do to deploy and schedule the daily Claude job.

   Then update the Phase 1b row in `docs/phases/README.md` to "Complete on branch, awaiting merge".
3. **Push the branch.** **Do not merge.** The owner merges after reading the report.

## Final message
Reply with:
- the branch's final SHA;
- per-task status, with any task left incomplete and why;
- final test counts (backend, frontend, check, build);
- whether Postgres-backed tests actually ran;
- every ruling you made;
- anything the owner must do next.
