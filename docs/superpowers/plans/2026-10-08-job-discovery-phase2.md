# Job Discovery (Phase 2) Implementation Plan

> **For agentic workers:** execute task by task, in order. Steps use checkbox (`- [ ]`) syntax. Each task: TDD (failing test first), implement, run the task's tests and then the affected full suite, commit, get a fresh review of the task's diff, fix Critical/Important findings, push, log progress.

**Goal:** A Discover page that finds internship postings automatically (GitHub community lists + a company watchlist on Greenhouse/Lever/Ashby/Workday), filters them into an Inbox, keeps a separate Saved list, turns a saved posting into an Applied application in one click, and accepts pasted posting links.

**Architecture:** Same layering as Phases 1/1b (thin routers → services → models). Network access sits behind one small `DiscoveryHttp` protocol so every test uses a fake (no test touches the network). Parsing is pure functions over recorded fixtures. A `job-scan` Compose service loops like `sheet-sync`; `POST /api/discovery/scan` runs the same scan as a background task; a Postgres advisory lock keeps scans single-flight. Filters are applied at query time, so changing a filter re-sorts existing postings immediately.

**Tech stack:** unchanged (FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL 16, httpx, pytest; Svelte 5 + TS, Vitest). No new Python or npm dependencies: HTML `JobPosting` extraction uses the standard library `html.parser`.

**Spec:** `docs/superpowers/specs/2026-10-08-job-discovery-design.md` (binding). Main spec §11b (workflow) still applies.

## As-built facts this plan relies on (from Phases 1 and 1b)

- Latest migration is `0004_outreach_contacts`; this plan's is `0005_job_discovery`.
- Model enums use `enum_column(EnumCls, "pg_type_name")` from `app/models/application.py` (stores lowercase values).
- `AppSettings` is a single row (`id = 1`, CHECK constraint). `settings_service.get_settings(db)` creates it on first use; `update_settings(db, SettingsUpdate)` applies `exclude_unset` fields. `SettingsUpdate` rejects explicit nulls.
- Services call `db.commit()` themselves; the test session uses SAVEPOINTs, so commits inside tests are safe.
- The test harness builds tables with `Base.metadata.create_all`, not migrations. Exercise migrations by hand: `alembic upgrade head`, `alembic downgrade -1`, `alembic upgrade head`, then `alembic check`. After changing models, run `alembic upgrade head` against the test DB too.
- `backend/pytest.ini` sets `filterwarnings = error`. Use `datetime.now(UTC)`; dates come from `nudges.utc_today()`.
- `application_service.create_application(db, ApplicationCreate)` writes the initial `status_history` row and, when created with status `applied`, enqueues one `company_contacts` research item. Apply must go through it.
- Sheet sync: `sheet_sync_service` has `TAB_*` constants and `ALL_TABS`; routers schedule syncs via `Depends(get_sheet_sync_scheduler)` → `sync.schedule(background_tasks, tabs)`. Tests use the `sheet_sync_recorder` fixture. `GoogleSheetsClient.replace_tab` fails on a tab that does not exist, and sheets created before this phase have only three tabs.
- Cookie routes use `Depends(get_current_user)`; tests use the `logged_in_client` fixture. `test_claude_auth_boundary.py` checks that a Claude token is rejected on cookie routes; extend it for the new routes.
- Frontend: hash routes (`/#/discover`) in `App.svelte`; `NavSidebar.svelte` links; `apiFetch` in `lib/api/client.ts` (session refresh, 422 formatting); snake↔camel mapping helpers in `lib/api/case.ts`; dashboard widgets are registered in `lib/dashboard/layout.ts` (`defaultLayout`; `reconcileLayout` appends new defaults) and rendered by `routes/Dashboard.svelte`'s widget snippet. Never use `{@html}`.
- The cloud sandbox cannot reach the Greenhouse, Lever, Ashby or Workday hosts; `raw.githubusercontent.com` works. Board fixtures are written from each vendor's documented response shape; list fixtures are trimmed copies of real `listings.json` rows.

## Global constraints

- No test contacts the network. All HTTP goes through `DiscoveryHttp`; tests pass `FakeDiscoveryHttp`.
- Everything from lists, boards and pasted pages is untrusted: Pydantic/parser caps every field (company/title 300 chars, each location 200, at most 20 locations, URL 2000), URLs must be `http`/`https` or the row is dropped, and the frontend renders it as plain text.
- Outbound requests send `User-Agent: InternshipTracker/1.0 (personal job tracker)`, no cookies, no credentials, 10 s timeout (list downloads 30 s), list downloads capped at 50 MB, pasted pages at 2 MB.
- Pasted-URL fetches are SSRF-guarded (§2c of the spec): `http`/`https` only; the host must resolve only to public addresses (reject private, loopback, link-local, multicast, reserved, unspecified, and IPv6 equivalents); redirects followed manually, at most 5, each hop re-checked.
- Board tokens match `^[A-Za-z0-9_-]{1,100}$`; Workday hosts match `^[a-z0-9-]+\.wd\d{1,3}\.myworkdayjobs\.com$`.
- No new Google scopes; no new secrets; no Claude endpoints in this phase (spec §6).
- Workflow: branch `phase-2-discovery`; after each task's review, push with `git push origin phase-2-discovery` after a secret check; never touch `main`; never rewrite history. Log each task in `docs/phases/phase-2-progress.md`. Commit messages end with `Co-Authored-By: Claude <noreply@anthropic.com>`.

