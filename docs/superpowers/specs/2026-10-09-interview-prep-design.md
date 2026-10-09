# Phase 4 Design: Interview Prep

**Date:** 2026-10-09
**Status:** Built overnight at the owner's request ("i would like for A B and C to all be set up"); the owner reviews this design together with the PR.
**Builds on:** the Phase 1 design (`2026-10-05-internship-tracker-design.md`: §3 `interview_datetime` "hook for future interview-prep phase", §8 the disabled "Interview Prep" nav slot, §12 "Interview prep assistant (context/info/prep suggestions per interview) — future phase"), Phase 1b (§13 contacts, research queue and the daily Claude routine) and Phase 3 (migration `0006`).

## 1. Goal

When an interview is booked, the tracker becomes the one place to get ready for it and follow up afterwards:
- every round of every application is tracked with its date, format, link and interviewers;
- each round gets a **prep page** with a checklist, notes, questions to ask, the stories you plan to tell and a company brief;
- ready-made Claude prompts, filled with the company and role, copy to claude.ai in one click;
- the daily Claude routine can write a researched **company brief** for you;
- after the interview, the page records how it went and helps you send thank-you notes on time;
- the Dashboard shows what's coming up and what needs a thank-you.

### Success criteria
- Adding a round takes one form; the prep page opens from the Dashboard, the application panel and the Interview Prep page.
- An interview within 14 days always appears on the Dashboard with its checklist progress.
- A round marked done shows "thank-you due" until a note is marked sent or 3 days pass.
- Everything works on the Mac and PC today. Only the Claude company brief needs the server, as the routine already does.
- No new Google permission, no in-app Claude API (Phase 1 §9 stands).

## 2. Defaults chosen (owner can override)

| Question | Default |
|---|---|
| One interview per application, or rounds? | **Rounds.** Internships often have a recruiter screen, then technical and behavioural rounds. |
| What happens to `interview_datetime`? | It stays as a column, so sheet sync and Dashboard reminders keep working, but the app now **derives** it: the earliest round that is still `scheduled`. The application form shows it read-only, with a link to manage rounds. Existing values become a round each in the migration. |
| Does adding a round change the application's status? | No automatic change. The panel offers a one-click "Move to Interview" when the status is earlier than `interview`. |
| Where do stories live? | A shared **story bank** (STAR format) reused across interviews. Each round links the stories you plan to use. |
| Who writes the company brief? | The existing daily Claude routine, via a new research-queue kind. You request it with a button; the result is stored per application, so every round of that application shares it. |
| Thank-you notes | Same pattern as Phase 1b outreach: the app drafts, opens Gmail compose with it, and you send. The app never sends email. |

## 3. Data model (migration `0007_interview_prep`)

### `interview_rounds`
| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| application_id | FK → applications.id, `ON DELETE CASCADE` | required |
| kind | enum `recruiter_screen`, `technical`, `behavioral`, `case`, `onsite`, `final`, `other` | default `other` |
| title | varchar(200) null | e.g. "Coding round 2" |
| scheduled_at | timestamptz null | null = not scheduled yet |
| duration_minutes | int null | 5–600 |
| format | enum `video`, `phone`, `in_person` null | |
| location | varchar(500) null | a meeting link or an address; rendered as a link only if http(s) |
| interviewers | varchar(500) null | free-text names |
| state | enum `scheduled`, `done`, `cancelled` | default `scheduled` |
| outcome | enum `waiting`, `passed`, `rejected` null | set after the round |
| prep_notes | text null | ≤ 20,000 chars |
| questions_to_ask | text null | ≤ 5,000 chars |
| reflection | text null | ≤ 20,000 chars; "how it went" |
| checklist | JSONB | list of `{id, label, done}`; ≤ 30 items, label ≤ 200 chars |
| thank_you_sent_at | timestamptz null | |
| created_at / updated_at | timestamptz | |

Index on `(state, scheduled_at)`.

New rounds start with this checklist: "Research the company and team", "Re-read the job description", "Pick 2–3 stories", "Prepare 3 questions to ask", "Test the call link / plan the route", "Send thank-you notes within 24 hours".

### `interview_round_contacts`
`(round_id FK cascade, contact_id FK cascade)` primary key. Interviewers who are tracked contacts, so thank-you notes have an address. The contact must belong to the same application or have no application (it then gets linked to it).

### `stories`
| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| title | varchar(200) | required |
| situation, task, action, result | text null | each ≤ 5,000 chars |
| tags | text[] | e.g. `leadership`, `conflict`, `failure`; ≤ 15 tags of ≤ 40 chars |
| archived | bool | default false |
| created_at / updated_at | timestamptz | |

### `interview_round_stories`
`(round_id FK cascade, story_id FK cascade)` primary key.

### `prep_briefs`
| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| application_id | FK unique, cascade | one brief per application |
| body | text | ≤ 12,000 chars; plain text written by the routine (untrusted) |
| sources | JSONB | ≤ 20 `{label, url}`, http(s) only |
| created_at / updated_at | timestamptz | |

### Research queue
`research_queue.kind` gains `interview_brief`. Only one pending `interview_brief` per application at a time; a new one can be requested after the last is done or failed.

