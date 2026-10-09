# Phase 6 Design: Gmail Sync

**Date:** 2026-10-09
**Status:** Built overnight at the owner's request ("i would like for A B and C to all be set up"); the owner reviews this design together with the PR. Gmail sync is **off until the owner connects it**, so merging changes nothing for an install that doesn't opt in.
**Builds on:** the Phase 1 design (§12: "Email sync (Gmail OAuth, auto-detect application-related emails) — future phase"), Phase 1b (contacts, statuses, and "drafts open in Gmail compose and the user sends them"), Phase 3 (publishing the Google app, privacy page) and Phase 4 (interview rounds; migration `0007`), Phase 5 (migration `0008`).

## 1. Goal

The tracker notices application-related email so you don't have to update it by hand:
- "Thanks for applying to Stripe" → confirms the application;
- "Unfortunately, we've decided…" → suggests moving it to Rejected;
- "Can you share your availability for an interview?" → suggests adding an interview round (Phase 4);
- an online-assessment link → suggests a note and a follow-up date;
- an offer → suggests moving it to Offer;
- a reply from a contact you emailed → suggests marking the contact Replied; an email you sent to a contact → suggests marking it Sent.

Everything lands as a **suggestion** you accept or dismiss in one tap. Nothing changes on its own unless you turn on auto-apply for the safe kinds.

### Success criteria
- A matching email shows up as a suggestion within 30 minutes of arriving (or right after **Sync now**).
- The app stores no email bodies. It keeps sender, subject, date and Gmail's short snippet for matched emails only, and drops everything else.
- Turning Gmail sync off or disconnecting Google stops all reading at once.
- Tests never contact Google.

## 2. The Google permission, and what it means for publishing

Reading mail needs the `gmail.readonly` scope. Google classes it as **restricted**:
- Publishing an app with a restricted scope for the general public needs Google's verification and a yearly security assessment.
- Google's "verification not needed" list includes **personal use**: an app used by its owner and fewer than 100 users. Such an app skips verification; users click through the "Google hasn't verified this app" screen at sign-in. (support.google.com/cloud/answer/13464323, checked 2026-10-09.)
- Refresh tokens expire after 7 days only while the app is in **Testing**; publishing removes that (developers.google.com/identity/protocols/oauth2, "Refresh token expiration"). Separately, a token that holds a Gmail scope stops working when the Google account password changes; the app then shows "reconnect Google".

So the plan is: the app stays a published personal-use app, Gmail is an **optional, separate consent** (incremental authorization), and the owner accepts the unverified-app screen once when connecting Gmail. The exact console clicks are confirmed live during the deploy walkthrough; if Google's console blocks publishing with the scope declared, the fallback is to request it without declaring it (the unverified screen covers it), and the guide says so.

## 3. Defaults chosen (owner can override)

| Question | Default |
|---|---|
| How is Gmail connected? | A separate **Connect Gmail** button in Settings, which asks Google for `gmail.readonly` on top of the existing Drive permissions (`include_granted_scopes=true`). The Drive connection keeps working if you never press it. |
| How often? | Every 30 minutes (setting: 15–240), plus **Sync now**. |
| How far back on the first sync? | 30 days (setting: 1–90). |
| Which mail? | Inbox and Sent, excluding Promotions, Social and chats: `-category:promotions -category:social -in:chats`. |
| Auto-apply | Off. A setting turns on auto-apply for confirmations and contact replies/sent only; rejections, interviews, assessments and offers always wait for you. |
| What is stored | For matched emails only (mail about a tracked application or from/to a tracked contact, and applicant-tracking-system mail from an untracked company, kept for the "new application" suggestion): Gmail message and thread id, date, sender name and address, subject (≤ 300 chars), snippet (≤ 300 chars). Unmatched emails leave no trace except the sync cursor. |
| How long | Decided suggestions are deleted after 90 days; pending ones stay until decided. |
| Claude | No email data ever goes to the Claude routine. |

## 4. Matching and classification (`app/services/gmail/`)

All rules are local and deterministic.