## Review focus

- A pasted URL pointing at `localhost`, `10.x`, `169.254.169.254`, or a public URL that redirects to one. Expected: refused before any request reaches it. Pinned to Task 2.
- A list row with a `javascript:` URL or a 50 KB title. Expected: dropped or truncated server-side; inert client-side. Pinned to Tasks 3 and 12.
- The same role from Simplify, vanshb03 and a Greenhouse board. Expected: one posting. Pinned to Task 5.
- Two scans at once (Scan now during the scheduled scan). Expected: the second reports "already scanning" and writes nothing. Pinned to Task 7.
- One source down (timeout, 500, malformed JSON). Expected: the others still ingest; the error is recorded per source; nothing is marked closed for the failed source. Pinned to Tasks 5 and 7.
- Apply twice on the same posting. Expected: one application, one `company_contacts` queue item. Pinned to Task 8.

---

## Task 1: Discovery data models, settings fields, migration

**Files:** create `backend/app/models/posting.py`, `backend/app/models/watch_company.py`; modify `backend/app/models/__init__.py`, `backend/app/models/app_settings.py`, `backend/app/schemas/settings.py`; create `backend/alembic/versions/0005_job_discovery.py`; test `backend/tests/models/test_discovery_models.py`, extend `backend/tests/services/test_settings_service.py` and `backend/tests/api/test_settings_routes.py`.

**Produces:**
- `posting.py`: `PostingSource(str, Enum)` = `SIMPLIFY="simplify"`, `VANSHB03="vanshb03"`, `LIST="list"` (any other list URL), `GREENHOUSE`, `LEVER`, `ASHBY`, `WORKDAY`, `PASTED` (lowercase values). `PostingState(str, Enum)` = `NEW`, `SAVED`, `DISMISSED`, `APPLIED`. `Posting` with the spec §3 columns: `id`, `source`, `source_key` (Text), `company`, `title`, `locations` (`ARRAY(Text)`, default `[]`), `url`, `url_key`, `terms` (`ARRAY(Text)`, default `[]`), `category` nullable, `sponsorship` nullable, `date_posted` (timestamptz, nullable), `first_seen_at`/`last_seen_at` (timestamptz, server default now), `closed` (bool, default false), `state` (default `NEW`), `state_changed_at` (timestamptz, server default now — needed for "most recent 200 dismissed"), `application_id` FK → `applications.id` `ondelete="SET NULL"`, `watch_company_id` FK → `watch_companies.id` `ondelete="SET NULL"`, `claude_score` (int, nullable), `claude_note` (Text, nullable). Unique constraint `(source, source_key)`. Indexes on `url_key`, `state`, `(lower(company), lower(title))` (functional index in the migration; a plain composite on `company, title` is acceptable if autogenerate fights it — record a ruling).
- `watch_company.py`: `WatchAts(str, Enum)` = `GREENHOUSE`, `LEVER`, `ASHBY`, `WORKDAY`. `WatchCompany`: `id`, `name`, `ats`, `board_token` (Text; for Workday `"<host>/<tenant>/<site>"`), `careers_url`, `added_at` (server default now), `last_checked_at` nullable, `last_error` nullable. Unique `(ats, board_token)`.
- `AppSettings` additions with the spec §3 defaults (both Python `default=` and `server_default=`): `discovery_list_urls` (`ARRAY(Text)`, the two URLs), `discovery_terms` (`{"Summer 2027"}`), `discovery_categories` (`{"Software","AI/ML/Data"}`), `discovery_include_keywords` (`{}`), `discovery_watchlist_keywords` (`{"intern","internship","co-op"}`), `discovery_exclude_keywords` (`{"senior","staff","principal","phd"}`), `discovery_locations` (`{}`), `discovery_hide_no_sponsorship` (bool false), `discovery_scan_hours` (int 6), `discovery_list_etags` (JSONB `{}` — map of list URL → ETag), `last_scan_at` nullable, `last_scan_error` nullable (Text).
- `SettingsOut` gains every new field except `discovery_list_etags`. `SettingsUpdate` gains optional fields: list fields as `list[str]` with each item stripped, empty items removed, case-insensitively de-duplicated, item `max_length=100` (URLs 500), at most 30 items (URLs 10); each list URL must be `https://`; `discovery_scan_hours` `ge=1, le=48`; `discovery_hide_no_sponsorship` bool.

- [ ] Step 1: failing tests — model defaults (posting state `NEW`, `closed` false, empty arrays; settings defaults exactly as above), `(source, source_key)` uniqueness raises `IntegrityError`, application delete nulls `application_id`, watch company delete nulls `watch_company_id`; settings update normalizes lists (`[" Remote ", "remote", ""]` → `["Remote"]`), rejects an `http://` list URL and `discovery_scan_hours=0` with 422 through the route.
- [ ] Step 2: implement models and schemas; register models.
- [ ] Step 3: autogenerate `0005_job_discovery`, review it by hand (array server defaults as `'{}'::text[]` literals, JSONB `'{}'::jsonb`, enum types created and dropped in downgrade, FK `ondelete` rules), then upgrade/downgrade/upgrade and `alembic check` on the dev DB, and `alembic upgrade head` on the test DB.
- [ ] Step 4: full backend suite passes. Commit `feat(discovery): posting and watchlist models, discovery settings, migration 0005`.

