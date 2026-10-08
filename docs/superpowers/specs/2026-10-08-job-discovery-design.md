# Phase 2: Job Discovery — Design

**Status:** draft for Daniel's approval (2026-10-08)
**Builds on:** the Phase 1 tracker and Phase 1b outreach (`docs/superpowers/specs/2026-10-05-internship-tracker-design.md`, §12 lists this as a future phase).

## 1. What it does

A new **Discover** page finds internship postings for you, so you stop checking lists and career pages by hand.

- The app scans the big GitHub internship lists and a watchlist of company career pages every 6 hours (and whenever you press **Scan now**).
- Postings that match your filters land in an **Inbox**. You **Save** the ones you like or **Dismiss** the rest.
- Saved postings sit in their own **Saved** list. When you actually apply, press **Apply**: it becomes an Applied application in your tracker with the company, role, location and link filled in. Your existing outreach flow then auto-queues company contacts, as it does today.
- You can also **paste any posting link**. It goes straight to Saved with the details filled in.

### Success criteria
- A new matching posting on either source shows up in the Inbox within 6 hours, or immediately after Scan now.
- The same role listed on two sources shows up once.
- Saving, applying and pasting each take one click (plus a confirm on Apply).
- Everything runs on your PC; nothing here needs the server or any new Google permission.

## 2. Where postings come from

### 2a. Community lists (GitHub)
These repos publish a machine-readable `listings.json` alongside their README. Checked 2026-10-08:

| List | URL | Size |
|---|---|---|
| SimplifyJobs Summer 2027 | `https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json` | ~17,000 rows, 13 MB |
| vanshb03 Summer 2027 | `https://raw.githubusercontent.com/vanshb03/Summer2027-Internships/dev/.github/scripts/listings.json` | ~470 rows |

Each row has `id`, `company_name`, `title`, `locations[]`, `url`, `active`, `is_visible`, `date_posted` (Unix time), `terms[]` (e.g. "Summer 2027"; vanshb03 calls it `season`), `category` (Simplify: Software, AI/ML/Data, Hardware, Product, Quant) and `sponsorship`.

- The list URLs are a setting, so next year you swap `2027` for `2028` without a code change.
- Downloads use `ETag`/`If-None-Match`, so an unchanged list costs almost nothing. Downloads are capped at 50 MB.
- Rows with `active=false` or `is_visible=false` are skipped. A posting we already have that turns inactive is marked **closed**.

### 2b. Company watchlist
You add a company by pasting its careers page URL. The app recognizes the four job-board systems most tech companies use and reads the same public job data their own career pages load (no login):

| System | Recognized URL | API read |
|---|---|---|
| Greenhouse | `boards.greenhouse.io/<token>` or `job-boards.greenhouse.io/<token>` | `https://boards-api.greenhouse.io/v1/boards/<token>/jobs` |
| Lever | `jobs.lever.co/<token>` | `https://api.lever.co/v0/postings/<token>?mode=json` |
| Ashby | `jobs.ashbyhq.com/<token>` | `https://api.ashbyhq.com/posting-api/job-board/<token>` |
| Workday | `<tenant>.wd<N>.myworkdayjobs.com/<site>` (e.g. NVIDIA, Intel, Salesforce, Adobe) | `POST https://<tenant>.wd<N>.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs`, searching each watchlist keyword |

Greenhouse, Lever and Ashby publish their APIs officially. Workday's is the undocumented endpoint its own career pages call, so it could change without notice; if it breaks, only Workday companies' scans fail (shown on the Watchlist tab) and everything else keeps working.

A Workday search matches substrings, so a keyword another keyword already covers ("internship" next to "intern") is dropped before searching — the shorter one returns everything the longer one would. Workday is also the only board read with several requests, so there is a 0.5 s pause between its pages, on top of the pause between companies (§5).

Companies with their own custom career sites (Google, Microsoft, Apple, Meta, Amazon) can't be watched. They are covered by the community lists instead, which track them closely (Simplify had 15 active Summer 2027 Google roles and 10 Amazon roles on 2026-10-08), and you can paste any of their postings (2c). The app explains this when you try to add one.

Watchlist boards list every job, not just internships. So by default only titles containing *intern*, *internship* or *co-op* count as matches (a filter you can change, §4). A watched job that disappears from its board is marked **closed**.

The API response shapes above come from each vendor's public documentation. My cloud sandbox can't reach those hosts, so tests use recorded sample responses, and the first real scan on your PC is the live check.

### 2c. Pasted links
Paste a posting URL on the Discover page:
1. **Greenhouse / Lever / Ashby / Workday link:** the app reads that single job from the API above, which gives an exact company, title and location.
2. **Any other site:** the app downloads the page once and reads its `JobPosting` structured data, which many career sites (including Workday) embed for Google Jobs. If that's missing, it falls back to the page title.
3. You see a preview and can edit any field before it's saved.

Pasted postings skip the filters and go straight to **Saved**. Because the server fetches a URL you typed, the fetcher accepts only `http`/`https`, refuses private and local addresses (including after redirects), and is capped at 2 MB and 10 seconds.