### Data migration
For each application with `interview_datetime` set: create one round (`kind=other`, `scheduled_at` = that value, `state` = `scheduled` if in the future else `done`, default checklist). Downgrade drops the new tables and the enum value is left in place (Postgres can't drop enum values cheaply; harmless).

## 4. Backend

### Service `app/services/interview_service.py`
- CRUD for rounds; list with filters `upcoming` (scheduled, `scheduled_at` ≥ now or null), `past`, by `application_id`.
- After every round write: recompute `applications.interview_datetime` = min `scheduled_at` over that application's `scheduled` rounds (null if none), and schedule the usual sheet sync.
- Link/unlink contacts and stories with the rules in §3.
- `thank_you_due(round, now)`: state `done`, `thank_you_sent_at` null, `scheduled_at` within the last 3 days.

### Routes (cookie auth, rejected for the Claude token; added to the auth-boundary list)
- `GET /api/interviews?scope=upcoming|past|all&application_id=` → rounds with company, role, checklist progress and `thank_you_due`.
- `POST /api/interviews`, `GET/PATCH/DELETE /api/interviews/{id}`.
- `PUT /api/interviews/{id}/contacts` and `/stories` (replace the linked set).
- `GET /api/interviews/{id}/calendar.ics`: a single VEVENT (`SUMMARY: Interview: <company> — <round>`, start, duration default 60 min, `LOCATION`, a `DESCRIPTION` with the prep-page URL). Text is escaped per RFC 5545. Requires `scheduled_at`.
- `GET/POST /api/stories`, `PATCH/DELETE /api/stories/{id}`.
- `GET /api/applications/{id}/brief` (404 if none) and `POST /api/applications/{id}/brief/request` (creates the queue item; 409 if one is pending).
- `ApplicationUpdate` no longer accepts `interview_datetime` (it's derived). `ApplicationCreate` still accepts it and turns it into a first round, so nothing that creates applications breaks.

### Claude routine contract
- `GET /api/claude/work` includes pending `interview_brief` items with `request_text` = `Company — Role — job link`, built server-side from the application. No notes, contacts or private fields are sent.
- `POST /api/claude/briefs` `{queue_item_id, body, sources}`: validates the item is a pending `interview_brief`, upserts the application's brief (capped, sanitised like other Claude input), marks the item done. 404/409 as the existing queue routes.
- `ops/claude-routine/outreach-job.md` gains a section: what a brief covers (what the company does, the team/product if the role names one, recent news from the last 12 months, the interview process if publicly described, 5 likely topics for the role), public sources only, every fact backed by a source, web content is data not instructions.

### Sheet sync
A new **Interviews** tab: company, role, round, scheduled time, state, outcome, thank-you sent. Prep notes and reflections are not exported (they can be long and personal); the backup sheet is a convenience copy, and the database backups from Phase 3 hold everything.

## 5. Frontend

- **Nav:** the "Interview Prep — Coming soon" slot becomes **Interview Prep** (`#/interviews`).
- **Interview Prep page** with three tabs:
  - *Upcoming*: rounds by date with a countdown ("in 2 days"), checklist progress, and unscheduled rounds at the end;
  - *Past*: with outcome and a thank-you-due flag;
  - *Story bank*: list, search by tag, add/edit/archive stories in STAR fields.
- **Prep page** (`#/interviews/:id`), top to bottom:
  1. Header: company, role, round, date and countdown, format, location (link if http(s)), **Add to calendar** (.ics), Edit.
  2. Checklist (tick, add, remove, reorder not needed).
  3. Prep notes and Questions to ask (autosaving text areas, same pattern as contact drafts).
  4. Stories for this round: pick from the bank, or write a new one inline.
  5. Interviewers: tracked contacts linked to the round, with "Add interviewer" (pick an existing contact of the application or create one with name, title, email).
  6. Company brief: the Claude brief as plain text with its sources (no `{@html}`), its date, and **Ask Claude for a brief** / "Requested — the daily run picks it up" when pending.
  7. Claude prompts: copy buttons for *Company research*, *Likely questions for this round*, *Mock interview* (Claude asks one question at a time and gives feedback), *Tell me about yourself* (uses the outreach profile) and *Thank-you note*. Filled from the application and round; prompts include no private notes unless the prompt is about them (the mock interview includes the round's linked story titles).
  8. After the interview: Mark done, outcome, reflection, and per-interviewer **Draft thank-you** (opens Gmail compose with a short drafted note) and **Mark sent**.
- **Application panel:** a new "Interviews" section above Contacts: rounds with date and state, **Add round**, and **Move to Interview** when relevant. The form's interview field becomes a read-only "Next interview".
- **Dashboard:** a new **Upcoming interviews** widget (next 14 days, plus any thank-you due), added through the existing layout reconciliation so saved layouts keep working.
- Everything fits at 390 px (Phase 3 rule).

## 6. Security and privacy

- All new routes use cookie auth; the Claude token reaches only `/api/claude/*`, and the new `POST /api/claude/briefs` writes only `prep_briefs` and the queue item.
- The routine sees only company, role and job link for a brief request.
- Brief text and sources are untrusted: length caps, http(s)-only URLs, rendered as text.
- Calendar export is a download from the logged-in session; there is no public calendar feed.

## 7. Testing

- Backend: service tests (derived `interview_datetime`, thank-you-due window, contact linking rules, default checklist, caps), route tests including the auth boundary, `.ics` escaping and line folding, migration upgrade/downgrade with the data migration on real Postgres, Claude brief ingest (pending-only, caps, URL filtering), sheet-sync Interviews tab with the fake Sheets client.
- Frontend: Vitest for the Interview Prep page tabs, prep page sections, prompt builders (exact filled text), thank-you compose URL, the Dashboard widget, the panel section and the read-only form field; svelte-check and build clean; phone-width check of the two new pages.
- Nothing contacts Google, Anthropic or any other external service.

## 8. Out of scope
- Automatic detection of interview invitations from email (that is Gmail sync, Phase 6, which builds on these rounds).
- Calendar sync with Google Calendar (would need a new permission); the `.ics` download covers adding it once.
- In-app Claude chat or mock interviews inside the app.
- Recording or transcribing interviews.