## Task 2: URL tools — normalization, board recognition, safe fetch

**Files:** create `backend/app/services/discovery/__init__.py`, `backend/app/services/discovery/urls.py`, `backend/app/services/discovery/http.py`; test `backend/tests/services/discovery/test_urls.py`, `backend/tests/services/discovery/test_http.py` (add `__init__.py` files).

**Produces:**
- `urls.py`:
  - `normalize_url(url: str) -> str | None`: `None` unless `http`/`https` with a host; lowercases scheme and host, drops fragment, default ports, trailing `/` on the path, and query params whose lowercased name starts with `utm_` or is one of `gh_src`, `gh_jid` (keep `gh_jid` if it is the only identifier? — no: Greenhouse links carry the id in the path for `boards.greenhouse.io/<t>/jobs/<id>`; drop both), `source`, `ref`, `lever-source`, `lever-origin`; sorts remaining params. Used for `url_key`.
  - `safe_http_url(url) -> str | None`: returns the stripped URL if `http`/`https`, ≤2000 chars, has a host; else `None`.
  - `@dataclass(frozen=True) BoardRef(ats: WatchAts, token: str)`, `@dataclass(frozen=True) JobRef(ats: WatchAts, token: str, job_id: str)`.
  - `parse_board_url(url) -> BoardRef | None`: Greenhouse `boards.greenhouse.io/<t>`, `job-boards.greenhouse.io/<t>`, `boards.greenhouse.io/embed/job_board?for=<t>`; Lever `jobs.lever.co/<t>`; Ashby `jobs.ashbyhq.com/<t>`; Workday `https://<tenant>.wd<N>.myworkdayjobs.com/[<locale>/]<site>[/...]` → token `"<host>/<tenant>/<site>"` (locale segments like `en-US` skipped). Tokens validated per Global constraints.
  - `parse_job_url(url) -> JobRef | None`: Greenhouse `.../<t>/jobs/<id>` (digits); Lever `jobs.lever.co/<t>/<uuid>`; Ashby `jobs.ashbyhq.com/<t>/<uuid>`; Workday `.../<site>/job/<location-slug>/<title-slug>_<reqId>` → job id is the path after `<site>` (`job/...`), used with the Workday detail endpoint.
  - `KNOWN_CUSTOM_SITES: dict[str, str]` mapping host suffixes (`google.com`, `careers.google.com`, `microsoft.com`, `apple.com`, `metacareers.com`, `amazon.jobs`) to the company name, so the watchlist can explain that these are covered by the lists.
- `http.py`:
  - `class DiscoveryHttp(Protocol)`: `get_json(url, *, etag: str | None = None, max_bytes: int, timeout: float) -> FetchResult`, `post_json(url, body: dict, *, max_bytes, timeout) -> FetchResult`, `get_page(url, *, max_bytes, timeout) -> FetchResult` (SSRF-guarded).
  - `@dataclass FetchResult(status: int, data: Any | None, text: str | None, etag: str | None, final_url: str)`; `status == 304` means not modified.
  - `class DiscoveryFetchError(Exception)` with a one-line message: never the response body, never query strings (log host + path only).
  - `HttpxDiscoveryHttp` implementing it with httpx streaming and a running byte count (abort past `max_bytes` with `DiscoveryFetchError("too large")`). `get_page` resolves the host with `socket.getaddrinfo` and rejects any non-global address (`ipaddress.ip_address(...).is_global` false), connects without following redirects, and re-validates each `Location` (max 5 hops). Accept only `text/html` or `application/xhtml+xml` for pages.
  - `FakeDiscoveryHttp` in `backend/tests/services/discovery/fakes.py`: maps `(method, url)` → `FetchResult` or an exception, records calls.

- [ ] Step 1: failing tests — normalization table (tracking params removed, host lowercased, fragments dropped, `javascript:`/`ftp:`/relative → `None`); every recognized board and job URL form → expected refs; Workday with and without locale segment; a bad token (`../x`) → `None`; custom-site hosts recognized; SSRF guard: `get_page` on `http://127.0.0.1/`, `http://localhost/`, `http://10.0.0.5/`, `http://169.254.169.254/latest`, `http://[::1]/` raises before any connection (patch `getaddrinfo` and assert the transport was never called); a public host whose response redirects to `http://127.0.0.1` raises; >5 redirects raises; oversize body raises "too large". Use `httpx.MockTransport` for `HttpxDiscoveryHttp` tests — never a real socket.
- [ ] Step 2: implement. Step 3: tests pass, full backend suite passes. Commit `feat(discovery): URL normalization, board recognition and SSRF-guarded fetcher`.

## Task 3: Source parsers and fixtures

**Files:** create `backend/app/services/discovery/parsers.py`; fixtures under `backend/tests/fixtures/discovery/` (`simplify_listings.json`, `vanshb03_listings.json`, `greenhouse_board.json`, `greenhouse_job.json`, `lever_board.json`, `lever_job.json`, `ashby_board.json`, `workday_jobs_page1.json`, `workday_jobs_page2.json`, `workday_job_detail.json`, `jobposting_page.html`, `title_only_page.html`); test `backend/tests/services/discovery/test_parsers.py`.

