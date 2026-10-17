# Phase 7 Design: Email Replies on the Dashboard, and More Than One Gmail Inbox

**Date:** 2026-10-16
**Status:** Requested by the owner on 2026-10-16: "i want to add a cold email block to the dashboard where it will give me a one line summary preview of emails that i heard back from. as well as the application tabs: interview, offer, rejected. also can i make it so i can add multiple emails that i can track?" The owner reviews this design with the PR.
**Builds on:** Phase 6 (Gmail sync, `email_suggestions`, migration `0009`), the Phase 1 Dashboard grid and its layout reconciliation (Phase 4 added a widget the same way).

## 1. Goal

1. A Dashboard block, **Email replies**, with four tabs, each a list of one-line previews:
   - **Cold emails**: replies from people you contacted (inbound mail matched to a tracked contact);
   - **Interviews**, **Offers**, **Rejections**: application emails of that kind.
2. Gmail sync can read **more than one inbox** (for example a personal Gmail and a school Google account), so replies to cold emails sent from any of them are tracked.

Reading taken for "add multiple emails that I can track": more than one Gmail inbox. Every inbox must be a Gmail or Google Workspace account; Outlook isn't covered.

## 2. Defaults chosen (owner can override)

| Question | Default |
|---|---|
| What is a "one-line preview"? | Date · sender (name, else address) · company or contact · subject, then Gmail's preview text, cut to one line with an ellipsis. No AI summary (there is no in-app Claude API). |
| Which emails count? | Everything Gmail sync matched in the last 90 days (the existing retention), whatever you did with it (pending, accepted, applied automatically, or already out of date), except ones you dismissed. Pending ones carry a **To review** tag that links to Email updates. |
| How many rows? | The newest 8 per tab, with the tab's total count and **See all in Email updates**. |
| Clicking a row | Opens the thread in Gmail (new tab), in the right inbox. |
| Removing an inbox | Deletes that inbox's stored email updates. Changes already applied to applications and contacts stay. |
| Where the Dashboard block goes | A new full-width row at the bottom; saved layouts get it through the existing reconciliation. |

## 3. Dashboard block

### Backend: `GET /api/email/highlights?limit=8` (cookie auth; `limit` 1–20)

```json
{
  "gmail_granted": true,
  "tabs": {
    "replies":   {"count": 3, "items": [EmailSuggestionOut, ...]},
    "interview": {"count": 1, "items": [...]},
    "offer":     {"count": 0, "items": []},
    "rejection": {"count": 2, "items": [...]}
  }
}
```

- Every tab: `direction = inbound`, `state != dismissed`, newest `received_at` first, then id.
- `replies`: `contact_id IS NOT NULL` (any kind: a contact's reply that is also an interview invitation shows in both tabs).
- `interview`, `offer`, `rejection`: `kind` equals the tab's kind.
- `count` is the total that matches; `items` the first `limit`.
- Items use the existing `EmailSuggestionOut`, which now also carries `account_email` (§4).

### Frontend: `EmailReplies.svelte` widget, id `email-replies`, title "Email replies"

- Tabs: **Cold emails** (replies), **Interviews**, **Offers**, **Rejections**, each with its count. One request on mount.
- A row is one line: date (e.g. "Oct 14"), sender, then "Company — Role" for application emails or "Contact, Organization" for replies, then the subject and the preview in a muted colour, cut with `text-overflow: ellipsis`; the full text is in the row's `title`. The row is a link to `gmail_url` (`target="_blank" rel="noopener noreferrer"`, only when `safeGmailUrl` accepts it). Pending rows show a **To review** tag linking to `#/email`.
- Below the list: **See all in Email updates** (`#/email`).
- States: loading; error with Retry; Gmail not connected ("Connect Gmail in Settings to see replies here", link to `#/settings`); a tab with no rows ("No cold email replies yet." etc.).
- Email text is untrusted: rendered as text only, never `{@html}`.
- Fits at 390 px (the row stays one line and truncates).

## 4. More than one Gmail inbox

### Data (migration `0010_gmail_accounts`)

New table `gmail_accounts`:

| Column | Notes |
|---|---|
| id | PK |
| email | text, unique, nullable (null only for an inbox carried over from Phase 6 until its first sync reads the address) |
| encrypted_refresh_token | bytea, Fernet like `oauth_tokens` |
| scopes | text, the scopes Google granted |
| history_cursor | text, moved from `app_settings.gmail_history_cursor` |
| last_sync_at, last_error | per inbox |
| created_at, updated_at | |

`email_suggestions` gains `gmail_account_id` (FK → `gmail_accounts.id`, `ON DELETE CASCADE`, nullable, indexed). The unique key on `gmail_message_id` becomes unique on `(gmail_account_id, gmail_message_id)`: Gmail message ids are per mailbox.

Data migration: if the `google` row in `oauth_tokens` holds `gmail.readonly`, copy its encrypted refresh token and scopes into a new `gmail_accounts` row (email null), with `history_cursor`, `last_sync_at` and `last_error` from `app_settings`, and point every existing suggestion at it. `app_settings.gmail_history_cursor` is dropped. `app_settings.gmail_last_sync_at` and `gmail_last_error` stay as the whole run's summary (§4 Sync). Downgrade puts the cursor back from the oldest inbox, restores the unique key (keeping only the oldest inbox's suggestions), and drops the table and column.

