# Phase 6 Plan: Gmail Sync

Spec: `docs/superpowers/specs/2026-10-09-gmail-sync-design.md`.
Branch: `phase-6-gmail-sync`, cut from `phase-5-inbox-ranking` (stacked: Phases 3–5 are not merged yet; this PR includes them until they are). Progress log: `docs/phases/phase-6-progress.md`.

Rules: as Phase 4.

## Task 1: OAuth granted scopes and the Gmail consent (spec §2, §5 OAuth token)
- Store the granted `scope` from the token response; `gmail` flag on the authorize route adding `gmail.readonly` and `include_granted_scopes=true`; `gmail_granted` exposed in the settings/status schema.
- Tests with faked token responses (granted subset, missing scope field falls back to requested).

## Task 2: Matcher and classifier (spec §4)
- `services/gmail/matching.py`, `classify.py`: pure functions over a parsed message header set and the applications/contacts snapshot.
- Table-driven tests with realistic cases and false-positive traps.

## Task 3: Data, Gmail client and sync job (spec §5, §6)
- Migration `0009_gmail_sync`; `GmailClient` (metadata only) with MockTransport tests; `services/gmail/sync.py` (cursor, overlap, paging, dedupe, errors, advisory lock); `app/jobs/gmail_sync.py`; Compose `gmail-sync` service (and the compose test).
- Retention cleanup in the sync run.

## Task 4: Suggestions service and routes (spec §4 actions)
- Accept/dismiss through `change_status`/`apply_action`/`add_application`; stale detection; auto-apply for safe kinds.
- Routes: `GET /api/email/suggestions`, `POST /api/email/suggestions/{id}/accept|dismiss`, `POST /api/email/sync`, Gmail settings fields; boundary tests.

## Task 5: Frontend (spec §7)
- Settings Gmail card; `#/email` page with nav badge; Needs Attention row; application panel Email list; interview suggestions open the Phase 4 add-round form prefilled.
- Tests; svelte-check; build; 390 px check.

## Task 6: Privacy page, guide, docs, review and report (spec §8)
- `privacy.html`, `server-setup.md` Gmail section, README; review; fixes; `docs/phases/phase-6-report.md`; PR.