**Fixtures:** download the two real `listings.json` files once (URLs in spec §2a; `raw.githubusercontent.com` is reachable) and keep ~10 rows each covering: active and inactive, `is_visible` false, Summer 2027 and another term, Software and Hardware categories, each sponsorship value, multiple locations, a row with a `javascript:` URL injected by hand, a row with a 50 KB title injected by hand. Write the board fixtures from vendor docs: Greenhouse `{"jobs":[{"id":..,"title":..,"location":{"name":..},"absolute_url":..,"updated_at":..,"first_published":..}]}`; Lever `[{"id":..,"text":..,"categories":{"location":..,"allLocations":[..]},"hostedUrl":..,"createdAt":<ms>}]`; Ashby `{"jobs":[{"id":..,"title":..,"location":..,"secondaryLocations":[{"location":..}],"jobUrl":..,"publishedAt":..,"isListed":true}]}`; Workday search `{"total":N,"jobPostings":[{"title":..,"externalPath":"/job/...","locationsText":..,"postedOn":"Posted 3 Days Ago","bulletFields":["R12345"]}]}` and detail `{"jobPostingInfo":{"title":..,"location":..,"externalUrl":..,"startDate":"2026-10-01","jobReqId":..},"hiringOrganization":{"name":..}}`. Mark each board fixture's first line or a sibling `README.md` "shape from vendor docs; verify against a live response on first real scan".

**Produces:** `@dataclass PostingIn(source, source_key, company, title, locations: list[str], url, terms: list[str], category, sponsorship, date_posted: datetime | None, active: bool)`; all string fields capped per Global constraints; rows without a safe URL, title or company are dropped.
- `parse_listings(data, source: PostingSource) -> list[PostingIn]` — handles both `terms` and `season` (vanshb03, a string → one-item list); `active = row.active and row.is_visible`; `date_posted` from Unix seconds; non-list input → `[]`.
- `parse_greenhouse_board(data, token, company)`, `parse_lever_board(data, token, company)`, `parse_ashby_board(data, token, company)` (skip `isListed == false`), `parse_workday_page(data, host, tenant, site, company) -> tuple[list[PostingIn], int total]` (URL = `https://<host>/<site><externalPath>`; `postedOn` parsed: "Posted Today" → today, "Posted Yesterday" → −1 day, "Posted N Days Ago" → −N, "Posted 30+ Days Ago" → −30; source_key = externalPath).
- Single-job parsers for paste: `parse_greenhouse_job`, `parse_lever_job`, `parse_workday_job_detail`, and `find_ashby_job(board_data, job_id)`.
- `parse_html_posting(html: str, url: str) -> PastedDetails` using `html.parser`: first `<script type="application/ld+json">` whose JSON (object, list, or `@graph`) contains `@type` `JobPosting` → `title`, `hiringOrganization.name`, `jobLocation[].address` (`addressLocality`, `addressRegion`, `addressCountry`) joined, `datePosted`; else `og:title`, else `<title>`. Company falls back to `og:site_name`, else the registrable-looking host label. Never executes or follows anything.
- `@dataclass PastedDetails(company: str, title: str, locations: list[str], date_posted: datetime | None, source: PostingSource, source_key: str)` (for non-board pages `source=PASTED`, `source_key = url_key`).

- [ ] Step 1: failing tests against each fixture (expected counts, field values, inactive/invisible handling, injected `javascript:` row dropped, 50 KB title truncated to 300, Workday "Posted N Days Ago" table, JSON-LD with `@graph`, title-only fallback, malformed JSON-LD ignored). Step 2: implement. Step 3: pass + full suite. Commit `feat(discovery): parsers for community lists, Greenhouse, Lever, Ashby, Workday and pasted pages`.

## Task 4: Source fetchers

**Files:** create `backend/app/services/discovery/sources.py`; test `backend/tests/services/discovery/test_sources.py`.

**Produces:**
- `LIST_SOURCE_BY_URL`: the Simplify URL → `SIMPLIFY`, the vanshb03 URL → `VANSHB03`; any other configured URL → `LIST` with `source_key` prefixed by a short stable hash of the URL so two custom lists never collide.
- `@dataclass SourceResult(name: str, postings: list[PostingIn], complete: bool, not_modified: bool = False, etag: str | None = None, error: str | None = None)`. `complete=True` means the result is the source's full current set, so missing postings may be marked closed. A failed source returns `postings=[]`, `complete=False`, `error="<name>: <one-line reason>"`.
- `fetch_list(http, url, etag) -> SourceResult` (304 → `not_modified=True, complete=False`).
- `fetch_board(http, company: WatchCompany, keywords: list[str]) -> SourceResult`: Greenhouse/Lever/Ashby one GET each (API URLs in spec §2b; Ashby with `?includeCompensation=false`). Workday: for each keyword, `POST https://<host>/wday/cxs/<tenant>/<site>/jobs` with `{"appliedFacets":{},"limit":20,"offset":k,"searchText":keyword}`, paging until `offset >= total` or 200 postings per keyword; results merged by `source_key`. Workday is `complete=False` (search results are not the full board), so Workday postings are closed only when a detail fetch 404s — out of scope; record a ruling that Workday postings close via the 90-day housekeeping only.
- `fetch_pasted(http, url) -> PastedDetails`: `parse_job_url` → board API single-job fetch (Ashby: fetch board and `find_ashby_job`); else `http.get_page` + `parse_html_posting`. Errors raise `DiscoveryFetchError` with a user-readable message ("Couldn't read that page (status 403)").

