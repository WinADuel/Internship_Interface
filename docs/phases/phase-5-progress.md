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
