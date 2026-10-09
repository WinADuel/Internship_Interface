# Phase 6 Report: Gmail Sync

| | |
|---|---|
| **Status** | Complete on branch `phase-6-gmail-sync`. The owner reads this report and merges the PR after Phases 3, 4 and 5 (PRs #3, #4, #5); nothing has been merged to `main`. |
| **Built** | 2026-10-09, overnight, at the owner's request ("i would like for A B and C to all be set up if possible"). The design uses the defaults in its §3; the owner reviews them with this PR. |
| **Branch** | `phase-6-gmail-sync`, stacked on `phase-5-inbox-ranking`. Until PRs #3–#5 are merged, this PR's diff also contains them. |
| **Spec** | [`docs/superpowers/specs/2026-10-09-gmail-sync-design.md`](../superpowers/specs/2026-10-09-gmail-sync-design.md) |
| **Plan** | [`docs/superpowers/plans/2026-10-09-gmail-sync-phase6.md`](../superpowers/plans/2026-10-09-gmail-sync-phase6.md) (6 tasks) |
| **Detailed log** | [`phase-6-progress.md`](phase-6-progress.md) |
| **Tests at finish** | Backend: 2193 passing on PostgreSQL 16 (Phase 5: 1841). Frontend: 660 passing (Phase 5: 566). `svelte-check` 0/0, build clean, `alembic check` clean. |

---

## 1. What Phase 6 delivers

The tracker reads your application email and suggests the update, so you don't have to make it by hand. **It is off until you connect it**, so merging changes nothing until you opt in.

- **Connect Gmail** in Settings → Gmail asks Google for read-only Gmail access on top of the existing Drive permission. Drive keeps working if you never press it.
- Every 30 minutes (15–240, or **Sync now**) the app reads the headers and Gmail's short preview of new Inbox and Sent mail, skipping Promotions, Social and chats. It looks back 30 days the first time (1–90).
- Matching email becomes a suggestion on the new **Email updates** page, with a count in the nav and on the Dashboard:
  - "Thanks for applying" → **Mark applied**;
  - "Unfortunately…" → **Move to Rejected**;
  - an interview invitation → **Add an interview round**, opening the Phase 4 round form prefilled;
  - an online assessment → a note and a follow-up date a week out;
  - an offer → **Move to Offer**;
  - a reply from a contact you emailed → **Mark replied**; an email you sent to a contact → **Mark sent**;
  - applicant-tracking mail from a company you don't track → **Add to tracker**.
- Each card shows the sender, subject, preview and the application it will change, with **Accept**, **Dismiss** and **Open in Gmail**. The application panel lists that application's email updates.
- Nothing changes by itself. An **auto-apply** setting (off by default) applies only confirmations and contact replies/sent; rejections, interviews, assessments and offers always wait for you.
- **What is kept:** for suggestions only, the sender, subject, date and Gmail's preview (each capped at 300 characters). Email bodies are never downloaded. Decided suggestions are deleted after 90 days. No email data goes to the Claude routine.

## 2. How it was built

Six tasks: the Google consent, the matcher and classifier, the data and sync job, the suggestion service and routes, the frontend, and the docs. Phases 4 and 5 were merged in as they finished. The lead reviewed every report and recorded the rulings.

- **End-to-end walk** against a real backend with 17 seeded suggestions and no network: every kind accepted and dismissed with the expected effect, stale and double accepts handled, and the pages checked at 390 px and 320 px. It found one bug (a second return from Google's consent screen showed no message), now fixed.
- **Review.** No security problems. Five Important findings, all fixed with tests:
  - common rejections ("we have decided not to move forward", "regret to inform", "unable to offer you a position") were read as confirmations, and some confirmations as interview invitations;
  - the privacy page said less was kept than really is (untracked companies' applicant-tracking mail is kept as an Add to tracker suggestion);
  - the password-change and reconnect docs missed that Gmail and Drive share one connection;
  - a decided card stayed clickable until the list reloaded;
  - a suggestion from a contact didn't say which application it would change.

  The Minor findings are fixed too: the sync cursor's edge cases, one bad email blocking every later one, email text in database error logs, a contact's reply lost when the application had already moved on, two simultaneous decisions, turning sync off mid-run, a silent missing permission, the pending count, the 100-card limit, button names for screen readers, and a Retry when status fails to load.

| Task | Commits |
|---|---|
| Design, plan, progress log | `a5b2425`, `dc3608b`, `8a07ea1` |
| 1. Granted scopes and the Gmail consent | `f7ebae9` |
| 2. Matcher and classifier | `d7c7adf` |
| 3–4. Migration 0009, Gmail client, sync job, suggestions and routes | `df8087f`, `a4019d5` |
| 5. Frontend | `f35a1ff`, `c3d1c7f` |
| 6. Privacy page, setup guide, README | `7f2f613` |
| Review fixes | `de31341`, `a36fddf`, `3d0d213` |

## 3. Decisions worth knowing

- **Google's permission.** `gmail.readonly` is a restricted scope. Google exempts personal-use apps (the owner plus fewer than 100 users) from verification; you click through "Google hasn't verified this app" once when connecting Gmail. The app stays published, so the token doesn't expire after 7 days.
- **A password change disconnects Google.** A token holding a Gmail scope is revoked when your Google password changes. That stops Drive backups and Essays as well as Gmail sync. Use **Reconnect Gmail** in Settings, not Connect Google Docs, or Gmail access is dropped again.
- **Classification is local and rule-based**, with wording guards against newsletters and promises ("If we decide not to move forward, we'll let you know" is a confirmation). It will miss some unusual wording; a missed email just produces no suggestion.
- **The cursor.** Each run reads mail after the last one handled, less an hour of overlap. Without storing ids of mail it ignores, no scheme catches every out-of-order message; one that arrives more than an hour late (mail fetched from another account, say) can be missed.
- **Errors.** A Gmail outage stops the run and the next one retries; one email that fails to process is skipped and counted, so it can't block the rest. Errors never quote email text.

## 4. Known limitations

- Tested only against fake Gmail and Google. The real consent screen, granular consent's reply and Gmail's list order are confirmed during the deploy walkthrough.
- The Google Cloud console clicks in the setup guide are written from Google's documentation. If the console won't publish with the scope declared, the guide's fallback is to request it without declaring it.
- **Sync now** was not pressed in the walk, because it calls Google.

## 5. What's next

- Merge in order: #3, #4, #5, then #6.
- After the deploy, follow "Turn on Gmail sync (optional)" in `docs/deploy/server-setup.md`: enable the Gmail API, press **Connect Gmail**, accept the unverified-app screen, turn sync on, and press **Sync now** once.