1. **Contact match.** The sender (inbound) or any recipient (sent mail) equals a tracked contact's email, case-insensitively. Inbound → `contact_reply` (if the contact is `sent` or `followed_up`). Sent → `contact_sent` (if the contact is `to_contact`).
2. **Application match**, for inbound mail only, against non-archived applications:
   - the sender's domain or display name matches the company (normalised: lower case, punctuation and suffixes like "inc", "llc", "technologies" removed; a company token of ≥ 3 letters must equal a domain label or appear in the display name); or
   - the sender is an applicant-tracking system (`greenhouse.io`, `greenhouse-mail.io`, `lever.co`, `hire.lever.co`, `ashbyhq.com`, `myworkday.com`, `myworkdayjobs.com`, `smartrecruiters.com`, `icims.com`, `jobvite.com`, `successfactors.com`, `taleo.net`, `eightfold.ai`, `gem.com`, `rippling.com`, `workablemail.com`) and the company name appears in the display name, subject or snippet.
   - If several applications at that company match, the role title in the subject/snippet picks one; otherwise the most recently updated.
3. **Classification** of the subject + snippet (whole-phrase, case-insensitive), first match wins, in this order:
   - `offer`: "offer letter", "pleased to offer", "extend an offer", "offer of employment";
   - `rejection`: "unfortunately", "not moving forward", "move forward with other", "decided not to proceed", "no longer under consideration", "will not be moving";
   - `interview`: "interview", "schedule a call", "your availability", "next steps", plus links to calendly.com, goodtime.io, or a scheduling page;
   - `assessment`: "online assessment", "coding challenge", "hackerrank", "codesignal", "codility", "take-home";
   - `confirmation`: "thank you for applying", "application received", "received your application", "thanks for your interest", "application has been submitted".
   - A job-related sender with none of these is ignored.
4. **Unmatched job mail.** An ATS sender whose company has no application becomes a `new_application` suggestion ("Add Rivian — Software Intern to your tracker?"), with the company taken from the display name.

### Suggested actions
| Kind | Suggestion | Accepting does |
|---|---|---|
| confirmation | Mark applied | status → `applied` (only if `wishlist`), sets `date_applied` if empty |
| rejection | Move to Rejected | status → `rejected` |
| interview | Add an interview round | opens the Phase 4 add-round form prefilled (kind from the text: "phone screen"/"recruiter" → `recruiter_screen`, "technical"/"coding" → `technical`, else `other`), status → `interview` if earlier |
| assessment | Note + follow-up | appends "Online assessment received <date>" to notes, sets `follow_up_date` = +7 days |
| offer | Move to Offer | status → `offer` |
| contact_reply | Mark replied | contact action `replied` |
| contact_sent | Mark sent | contact action `sent` with the email's date |
| new_application | Add to tracker | creates the application as `applied` |

Status changes go through the existing `change_status` and `apply_action` services, so history, contact auto-queueing and sheet sync behave as if you clicked. A suggestion whose action is no longer valid (status already moved, contact already replied) is marked `stale` and hidden.

## 5. Data (migration `0009_gmail_sync`)

### `email_suggestions`
id; `gmail_message_id` (unique); `gmail_thread_id`; `received_at`; `direction` (`inbound`/`sent`); `from_name`, `from_email`; `subject`; `snippet`; `kind` (enum above); `application_id` FK SET NULL; `contact_id` FK SET NULL; `proposed_company`, `proposed_role` (for `new_application`); `state` (`pending`, `accepted`, `dismissed`, `stale`, `auto_applied`); `created_at`, `decided_at`.

### `app_settings`
`gmail_sync_enabled` (bool, default false), `gmail_sync_minutes` (30), `gmail_lookback_days` (30), `gmail_auto_apply` (bool, false), `gmail_last_sync_at`, `gmail_last_error`, `gmail_history_cursor` (text; the newest `internalDate` processed, in ms).

### OAuth token
The callback now stores the scopes **Google actually granted** (the `scope` field of the token response) instead of the requested constant, so the app knows whether Gmail is granted. A `gmail` flag on the authorize route adds `gmail.readonly` and `include_granted_scopes=true`.

## 6. Sync job