- [ ] Step 1: failing tests with `FakeDiscoveryHttp` for each path, including 304, 500, timeout exception, malformed JSON, Workday paging across two pages and the 200 cap, and that no request ever goes to a URL not built from the validated token. Step 2: implement. Step 3: pass + suite. Commit `feat(discovery): list, board and pasted-link fetchers behind DiscoveryHttp`.

## Task 5: Ingest — upsert, de-duplication, closing, housekeeping

**Files:** create `backend/app/services/discovery/ingest.py`; test `backend/tests/services/discovery/test_ingest.py`.

**Produces:** `ingest(db, result: SourceResult, now: datetime, watch_company_id: int | None = None) -> IngestStats(added, updated, closed, skipped_duplicates)` and `housekeep(db, now) -> int`.
- Existing `(source, source_key)` → update `company`, `title`, `locations`, `url`, `url_key`, `terms`, `category`, `sponsorship`, `last_seen_at=now`; set `closed = not active`; never touch `state`, `application_id`, `claude_*`.
- New and `active` → skip (count as duplicate) if its `url_key` matches any existing posting, or a posting with the same `lower(company)`, `lower(title)` from a different source has `first_seen_at >= now - 14 days`; else insert with `state=NEW`. New and inactive → ignore.
- If `result.complete`: postings of that source (and, for boards, that `watch_company_id`) not present in the result and not already closed → `closed=True`.
- Errors (`result.error`) → ingest nothing, close nothing.
- `housekeep`: delete postings with `state in (NEW, DISMISSED)` and (`closed` or `first_seen_at < now - 90 days`). Saved/applied never deleted.
- Use bulk queries (load existing keys for the source into memory once; insert with `db.add_all`). One commit per `ingest` call. A 5,000-row list must ingest in under ~5 s on the test DB (add a test that builds 5,000 synthetic rows and asserts it completes; mark it with no timing assertion if CI timing is flaky — record a ruling).

- [ ] Step 1: failing tests for each rule above, including the three-source duplicate case from Review focus, re-ingest idempotence (second identical ingest adds 0), saved posting closed by its source keeps `state=SAVED` with `closed=True`, failed source changes nothing, housekeeping boundaries (89 vs 91 days). Step 2: implement. Step 3: pass + suite. Commit `feat(discovery): ingest with cross-source de-duplication, closing and housekeeping`.

## Task 6: Filters, Inbox query, match count

**Files:** create `backend/app/services/discovery/filters.py`; test `backend/tests/services/discovery/test_filters.py`.

**Produces:**
- `@dataclass(frozen=True) DiscoveryFilters(terms, categories, include_keywords, watchlist_keywords, exclude_keywords, locations, hide_no_sponsorship)` and `filters_from_settings(s: AppSettings)`.
- `inbox_clause(f: DiscoveryFilters)` → a SQLAlchemy boolean expression implementing spec §4 exactly. List sources are `SIMPLIFY`, `VANSHB03`, `LIST`; board sources are `GREENHOUSE`, `LEVER`, `ASHBY`, `WORKDAY`; `PASTED` never appears in the Inbox. Keyword matching is case-insensitive whole-word: use Postgres `~*` with `\m<escaped>\M` (escape regex metacharacters with a helper; test `c++`, `co-op`, `.net`). Location: `EXISTS (SELECT 1 FROM unnest(locations) l WHERE l ILIKE '%' || :loc || '%')` with `%`/`_` escaped. Sponsorship hide list: `"Does Not Offer Sponsorship"`, `"U.S. Citizenship is Required"`.
- `list_postings(db, view: Literal["inbox","saved","dismissed"], filters, limit=50, offset=0) -> tuple[list[Posting], int]`: inbox = `state NEW`, not closed, `inbox_clause`, ordered `claude_score DESC NULLS LAST, coalesce(date_posted, first_seen_at) DESC, id DESC`; saved = `state SAVED`, newest `state_changed_at` first; dismissed = `state DISMISSED`, newest `state_changed_at` first, capped at 200 total.
- `match_count(db, filters) -> int` (the Inbox count for arbitrary, unsaved filters — used by the Settings live count).

- [ ] Step 1: failing tests: one test per rule, empty-list = "any" semantics, watchlist keyword rule applies to boards only, term rule applies to lists only, `PASTED` excluded, closed excluded, ordering, pagination totals, regex-metacharacter keywords. Step 2: implement. Step 3: pass + suite. Commit `feat(discovery): query-time filters, inbox listing and match count`.

## Task 7: Scanner, advisory lock, `job-scan` service

**Files:** create `backend/app/services/discovery/scanner.py`, `backend/app/jobs/job_scan.py`; modify `docker-compose.yml`; test `backend/tests/services/discovery/test_scanner.py`, `backend/tests/jobs/test_job_scan.py`.

