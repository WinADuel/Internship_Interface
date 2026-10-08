# Phase 2 Report: Job Discovery

| | |
|---|---|
| **Status** | Complete on branch `phase-2-discovery`. Waiting for the owner to read this report and merge the PR. Nothing has been merged to `main`. |
| **Built** | 2026-10-08, one cloud session (design approved by the owner the same day) |
| **Branch** | `phase-2-discovery`, cut from `main` at `bbc05c3` |
| **Spec** | [`docs/superpowers/specs/2026-10-08-job-discovery-design.md`](../superpowers/specs/2026-10-08-job-discovery-design.md) |
| **Plan** | [`docs/superpowers/plans/2026-10-08-job-discovery-phase2.md`](../superpowers/plans/2026-10-08-job-discovery-phase2.md) (15 tasks) |
| **Detailed log** | [`phase-2-progress.md`](phase-2-progress.md): one entry per task, with every finding and ruling |
| **Tests at finish** | Backend 1171 passing against real PostgreSQL 16 (baseline 356) · Frontend 389 passing (baseline 232) · `svelte-check` 0 errors / 0 warnings · production build clean · Alembic `upgrade` → `downgrade -1` → `upgrade` succeeds and `alembic check` reports no drift · `docker compose config` parses |

---

## 1. What Phase 2 delivers

The app now finds internship postings by itself.

- **Discover page** (new sidebar link, with a count of new matches).
  - **Inbox:** postings that match your filters, newest first. **Save**, **Dismiss**, **Open**, and **Dismiss all shown**.
  - **Saved:** your shortlist. **Apply** adds the posting to your tracker as Applied today (company, role, location and link filled in), which also auto-queues company contacts exactly as in Phase 1b. A **closed** badge appears if the source later takes the posting down.
  - **Dismissed:** the most recent 200, each with **Restore**.
  - **Watchlist:** paste a company's careers page to watch it directly.
  - **Paste a posting link:** any posting URL, with an editable preview, saved straight to Saved.
  - A header with the last scan time, **Scan now**, and any per-source errors.
- **Sources.**
  - The SimplifyJobs and vanshb03 Summer 2027 GitHub lists (about 4,900 active postings between them on 2026-10-08, after de-duplication). The list URLs are a setting, so next year is a settings change.
  - Watchlist companies on **Greenhouse, Lever, Ashby and Workday** (Workday covers NVIDIA, Intel, Salesforce, Adobe and many others).
  - Google, Microsoft, Apple, Meta and Amazon run their own career sites, so they come in through the lists, or by pasting a link.
- **Scanning.** A new `job-scan` Compose service scans every 6 hours (1–48, configurable), starting about a minute after it boots. Unchanged lists cost almost nothing (ETag). The same role on several sources shows up once.
- **Filters** (Settings → Job discovery): seasons, categories, include/exclude keywords, watchlist keywords, locations, and "hide roles that don't sponsor". A live "N postings match" count updates as you edit. Filters apply when the Inbox is shown, so changing one re-filters everything already found.
- **Dashboard:** a **New postings** widget with the count and the five newest matches.
- **Backup sheet:** a fourth **Saved postings** tab. Existing three-tab sheets gain it automatically on their next sync.
- **No new Google permissions, secrets or paid APIs.**

## 2. Architecture additions

- **Backend package `app/services/discovery/`**, one job per file:
  - `urls.py` — URL normalization (for de-duplication), board and job link recognition, canonical careers URLs.
  - `http.py` — the only network code. Every request resolves the host, refuses non-public addresses, connects to the checked address (Host header and TLS SNI keep the real name, so certificates are still verified), re-checks every redirect, caps bytes, and enforces one deadline over the whole request.
  - `parsers.py` — pure functions turning list JSON, the four board APIs, and pasted HTML (`JobPosting` structured data, then the page title) into capped, cleaned records.
  - `sources.py` — fetches one list, board or pasted link through the `DiscoveryHttp` protocol.
  - `ingest.py` — upserts, cross-source de-duplication, closing, housekeeping.
  - `filters.py` — the Inbox query, built in SQL from the settings.
  - `scanner.py` — the single-flight scan (Postgres advisory lock on a dedicated connection).
  - `actions.py`, `watchlist.py`, `labels.py` — save/dismiss/restore/apply/paste and the watchlist.
