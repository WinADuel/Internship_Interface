# Phase 6 Progress Log: Gmail Sync

Spec: `docs/superpowers/specs/2026-10-09-gmail-sync-design.md`. Plan: `docs/superpowers/plans/2026-10-09-gmail-sync-phase6.md`.
Branch `phase-6-gmail-sync`, stacked on `phase-5-inbox-ranking` (it starts from `phase-4-interview-prep` and merges Phase 5 in before the Phase 6 migration).

The owner asked on 2026-10-09 for interview prep, Discover inbox ranking and Gmail sync to be built overnight. The design uses the defaults in its §2; the owner reviews them with the PR.

## Task log

### Task 1: OAuth granted scopes and the Gmail consent — `f7ebae9`
The callback stores the scopes Google granted; `authorize?gmail=1` adds `gmail.readonly` with `include_granted_scopes=true`. The flow is marked by a `gmail.` prefix on the state value and read only after the state matches the cookie. Settings expose computed `google_connected` and `gmail_granted`.
Rulings: a cancelled consent (no `code`) now redirects back to Settings or Essays instead of a 422 page. Accepted. Real Google behaviour (granular consent's `scope` value, the `error=` redirect) is verified only with fakes; confirm during the live walkthrough.

### Task 2: Matcher and classifier — `d7c7adf`
Backend 1762 passed. Pure functions in `app/services/gmail/` (`classify`, `propose`, `match_contact`, `match_application`, helpers).
Rulings:
- Extra guards beyond the spec (conditional "interview" phrasing, "interview process", "next steps" inside confirmations, assessment beats weak interview words, "unfortunately … reschedule", job-word requirement for direct company mail, job-board/newsletter senders skipped, ATS subject search only when the display name names no company) are accepted: they target the false positives the spec asked to test.
- No `new_application` suggestion from a rejection. Accepted.
- Contact match vs application kind: when inbound mail matches a contact **and** classifies as interview, rejection, offer or assessment, the suggestion is the application kind (with the contact's application and `contact_id` set), and accepting it also marks the contact Replied when that transition is valid. A plain reply stays `contact_reply`. Task 4 implements this; `propose` changes accordingly.
- Task 3 leaves archived contacts out of the snapshot. Task 4 checks validity against current status (stale).

### Tasks 3–4: data, Gmail client, sync job, suggestions and routes — `df8087f`, `a4019d5`
Backend 2103 passed; 2118 after merging Phase 4's review fixes (`5df926a`). Migration 0009 upgrade/downgrade/upgrade tested.
Rulings:
- A contact's reply that classifies as interview, rejection, offer or assessment becomes that kind with `contact_id` set (its own application, else the sender's company) and needs a job word, so "Unfortunately I'm out this week" stays a plain reply. Accepted (implements the Task 2 ruling).
- One pending `new_application` suggestion per untracked company; a suggestion that doesn't apply when found is stored `stale` so the message isn't fetched again. Accepted.
- `gmail-sync` joins `APP_SERVICES` (stopped during a restore), with a test that the list equals every Compose service except `db`. Accepted.
- Stale rules: confirmation applies only while `wishlist` or `date_applied` is empty; rejection/interview/assessment stop applying at `rejected` or `offer`; offer stops at `offer`; anything stops when the application is archived or deleted. A rejection arriving for an application already at Offer is stale. Accepted.
- Dates written on accept (date applied, the assessment follow-up, contact sent/replied) use the email's date. New applications from email get role "Role not given" and source "Gmail". Accepted.
- **Sync now** runs synchronously (like Back up now). Accepted.
- To check in review: the sync cursor's reliance on Gmail listing newest first.

### Tasks 5–6: frontend, privacy page and docs — `f35a1ff`, `7f2f613`, `c3d1c7f`
Frontend 594 passed (Phase 5: 566 before the merge). Email updates page (`#/email`), Settings → Gmail card, nav badge, Needs Attention row, application panel Email list; `privacy.html`, the setup guide's "Turn on Gmail sync (optional)" section, README.
Rulings:
- Interview suggestions open the existing round form prefilled; `RoundForm` gains optional `defaultKind`, `submitLabel` and `create` props, unchanged for normal use. Accepted.
- **Open in Gmail** shows only when the link parses as https on `mail.google.com`. Accepted.
- End-to-end walk against a real backend with 17 seeded suggestions (no network; Google's token URL pointed at a closed local port): every kind accepted and dismissed with the expected effect, stale and double accepts handled, badges and limits correct, 390 px and 320 px without sideways scroll. It found one bug: a second consent return to an open Settings page showed no toast (`c3d1c7f`, with a test). **Sync now** was not pressed (it would call Google); it is covered by mocked tests.

## Whole-branch review
Two reviewers: backend/ops/docs and frontend. No security problems found. Backend: three Important (rejections classified as confirmations, the privacy page overstating what is filtered, password-change and reconnect docs), four Minor (cursor edge cases, one bad message blocking sync and SQL parameters in logs, a contact's reply lost when its application update no longer applies, accept/dismiss row lock), plus the missing-grant error, stopping a run when sync is turned off, and the README stop command. Frontend: two Important (a decided card stays clickable until the reload, application-kind labels from a contact hide which application changes), four Minor (pending count ordering, the silent 100 limit, button names, no Retry when the status request fails) and test gaps.

All fixed in `de31341` (backend), `a36fddf` (frontend), `3d0d213` (docs). Backend 2193 passed, frontend 660, check 0/0, build clean, `alembic check` clean.
Rulings:
- "Candidates whose" counts as a rejection only after a decision ("decided to move forward with … candidates"); "we will only contact candidates whose qualifications match" stays a confirmation. Accepted.
- Rejection phrases inside an if/unless clause don't count ("If we decide not to move forward, we'll let you know"). Accepted.
- Refused offers ("unable to offer you a position") are checked before offers and classify as rejections. Accepted.
- Cursor: capped at the run's time; after each message it moves to that message's date (the last handled in list order); a complete run moves it to the newest date seen; a capped run that couldn't move it at all also jumps to the newest, so out-of-order mail can't make every run repeat the same messages. No scheme is fully safe without storing ids of unmatched mail, which the spec rules out; the hour of overlap covers small disorder. `MAX_LIST` is now in spec §6. Accepted.
- Gmail and Google auth errors still stop the run (an outage must not skip 500 messages); any other per-message failure is rolled back, logged as type and Gmail id only, counted as `skipped` and passed over. The engine sets `hide_parameters=True`. Accepted.
- Turning sync off mid-run ends the run as "disabled" without setting the last-sync time. Sync on without the Gmail grant records "Gmail permission missing: use Reconnect Gmail in Settings", and the Settings link and Email page say **Reconnect Gmail** to match. Accepted.
- The Settings blurb and README got the same "what is kept" correction as the privacy page. Accepted.
- Commit order: `a36fddf` updates the privacy-page test whose page change is in `3d0d213`, so that one test fails at `a36fddf` alone and passes from `3d0d213`. History is not rewritten. Noted.
- Not verified: real Gmail list ordering, the real consent screens, and phone width of the new status lines.