## 3. Data model (migration `0005_job_discovery`)

### `postings`
| Column | Notes |
|---|---|
| `id` | |
| `source` | `simplify`, `vanshb03` (the list's short name), `greenhouse`, `lever`, `ashby`, `workday`, `pasted` |
| `source_key` | the source's own id; unique together with `source` |
| `company`, `title` | text, length-capped |
| `locations` | text array |
| `url` | the apply link (`http`/`https` only) |
| `url_key` | normalized URL (lowercased host, tracking params like `utm_*` stripped), used for de-duplication |
| `terms` | text array, e.g. `{"Summer 2027"}`; empty for watchlist/pasted |
| `category` | from the list, nullable |
| `sponsorship` | from the list, nullable |
| `date_posted` | nullable |
| `first_seen_at`, `last_seen_at` | |
| `closed` | bool: the source marked it inactive or it vanished from a watched board |
| `state` | `new`, `saved`, `dismissed`, `applied` |
| `application_id` | FK → `applications`, `ON DELETE SET NULL`; set by Apply |
| `watch_company_id` | FK → `watch_companies`, nullable |
| `claude_score`, `claude_note` | nullable, reserved for Claude ranking (§6) |

**De-duplication.** A new posting is skipped if its `url_key` matches an existing row, or if the same company and title (case-insensitive) arrived from another source in the last 14 days. So the same role on Simplify, vanshb03 and a Greenhouse board appears once.

**Housekeeping.** Postings that are `new` or `dismissed` and not seen by any scan for 90 days (`last_seen_at`) are deleted by the scan. Being closed is never enough: a row whose source still lists it (a list's inactive rows count as seen, as do the postings of a list that answered 304) keeps its place as a de-duplication tombstone, so neither a dismissed posting nor the same role from another list can come back to the Inbox as new. A closed posting stops being seen once its source drops it, and is deleted 90 days later. Saved and applied postings are never deleted automatically.

### `watch_companies`
`id`, `name`, `ats` (`greenhouse`/`lever`/`ashby`/`workday`), `board_token` (unique with `ats`; for Workday, `<host>/<tenant>/<site>`), `careers_url`, `added_at`, `last_checked_at`, `last_error` (one line, never a response body).

### `app_settings` additions
| Column | Default |
|---|---|
| `discovery_list_urls` | the two URLs in §2a |
| `discovery_terms` | `{"Summer 2027"}` |
| `discovery_categories` | `{"Software", "AI/ML/Data"}` |
| `discovery_include_keywords` | `{}` (list rows already are internships) |
| `discovery_watchlist_keywords` | `{"intern", "internship", "co-op"}` |
| `discovery_exclude_keywords` | `{"senior", "staff", "principal", "phd"}` |
| `discovery_locations` | `{}` (anywhere) |
| `discovery_hide_no_sponsorship` | `false` |
| `discovery_scan_hours` | `6` |
| `last_scan_at`, `last_scan_error` | |

## 4. Filters

Filters decide what reaches the Inbox. They are applied **when the Inbox is shown, not when postings are stored**, so changing a filter immediately re-sorts what you see, including postings already scanned.

A posting is in the Inbox when it is `new`, not closed, and:
- **Term:** for list postings, one of its `terms` is in your terms. Watchlist postings have no term, so this check is skipped for them.
- **Category:** for list postings, its category is in your categories (empty = any).
- **Keywords:** the title contains a whole word from your include keywords (empty = any). For watchlist postings, it must also contain one of the watchlist keywords.
- **Exclude:** the title contains none of your exclude keywords.
- **Location:** any of its locations contains any of your locations, ignoring case (empty = anywhere; "Remote" works as a location).
- **Sponsorship:** if *hide no-sponsorship* is on, list postings marked "Does Not Offer Sponsorship" or "U.S. Citizenship is Required" are hidden. Most rows say "Other" (about 99% of Simplify's, checked 2026-10-08), so this only catches the ones the list marks explicitly.

All filters are edited in **Settings → Job discovery**, with a live "N postings match" count as you change them.

## 5. Scanning

A new Docker Compose service, `job-scan`, works like the existing `sheet-sync`: it runs `python -m app.jobs.job_scan`, which loops forever, scanning every `discovery_scan_hours`. **Scan now** on the Discover page triggers a scan through the API.

Each scan:
1. Takes a Postgres advisory lock, so two scans never run at once (a second Scan now just reports "already scanning").
2. Downloads each list (conditional GET) and upserts its active rows; a `304` ingests nothing but still marks that list's postings seen (§3).
3. Reads each watched board in turn, with a 10-second timeout and a short pause between companies.
4. Marks closed postings and runs housekeeping (§3).
5. Records `last_scan_at`, plus a short per-source error summary in `last_scan_error`. One broken source never stops the others.

All outbound requests go to the fixed list and board hosts (pasted links aside, §2c), send a plain `User-Agent` naming the app, and never send cookies or credentials. Every request — list, board API or pasted page — is resolved, address-checked and pinned on every redirect hop (§9), since list URLs are user-configured and a board API can redirect.

## 6. Claude ranking (designed now, switched on later)

When the server exists, the daily Claude job can also rank Inbox matches against your outreach profile and write a 0–100 `claude_score` with a one-line `claude_note` ("Strong fit: ML infra, Python, matches your research interest in …").

This phase only adds the two nullable columns and sorts the Inbox by score when one exists. The Claude endpoints (`GET /api/claude/postings`, `POST /api/claude/postings/scores`) and the routine instructions are built together with the server deploy, so they can be tested end to end against the real routine. Until then the Inbox sorts newest first.

## 7. UI

**Sidebar:** a new **Discover** link with a badge counting Inbox postings.

**Discover page** (tabs):
- **Inbox:** matching postings, newest first. Each row shows company, title, locations, how long ago it was posted, a source badge, and a sponsorship note when the list has one. Buttons: **Save**, **Dismiss**, **Open** (new tab). **Dismiss all shown** clears a batch after a confirm. Header: last scan time, **Scan now**, and any scan errors.
- **Saved:** your saved postings, with a **closed** badge on any the source has since closed. Buttons: **Apply** (confirm: "Add to your tracker as Applied today?"), **Remove** (moves it to Dismissed), **Open**.
- **Dismissed:** the most recent 200, each with **Restore**, so a mis-click is never permanent.
- **Watchlist:** add a company by pasting its careers URL; each company shows its system, last checked time, open matches, and any error; **Remove** (which also drops that company's still-new postings from the Inbox, since no scan lists them any more; saved, applied and dismissed ones stay).
- A **Paste a posting link** box above the tabs, with an editable preview before saving (§2c).

**Apply** creates an application with status Applied, `date_applied` = today, company, role, first location, `job_link` = the posting URL, and `source` = "Discover: Simplify" (or the board/pasted). It goes through the existing `create_application`, so Phase 1b's company-contact auto-queue runs unchanged. The posting moves to `applied` and links to the application.

**Dashboard:** a **New postings** widget showing the Inbox count and the five newest matches, linking to Discover.

**Backup sheet:** a fourth tab, **Saved postings** (company, role, locations, link, saved date, closed). Inbox and dismissed postings are not backed up, since the next scan recreates them.

## 8. API (all session-authenticated, like the rest of the app)

- `GET /api/discovery/postings?view=inbox|saved|dismissed&limit&offset` → postings plus a total count
- `POST /api/discovery/postings/{id}/save` · `/dismiss` · `/restore` · `/apply`
- `POST /api/discovery/postings/dismiss-all` (body: the ids currently shown)
- `POST /api/discovery/paste/preview` (URL in, editable fields out; saves nothing) and `POST /api/discovery/paste` (the confirmed fields)
- `GET/POST/DELETE /api/discovery/watchlist`
- `POST /api/discovery/scan` → starts a scan, or reports one already running; `GET /api/discovery/status`
- `GET/PUT /api/settings` gains the discovery fields, plus `GET /api/discovery/match-count` for the live count

The Claude token is rejected on all of these.

## 9. Security

- No new Google scopes and no new secrets.
- Everything from lists, boards and pasted pages is untrusted: Pydantic caps every field's length, URLs must be `http`/`https`, and the frontend renders it as plain text only (never `{@html}`).
- Every outbound request guards against server-side request forgery as described in §2c: each hop's host is resolved, every address it answers must be public, and the request is sent to a checked address. This covers pasted pages, the user-configured list URLs and the board APIs alike.
- Lone UTF-16 surrogates (`\ud800`–`\udfff`), which a source can put in any string and which Postgres cannot store, are treated as control characters in cleaned text and make a URL or source key unusable.
- Board tokens are validated as `[A-Za-z0-9_-]{1,100}` before they go into an API URL, and a Workday host must match `<tenant>.wd<N>.myworkdayjobs.com` exactly.

## 10. Testing

- No test touches the network (repo rule). Each source has recorded sample responses in `backend/tests/fixtures/discovery/`, served through a fake HTTP client.
- Backend: the parser for each format; URL normalization and de-duplication; each filter rule and their combination; closed marking and housekeeping; the advisory lock; Apply creating an Applied application and auto-queuing contacts; the SSRF guard (private IPs, redirects, size cap); the migration down/up cycle.
- Frontend: Inbox/Saved/Dismissed actions with undo paths, the paste preview, the watchlist add errors, the settings live count, and the dashboard widget.

## 11. Out of scope

- LinkedIn, Handshake, Indeed and other sites that need a login or forbid scraping.
- Auto-applying, or filling in application forms.
- Notifications outside the app (email, push).
- New-grad lists (easy to add later: they use the same `listings.json` format, so it's just another URL in settings).
- Claude ranking endpoints and routine, built with the server deploy (§6).

## 12. Workflow

Per §11b of the main spec: built on its own branch (`phase-2-discovery`), one reviewed and pushed commit series per task, a final whole-branch review, then `docs/phases/phase-2-report.md`. This spec is committed as `docs/superpowers/specs/2026-10-08-job-discovery-design.md`, and the stale "awaiting merge" row for Phase 1b in `docs/phases/README.md` is fixed on the same branch.
