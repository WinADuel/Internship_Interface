# Phase 5 Plan: Discover Inbox Ranking

Spec: `docs/superpowers/specs/2026-10-09-inbox-ranking-design.md`.
Branch: `phase-5-inbox-ranking`, cut from `phase-4-interview-prep` (stacked: Phases 3 and 4 are not merged yet; this PR includes them until they are). Progress log: `docs/phases/phase-5-progress.md`.

Rules: as Phase 4 (test-first, fakes only, one implementer at a time, lead reviews and pushes, secret check, never `main`).

## Task 1: Preferences, local score and storage (spec §3, §4)
- Migration `0008_inbox_ranking`: the `app_settings` ranking fields; `postings.local_score`, `local_reasons`, `claude_scored_at`; the Best-match expression index.
- `services/discovery/ranking.py` pure scoring; score during ingest; re-score on preference change (settings service) and after the first scan of each day.
- Settings schema/route accept the new fields with the caps.
- Tests: every rule, overrides, fallback, freshness boundaries; ingest scoring; re-score on change with a 5,000-row timing check.

## Task 2: Listing sort and Top picks (spec §6 listing)
- `sort=best|newest`, `min_score` on `GET /api/discovery/postings`; Top-picks count (reuse the match-count pattern).
- Tests: ordering with mixed Claude/local scores, ties, paging stability, `min_score`.

## Task 3: Claude ranking routes and routine (spec §5)
- `GET /api/claude/postings`, `POST /api/claude/postings/scores`; boundary tests; routine instructions section.
- Tests: selection (limit, stale re-eligibility, Inbox filters, closed excluded), payload fields, caps, skipping, sanitising.

## Task 4: Frontend (spec §6 UI)
- Types/API; Inbox toolbar (Best/Newest, Top picks chip); score badge and Why? disclosure in `PostingRow`; Settings Ranking card; Dashboard widget order.
- Tests for each; svelte-check, build; 390 px check of the Inbox.

## Task 5: Docs, review and report
- README; phases index; whole-branch review; fixes; `docs/phases/phase-5-report.md`; PR.