### Connecting an inbox

- **Connect Gmail** and **Add another inbox** both go to `GET /api/docs/google/authorize?gmail=1`, which now asks for `gmail.readonly` **only**, with `prompt=consent select_account` (Google shows the account chooser) and no `include_granted_scopes`. So each inbox has its own token and the Drive/Docs connection is never touched.
- The callback (state prefix `gmail.` as today) exchanges the code and, when `gmail.readonly` was granted, asks Gmail for the inbox's address (`GET gmail/v1/users/me/profile` → `emailAddress`, allowed by `gmail.readonly`) with the new access token. It then upserts the `gmail_accounts` row by lower-cased address: a new inbox is added; an existing one gets the new token and its error cleared (that's **Reconnect**). It redirects to `/#/settings?gmail=1`, or `gmail=0` when the box wasn't ticked or consent was cancelled. Errors never carry tokens or response bodies.
- `is_gmail_granted(db)` now means "at least one inbox is connected"; the Settings `gmail_granted` flag follows it. **Connect Google Docs** no longer affects Gmail.
- A token refresh failing with 400/401 on one inbox records "reconnect this inbox in Settings" on that inbox only.

### Routes (cookie auth)

- `GET /api/email/accounts` → `[{id, email, last_sync_at, last_error, created_at}]`, oldest first.
- `DELETE /api/email/accounts/{id}` → 204; deletes the inbox and, by cascade, its suggestions. 404 if unknown. Nothing is revoked at Google (a revocation would also end the Drive connection when it is the same Google account); the Settings card says how to withdraw access completely.
- `GET /api/email/status` and the Sync now response gain `accounts` (the same list).
- `EmailSuggestionOut` gains `account_email` (null when unknown). `gmail_url` uses the inbox: `https://mail.google.com/mail/u/<url-encoded address>/#all/<thread id>`, falling back to `/mail/u/0/` when the address isn't known.

### Sync

- One run (job or Sync now, still under the one advisory lock) handles every inbox, oldest first, each with its own client, cursor and lookback. A failure on one inbox is recorded on that inbox and the run goes on to the next.
- An inbox with no address yet reads it from Gmail's profile first. If another inbox already has that address, the carried-over row's suggestions move to it and the row is removed.
- The run's summary on `app_settings`: `gmail_last_sync_at` is set when at least one inbox synced; `gmail_last_error` lists the failing inboxes ("you@school.edu: reconnect this inbox in Settings"), or is cleared. The report's counts are summed over inboxes.
- Matching is unchanged and sees mail from every inbox, so a cold email sent from any inbox and its reply are both tracked. The same message delivered to two inboxes can produce two suggestions (known limitation).

### Settings → Gmail card

- A list of connected inboxes: address (or "Gmail inbox, address shown after the next sync"), last sync, its error if any, **Reconnect** (to `authorize?gmail=1`) and **Remove** (asks first: "Remove you@x.com? Its email updates are deleted from the tracker. Changes you already accepted stay.").
- **Connect Gmail** when there is none, **Add another inbox** otherwise. The sync switch, interval, lookback and auto-apply stay global.
- On the Email updates page, a card shows "to you@school.edu" when more than one inbox is connected.

## 5. Privacy and docs

- `privacy.html`: Gmail access can cover several inboxes you connect; removing one deletes its stored data.
- `docs/deploy/server-setup.md` "Turn on Gmail sync": add another inbox; Connect Google Docs no longer drops Gmail; a password change on one Google account needs **Reconnect** on that inbox (and Connect Google Docs if it is the Drive account). Troubleshooting rows updated.
- README Gmail section.

## 6. Testing

- Highlights: tab rules (inbound only, dismissed excluded, stale included, contact rule, kinds), counts vs. limit, ordering, auth boundary.
- Migration 0010 up/down/up with and without a Phase 6 Gmail connection, suggestions carried over.
- OAuth: Gmail-only scope and account chooser on authorize; callback upserts by address, Reconnect replaces the token, the Drive row untouched, cancelled and not-granted consent, profile failure (502, nothing stored).
- Sync over two fake inboxes: per-inbox cursor and errors, one failing doesn't stop the other, the carried-over row learning its address and merging, summary fields.
- Accounts routes, cascade delete, `gmail_url` per inbox.
- Frontend: widget tabs, counts, rows, links, states, To review tag; Settings inbox list, Add/Reconnect/Remove with confirm; card "to" line. Nothing contacts Google.

## 7. Out of scope

- Outlook or other providers; sending mail; AI summaries of email.
- De-duplicating one message delivered to two inboxes.