- **Routes** `app/api/discovery.py`: 14 cookie-authenticated routes under `/api/discovery`. The Claude token is rejected on all of them, and a test fails if a new route is added without that check.
- **Data**: migration `0005_job_discovery` adds `postings`, `watch_companies` and the `discovery_*` settings columns.
- **Frontend**: `routes/Discover.svelte`, components under `lib/components/discovery/`, a shared `ChipInput`, `DiscoverySettings`, the `NewPostings` widget, `lib/api/discovery.ts`, and a small status store for the sidebar badge.

## 3. How it was built

The owner chose the feature set and the main behaviours on decision cards (sources: both lists and a watchlist; paste-a-link; filters now, Claude ranking later; a separate Saved list), then approved the written design. The 15-task plan was executed task by task: a fresh agent implemented each task test-first; the lead read each report and diff, logged rulings, and pushed reviewed work. Security-sensitive Task 2 got a separate reviewer. At the end, two reviewers covered the whole branch (backend and frontend) and their findings were fixed in one round.

### Task log

| Task | Commit(s) | Outcome |
|---|---|---|
| 0. Spec, plan, progress log | `c490ce2` | |
| 1. Models, settings, migration 0005 | `1c2b56f` | Clean |
| 2. URLs, board recognition, guarded fetcher | `93307d4`, fixes in `eebbcd0` | Reviewer: guard sound; one Important (deadline not enforced while headers arrive) fixed with minors |
| 3. Parsers and fixtures | `eebbcd0` | Clean. The commit also holds Task 2's fixes (two agents shared the git index; content verified, history left intact) |
| 4. Fetchers | `161833e` | Clean |
| 5. Ingest | `52806a8`, `2ad092e` | Lead found one Important (old still-listed postings deleted, so dismissed ones returned) — fixed |
| 6. Filters | `7300331` | Clean |
| 7. Scanner and `job-scan` | `9519757` | Clean |
| 8. Actions, paste, watchlist | `daa0c4b` | Clean (includes a real two-session double-apply race test) |
| 9. API routes | `b54c9c0` | Clean |
| 10. Saved postings sheet tab | `f3c862a` | Clean |
| 11. Frontend data layer | `ed9342f` | Clean |
| 12. Discover page | `04689c3` | Clean |
| 13. Watchlist tab and settings | `ced4c46` | Clean |
| 14. Dashboard widget | `f6da2b7` | Clean |
| 15. End-to-end flow test, docs | `b0f0762` | The flow test found no bugs in earlier tasks |
| Whole-branch fixes | `3135d07` (frontend), `b39a844` (backend) | See §5 |

## 4. Quality & security

- **No test touches the internet.** All HTTP goes through a fake; the only real sockets are three loopback-only tests proving the request deadline.
- **Untrusted content** (lists anyone can contribute to, job boards, pasted pages): every field is length-capped and cleaned of control characters and lone surrogates; URLs must be http/https; the UI renders everything as plain text and only links to http/https URLs, opened with `rel="noopener noreferrer"`.
- **Server-side request forgery:** a reviewer tried numeric, octal, hex and IPv6 forms of local addresses, `user@host` tricks, mixed DNS answers and redirects to private addresses; all were refused before any request. A local TLS experiment confirmed the pinned-address connection still verifies certificates against the real hostname.
- **Real-data check:** the reviewer ran a full scan of the real Simplify (13 MB) and vanshb03 lists through the real HTTP client on a simulated network: 4,941 postings stored in 3.7 s with about 155 MB peak memory; an unchanged list scanned in 0.02 s.
- **Concurrency:** one scan at a time (advisory lock); Apply is safe against double clicks and simultaneous requests (row lock, one transaction).

## 5. Final whole-branch review

No Critical findings. Three Important, all fixed:

