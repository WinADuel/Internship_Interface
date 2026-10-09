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