- New Compose service `gmail-sync` (`python -m app.jobs.gmail_sync`), same pattern as `job-scan`: a loop every `gmail_sync_minutes`, skipping quietly while sync is disabled or the scope isn't granted. An advisory lock prevents overlap with **Sync now**.
- Each run: `messages.list` with `q = <filters> after:<cursor seconds − 1 hour overlap>` (first run: `newer_than:<lookback>d`), paging up to 500 messages per run; then `messages.get?format=metadata&metadataHeaders=From,To,Cc,Subject,Date` for each new id (skipping ids already in `email_suggestions` or below the cursor). Bodies are never requested.
- Errors: 401/403 → "reconnect Google and allow Gmail" in Settings; 429/5xx → retry next run; the cursor only advances past fully processed messages.
- Cursor (review fix): never later than the run's start time (a future-dated message can't hide later mail). After each message it moves to that message's date, the last one handled in list order, so a run that stops early (an error, the 500-fetch cap, sync turned off) doesn't jump past mail it hasn't handled; a run that handled everything it listed moves it to the newest date seen, as does a capped run that couldn't move it at all (so out-of-order dates can't make it handle the same messages forever).
- A message that fails to process for any reason other than a Gmail/Google error is rolled back, logged by exception type and Gmail id only, counted as skipped, and passed over. The database engine hides SQL parameters in error messages.
- A run re-checks after each message that sync is still on and Gmail still granted, and stops if not. Sync on without the Gmail permission (Google revoked it, or a Drive-only reconnect dropped it) records "Gmail permission missing: use Reconnect Gmail in Settings".
- Limits: at most 500 message fetches per run (the rest wait for the next run), and at most 5,000 ids listed per run, newest first: if one query window holds more than 5,000 messages, the older ones beyond that are never looked at.
- Client `GmailClient(access_token, transport)` with `httpx.MockTransport` fakes in tests, like the Drive client. Error messages carry no response bodies or tokens.

## 7. UI

- **Settings → Gmail** card: Connect Gmail (or "Connected"), on/off toggle, interval, lookback, auto-apply toggle with its one-line explanation, last sync time and error, **Sync now**, and a sentence on what is and isn't stored.
- **Email updates** (`#/email`, in the nav with a pending count badge): suggestions grouped Pending / Recent decisions, each with sender, subject, snippet (as text), date, the matched application or contact, **Accept**, **Dismiss**, and **Open in Gmail** (`https://mail.google.com/mail/u/0/#all/<thread id>`).
- **Dashboard**: the Needs Attention widget gains an "N email updates to review" row linking to the page.
- **Application panel**: an "Email" list of that application's suggestions and accepted updates.
- 390 px wide works.

## 8. Privacy page and docs
- `privacy.html` adds `gmail.readonly`: what is read (headers and Gmail's snippet of recent Inbox and Sent mail), what is kept (matched emails' sender, subject, date and snippet; unmatched mail is not stored), that bodies are never downloaded, that it is optional and off by default, and how to turn it off.
- `docs/deploy/server-setup.md` gains a "Turn on Gmail sync (optional)" section: enable the Gmail API in the Cloud project, add the scope, the unverified-app screen, Connect Gmail.
- README feature list.

## 9. Security
- The Gmail scope is read-only; the app has no way to send, delete or label mail.
- Email text is untrusted: capped, stored and shown as text, never rendered as HTML, never followed as a link except the Gmail thread link the app builds itself from the id.
- The Claude token gains nothing.

## 10. Testing
- Classifier and matcher tables (dozens of realistic subject/snippet/sender cases, including false-positive traps like newsletters mentioning "interview").
- Sync run against a fake Gmail transport: paging, cursor, overlap de-duplication, metadata-only requests (assert no `format=full`/`raw`), 401/403/429 handling, disabled/not-granted skipping.
- Accepting each kind through the real services on Postgres; stale detection; auto-apply limited to the safe kinds; retention cleanup.
- OAuth: granted-scope storage, the `gmail` authorize flag, Settings exposure.
- Frontend: Settings card states, Email updates page, Dashboard row, panel list.

## 11. Out of scope
- Sending, labelling or archiving mail.
- Reading attachments or full bodies; using Claude to classify email.
- Calendar invites (`.ics` attachments) and Google Calendar.
- Outlook or other providers.