1. **A dismissed posting could come back from the other list.** If both lists carried a role and Simplify closed it, housekeeping deleted the stored copy and the vanshb03 copy arrived as new. About 40 roles are in that position in today's data. Now closed rows stay (as de-duplication markers) until no scan has seen them for 90 days.
2. **One malformed character could fail a whole source on every scan.** A lone UTF-16 surrogate in any list row made PostgreSQL reject the batch. Surrogates are now cleaned from text and rejected in URLs and keys.
3. **Paste-a-link split "San Francisco, CA" into two locations.** Locations are now edited as separate entries.

Minor fixes in the same round: out-of-range dates no longer crash a paste preview; every outbound request (not only pasted pages) gets the address check; scan status no longer touches the scan lock; an unchanged list refreshes its postings' last-seen time; removing a watched company clears its new postings; `job-scan` waits for a healthy database and retries 10 minutes after a crash; Workday searches skip redundant keywords and pause between pages; the list and badge refresh reliably; Dismiss all works past 500; typed-but-not-added filter text is no longer lost on Save; README wording.

## 6. Decisions and trade-offs

Every ruling is in [`phase-2-progress.md`](phase-2-progress.md). The ones the owner is most likely to notice:

- **Saved is a separate list**, not the tracker's Wishlist column (owner's choice). Apply is the step that adds to the tracker.
- **Housekeeping** deletes new or dismissed postings only when no scan has seen them for 90 days. Saved and applied postings are never deleted.
- **vanshb03 seasons have no year** ("Summer"). A filter of "Summer 2027" matches them; "Summer 2026" postings do not match.
- **List postings without a category pass the category filter** (vanshb03 has none), so a few hardware roles from that list can appear.
- **The "intern" keyword check applies only to watchlist boards.** List postings are already internships, so a list role titled just "Software Engineer" can appear under the defaults.
- **Workday postings are never marked closed by a scan**; they drop out after 90 days unseen.
- **`gh_jid` is kept in URLs on companies' own domains** (where it is the only job id), so 54 Waymo roles stay distinct.
- **Claude ranking** is designed (two reserved columns, Inbox sorts by score when present) but its endpoints wait for the server deploy.

## 7. Known limitations

- **Not verified against the live job boards.** The sandbox could not reach Greenhouse, Lever, Ashby or Workday, so those parsers were tested on responses written from vendor documentation (marked in `backend/tests/fixtures/discovery/README.md`). Workday's search and single-job endpoints are undocumented and could change; if they do, only Workday companies' scans fail, with the error shown on the Watchlist tab. The GitHub lists were tested on real data.
- **The `job-scan` Docker service has not run on a real machine yet**; `docker compose config` parses.
- **"Load more" can skip a posting** if a background scan closes shown postings between pages (accepted; switching tabs reloads).
- **The dashboard widget loads once per visit** and does not follow live scans.
- **Apply's toast is text only** (the toast component has no link support).
- **Untrusted company names reach the contacts research queue** when you Apply (capped, one line). Fine today; worth noting when the Claude endpoints are built.
- **Out of scope by design:** LinkedIn, Handshake, Indeed and other login-only sites; auto-applying; notifications outside the app; new-grad lists (just another list URL in settings later).

## 8. What's next — what the owner must do

**To merge.** Read this report, then merge the PR from `phase-2-discovery` into `main`.

**To run it on your PC** (from the repo folder):

1. `git pull origin main`, then `docker compose up -d --build`. Migration `0005` runs automatically, and the new `job-scan` service starts and runs its first scan about a minute later.
2. Open **Discover**. Postings appear after the first scan (or press **Scan now**).
3. In **Settings → Job discovery**, adjust seasons, categories, keywords and locations. The live count shows how many postings match before you save.
4. On the **Watchlist** tab, paste careers pages of companies you care about that use Greenhouse, Lever, Ashby or Workday. The first scan after adding one is the live check for that board type; if one shows an error, send it to Claude.

**Later:** the server deploy (which also unlocks the daily Claude job, Google app publishing, and Claude ranking of the Inbox), then interview prep or Gmail sync.