**Produces:**
- `SCAN_LOCK_KEY` (a fixed bigint constant). `run_scan(db, http: DiscoveryHttp, now: datetime | None = None, pause: Callable[[float], None] = time.sleep) -> ScanReport | None`: `SELECT pg_try_advisory_lock(key)`; if false return `None`. Otherwise, in a `try/finally` that always unlocks: for each `discovery_list_urls` → `fetch_list` with the stored ETag → `ingest`; store the new ETag on success; for each `WatchCompany` → `fetch_board` with `discovery_watchlist_keywords` → `ingest(watch_company_id=...)`, update `last_checked_at` and `last_error` (cleared on success), `pause(1.0)` between companies; then `housekeep`; then `last_scan_at=now` and `last_scan_error` = the joined per-source errors (≤2000 chars) or `None`. Unexpected exceptions per source are caught and recorded; the scan continues.
- `ScanReport(added, closed, removed, errors: list[str])`.
- `scan_status(db) -> dict` (`last_scan_at`, `last_scan_error`, `scanning: bool` via `pg_try_advisory_lock` + immediate unlock, `inbox_count`).
- `job_scan.py`: like `nightly_sheet_sync.py` — loop: scan, then sleep `discovery_scan_hours` hours (re-read each loop); run one scan at startup after a 60 s delay; catch and log everything; real `HttpxDiscoveryHttp`.
- `docker-compose.yml`: `job-scan` service (`build: ./backend`, `restart: unless-stopped`, `env_file: .env`, `environment: TZ: ${TZ:-UTC}`, `command: python -m app.jobs.job_scan`, `depends_on: [db]`).

- [ ] Step 1: failing tests: full scan over fakes ingests lists + boards and records ETags; 304 path skips ingest; one failing source recorded while the others ingest; lock held by a second connection → `run_scan` returns `None` and writes nothing (open a separate engine connection in the test to hold the lock; release in teardown); lock released after an exception; `scan_status` reports `scanning`; job loop test with a fake sleep that raises to stop after two iterations. Step 2: implement. Step 3: pass + suite; `docker compose config` parses (use a temporary `.env` copied from `.env.example`, then delete it). Commit `feat(discovery): single-flight scanner and job-scan service`.

## Task 8: Posting actions, paste, watchlist services

**Files:** create `backend/app/services/discovery/actions.py`, `backend/app/services/discovery/watchlist.py`, `backend/app/schemas/discovery.py`; modify `backend/app/services/errors.py`; test `backend/tests/services/discovery/test_actions.py`, `backend/tests/services/discovery/test_watchlist.py`.

