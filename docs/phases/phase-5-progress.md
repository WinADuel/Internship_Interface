# Phase 5 Progress Log: Discover Inbox Ranking

Spec: `docs/superpowers/specs/2026-10-09-inbox-ranking-design.md`. Plan: `docs/superpowers/plans/2026-10-09-inbox-ranking-phase5.md`.
Branch `phase-5-inbox-ranking`, stacked on `phase-4-interview-prep`.

The owner asked on 2026-10-09 for interview prep, Discover inbox ranking and Gmail sync to be built overnight. The design uses the defaults in its §2; the owner reviews them with the PR.

## Task log

### Tasks 1–3: ranking backend — `025eeb8`, `07faf4e`, `5da22f8`
Backend 1706 passed at `5da22f8`; 1792 after merging Phase 4's routes. Re-scoring 5,000 postings after a preferences change: 0.44 s (test limit 3 s).
Rulings:
- The pinned `alembic check` moved from the 0007 migration test to `tests/migrations/test_head.py`. Accepted.
- Claude notes over 200 characters are cut to 200 on one line instead of rejected; raw input over 2,000 characters is still a 422. Accepted: one wordy note shouldn't lose a run's scores.
- Changing only the daily limit doesn't mark Claude scores stale. Accepted.
- Skill, company and dealbreaker keywords match whole words (so "go" doesn't match "Google"); "Remote" also matches the title; freshness falls back to `first_seen_at`; a Claude score without `claude_scored_at` counts as stale; saving or restoring a posting re-scores it. Accepted.
- Example titles for Claude: applied postings count as positive examples together with saves (Task 4 makes the change).
- Merge with Phase 4: the routine instructions are now §7 briefs, §8 follow-ups, §9 Inbox ranking (last step), §10 errors, §11 end of run.

### Task 4: frontend — `0ad673b`, `12058e2`, `9be854b`
Frontend 547 passed; backend 1793. Applied postings now count as positive examples with saves (ruling from Tasks 1–3). Rulings: sort and Top picks choices persist across tabs and rescans; the Inbox drops out-of-order responses; scores and Why? show in Inbox and Saved, not Dismissed; the Ranking card has its own Save, after Job discovery. Accepted.

### Task 5 (part 1): end-to-end walk and docs — `142394e`, `410e7a2`, `74f5703`, `f796074`
Walked against a real backend with 300 seeded postings (no network) in headless Chromium, including a simulated routine. Three bugs fixed: a `null` Claude note was a 422 that lost the whole batch; the freshness reason ("posted 1 day ago") went stale and disagreed with the row's date, so it now names its band; the Claude tokens card described only the old job. Stale Claude scores keep ordering the Inbox (greyed), as the spec says.

### Review — fixes `a707717`, `cfcfc92`
One reviewer covered backend and frontend: 1 Important, 5 Minor, all fixed with tests that fail on the old code:
- Important: a preference change saved while a scan was running was undone by the rest of the scan. The scan now re-reads preferences before each source and before the final re-score.
- Claude scores posted after a preference change counted as fresh: `GET /api/claude/postings` returns `preferences_as_of`, which the routine echoes back.
- The daily freshness re-score now has its own `last_rescore_at` (added to migration 0008, which is unmerged) and runs whenever it is 20 h old, also between scans.
- Locations match whole words ("NY" no longer matches "Sunnyvale").
- Inbox actions and Dismiss all respect a reload that happened meanwhile.
- Bulk posting writes (re-score, ingest, housekeeping, dismiss-all, Claude scores, the settings PATCH) take one short transaction-scoped advisory lock, so they can't deadlock each other.
Final: backend 1841 passed, `alembic check` clean; frontend 566 passed, `svelte-check` 0/0, build clean.