**Produces:**
- `errors.py`: `PostingNotFoundError`, `InvalidPostingStateError(message)`, `WatchCompanyNotFoundError`, `UnsupportedCareersSiteError(message)`, `DuplicateWatchCompanyError`.
- `schemas/discovery.py`: `PostingOut` (all user-visible columns, `from_attributes`), `PostingPage(items, total)`, `PasteIn(url: str)`, `PastePreviewOut(company, title, locations, url, date_posted, source)`, `PasteConfirmIn(url, company, title, locations ≤20 items, date_posted optional)` with the Global caps, `WatchCompanyIn(careers_url, name optional ≤200)`, `WatchCompanyOut` (+ `open_matches: int`), `DismissAllIn(ids: list[int], max 500)`, `ScanStatusOut`, `MatchCountIn` (same fields as the discovery filter settings), `MatchCountOut(count)`.
- `actions.py`: `save(db, id, now)` (NEW or DISMISSED → SAVED), `dismiss(db, id, now)` (NEW or SAVED → DISMISSED), `restore(db, id, now)` (DISMISSED → NEW), `dismiss_many(db, ids, now) -> int` (only NEW ones), `apply(db, id, today) -> Application` (SAVED or NEW → APPLIED; creates via `create_application` with `status=applied`, `date_applied=today`, `company`, `role_title=title`, `location=locations[0] if any`, `job_link=url`, `source="Discover: <Source label>"`; sets `application_id`; idempotent: a posting already APPLIED with a live application raises `InvalidPostingStateError("already applied")`), `paste_preview(db, http, url) -> PastePreviewOut` (no DB write; a URL already stored → `InvalidPostingStateError("already saved")` with the existing state), `paste_confirm(db, data, now) -> Posting` (state SAVED, `source` from the URL's board recognition or `PASTED`, `source_key` = job id or `url_key`; if the `url_key` exists, move that posting to SAVED instead of inserting). Every state change sets `state_changed_at=now`.
- `watchlist.py`: `add_company(db, data) -> WatchCompany` (`parse_board_url` → else if host matches `KNOWN_CUSTOM_SITES` raise `UnsupportedCareersSiteError("<Company> uses its own careers site, so it can't be watched. Its internships come in through the community lists, and you can paste any of its postings.")` → else raise `UnsupportedCareersSiteError("That careers page isn't on Greenhouse, Lever, Ashby or Workday, so it can't be watched. You can still paste individual postings from it.")`; name defaults to the token prettified (`openai` → `Openai`; Workday tenant); duplicate → `DuplicateWatchCompanyError`), `list_companies(db, filters) -> list[tuple[WatchCompany, int open_matches]]`, `remove_company(db, id)` (its postings keep existing; `watch_company_id` nulls via FK).

- [ ] Step 1: failing tests for each transition (valid and invalid), apply creating exactly one application and one `company_contacts` queue item even if called twice, apply fields, paste preview/confirm paths (board URL, JSON-LD page, existing URL), watchlist add for each ATS, custom-site message for google.com, generic message for an unknown host, duplicate add. Step 2: implement. Step 3: pass + suite. Commit `feat(discovery): posting actions, paste-a-link and watchlist services`.

## Task 9: Discovery API routes

**Files:** create `backend/app/api/discovery.py`; modify `backend/app/main.py`, `backend/app/api/deps.py` (add `get_discovery_http` returning `HttpxDiscoveryHttp()`, overridable), `backend/tests/api/conftest.py` (override with a `FakeDiscoveryHttp` fixture), `backend/tests/api/test_claude_auth_boundary.py`; test `backend/tests/api/test_discovery_routes.py`.

**Routes** (all `Depends(get_current_user)`, under `/api/discovery`): `GET /postings?view=&limit=(1..100, default 50)&offset=(≥0)` → `PostingPage`; `POST /postings/{id}/save|dismiss|restore|apply` (apply returns the created application in the existing application output schema); `POST /postings/dismiss-all`; `POST /paste/preview`; `POST /paste`; `GET /watchlist`; `POST /watchlist`; `DELETE /watchlist/{id}`; `POST /scan` (if a scan is running → 409 `{"detail":"already scanning"}`; else schedule `run_scan` in `BackgroundTasks` with its own `SessionLocal` session, return 202 `{"started": true}`); `GET /status` → `ScanStatusOut`; `POST /match-count` (body `MatchCountIn`) → `MatchCountOut`. Error mapping: not found → 404, invalid state/duplicate → 409, unsupported site / fetch error → 422 with the service's message. `apply` and `save`/`dismiss`/`restore`/`dismiss-all`/`paste` schedule a backup sync of the new `TAB_SAVED_POSTINGS` (Task 10 creates the constant; in this task use a placeholder string constant defined in `sheet_sync_service` as `TAB_SAVED_POSTINGS = "Saved postings"` without adding it to `ALL_TABS` yet); `apply` also schedules `TAB_APPLICATIONS`.

- [ ] Step 1: failing route tests for each endpoint (auth required: 401 without session; happy paths; error mapping; scan 409 when the lock is held; scan 202 runs the scan with the fake http — call the background task synchronously via the TestClient), plus the Claude-token boundary list extended to every new route. Step 2: implement. Step 3: pass + suite. Commit `feat(discovery): /api/discovery routes`.

## Task 10: Backup sheet "Saved postings" tab

**Files:** modify `backend/app/services/sheets_client.py` (add `ensure_tabs(spreadsheet_id, titles)` using `GET .../spreadsheets/{id}?fields=sheets.properties.title` then one `:batchUpdate` with `addSheet` requests for missing titles), `backend/app/services/sheet_sync_service.py` (`TAB_SAVED_POSTINGS` in `ALL_TABS`; `saved_posting_rows` with header `Company, Role, Locations, Link, Saved, Closed`; `sync_tabs` calls `client.ensure_tabs` before writing tabs to an existing sheet); update the in-memory fake client in tests; test additions in `backend/tests/services/test_sheet_sync_service.py`.

- [ ] Step 1: failing tests: an existing three-tab sheet gains the fourth tab once and is then written; rows render plain text (a title starting with `=` stays text — RAW input already guarantees it; assert the value passed through unchanged); closed shows `yes`/blank; the nightly sync covers the new tab. Step 2: implement. Step 3: pass + suite. Commit `feat(discovery): Saved postings tab in the backup sheet`.

## Task 11: Frontend types, API client, store

**Files:** create `frontend/src/lib/types/discovery.ts`, `frontend/src/lib/api/discovery.ts`, `frontend/src/lib/stores/discovery.ts`; modify `frontend/src/lib/api/settings.ts` and its types for the new settings fields; tests alongside (`*.test.ts`).

**Produces:** camelCase types mirroring the backend (`Posting`, `PostingSource`, `PostingState`, `PostingPage`, `WatchCompany`, `PastePreview`, `ScanStatus`, discovery settings fields); API functions for every route in Task 9 using `apiFetch` and the existing case helpers; `sourceLabel(source)` (`simplify` → "Simplify", `vanshb03` → "vanshb03 list", `list` → "Community list", boards by vendor name, `pasted` → "Pasted"); `postedAgo(date, now)` ("today", "1 day ago", "N days ago", "N weeks ago"); a `discoveryStatus` store holding `ScanStatus` with `refreshDiscoveryStatus()` used by the sidebar badge and dashboard widget.

- [ ] Step 1: failing tests for mapping (snake → camel both ways), each API call's method/URL/body, `sourceLabel`, `postedAgo`. Step 2: implement. Step 3: `npm run test -- --run`, `npm run check`. Commit `feat(discovery): frontend types, API client and status store`.

## Task 12: Discover page — Inbox, Saved, Dismissed, paste box, scan header

**Files:** create `frontend/src/routes/Discover.svelte`, `frontend/src/lib/components/discovery/PostingRow.svelte`, `frontend/src/lib/components/discovery/PasteLink.svelte`, `frontend/src/lib/components/discovery/ScanHeader.svelte`; modify `frontend/src/App.svelte` (route `/discover`), `frontend/src/lib/components/NavSidebar.svelte` (Discover link after Applications with an Inbox-count badge from the status store, `aria-label` including the count); tests for each.

**Behaviour:** tabs Inbox / Saved / Dismissed / Watchlist (Watchlist content arrives in Task 13; render a placeholder link to it for now — or build the tab shell so Task 13 only fills it). Rows show company, title, locations (first two + "+N more"), posted-ago, source badge, sponsorship note when present and not "Other", a **closed** badge; all text via normal interpolation. Inbox actions Save / Dismiss / Open (`target="_blank" rel="noopener noreferrer"`, only when the URL starts with `http`); **Dismiss all shown** with `confirm()`; Saved actions Apply (confirm "Add <Company> – <Role> to your tracker as Applied today?"; on success toast with a link to Applications), Remove, Open; Dismissed: Restore. Optimistic removal from the list with rollback + error toast on failure. Pagination with "Load more" (50 per page). `ScanHeader`: last scan time, Scan now (disabled while scanning; 409 → "A scan is already running"), polls `/status` every 5 s while scanning, refreshes the list when it finishes, shows `last_scan_error` lines. `PasteLink`: URL input → Preview → editable fields (company, title, locations comma-separated) → Save → appears in Saved; 422 messages shown inline. Accessible: tabs as `role=tablist`, buttons labelled with the posting ("Save Stripe – SWE Intern").

- [ ] Step 1: failing component tests (mock the API module): each action, rollback on failure, dismiss-all confirm, apply confirm text, paste flow including an error, scan button states and 409, closed badge, a posting whose title contains `<img src=x onerror=alert(1)>` renders as literal text. Step 2: implement. Step 3: tests, `npm run check`, `npm run build`. Commit `feat(discovery): Discover page with inbox, saved and dismissed lists`.

## Task 13: Watchlist tab and Settings → Job discovery

**Files:** create `frontend/src/lib/components/discovery/Watchlist.svelte`, `frontend/src/lib/components/settings/DiscoverySettings.svelte`; modify `frontend/src/routes/Discover.svelte`, `frontend/src/routes/Settings.svelte`; tests.

**Behaviour:** Watchlist: paste careers URL (+ optional name) → Add; list shows name, system (Greenhouse/Lever/Ashby/Workday), last checked, open matches, last error, Remove (confirm); the service's custom-site message shown inline on 422; a one-line note "Google, Microsoft, Apple, Meta and Amazon use their own sites; their internships come in through the community lists." Settings section "Job discovery": chip-style editors for terms, categories (with the five Simplify categories offered as suggestions), include keywords, watchlist keywords, exclude keywords, locations; hide-no-sponsorship checkbox; scan interval hours; list URLs (advanced, collapsed `<details>`); live "N postings match" via `POST /api/discovery/match-count`, debounced 400 ms, ignoring stale responses; Save via the existing settings update; field errors from 422 shown.

- [ ] Step 1: failing tests: add/remove/error paths; settings chips add/remove/dedupe; debounced count with out-of-order responses (only the latest applies); save payload shape. Step 2: implement. Step 3: tests, check, build. Commit `feat(discovery): watchlist tab and job discovery settings`.

## Task 14: Dashboard "New postings" widget

**Files:** create `frontend/src/lib/components/widgets/NewPostings.svelte`; modify `frontend/src/lib/dashboard/layout.ts` (`"new-postings"` added to `defaultLayout`), `frontend/src/routes/Dashboard.svelte` (render it); tests.

**Behaviour:** shows the Inbox count and the five newest Inbox postings (company – title, posted-ago), each linking to `#/discover`; empty state "No new matches. Adjust filters in Settings."; load failure state with Retry.

- [ ] Step 1: failing tests (count, five rows, empty, failure + retry, existing saved layouts gain the widget via `reconcileLayout`). Step 2: implement. Step 3: tests, check, build. Commit `feat(discovery): New postings dashboard widget`.

## Task 15: End-to-end scan test, docs

**Files:** create `backend/tests/api/test_discovery_flow.py`; modify `README.md` (new section "Job discovery": what it scans, how to add a watchlist company, the Workday caveat, `docker compose up -d --build` to start `job-scan`, where filters live); `docs/phases/README.md` (fix the Phase 1b row to "Complete (merged 2026-10-08)" and add a Phase 2 row).

**End-to-end test** (fakes only): settings defaults → add a Greenhouse watchlist company via the API → `POST /scan` → Inbox shows matching list rows and board rows, not the Hardware/Summer 2026/senior ones → save one → apply it → an Applied application exists with the job link and one `company_contacts` queue item → re-scan with the posting marked inactive → saved/applied posting shows closed but is not deleted → paste a JSON-LD page URL → it appears in Saved.

- [ ] Step 1: write and pass the flow test. Step 2: docs. Step 3: full backend and frontend suites, check, build, alembic cycle. Commit `test(discovery): end-to-end scan flow; docs: job discovery`.

## After Task 15

Whole-branch review of `git diff origin/main...HEAD` against the spec (security: SSRF guard, untrusted content, token validation; cross-task contracts; frontend↔backend field names; migration). Fix Critical/Important in one round, re-verify, write `docs/phases/phase-2-report.md` (structure of the Phase 1b report), push, open a PR to `main` for the owner to merge.
