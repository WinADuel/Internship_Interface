# Discovery fixtures

Recorded sample responses for the job-discovery parsers
(`app/services/discovery/parsers.py`, tests in `tests/services/discovery/`).
No test touches the network; these files stand in for it.

## Real data (trimmed)

Downloaded once on 2026-10-08 from the URLs in spec §2a, trimmed to a few rows
each. Apart from the injected rows listed below, rows are unchanged.

| File | Source | Rows |
|---|---|---|
| `simplify_listings.json` | `SimplifyJobs/Summer2027-Internships` `listings.json` | 12 real + 2 injected |
| `vanshb03_listings.json` | `vanshb03/Summer2027-Internships` `listings.json` | 9 real + 2 injected |

The rows cover active and inactive, `is_visible: false` (Simplify), Summer 2027
and other terms, several categories (including Simplify's older long names such
as "Software Engineering"), every sponsorship value, multiple locations, and
more than 20 locations.

Injected by hand at the end of both files (ids start with `injected-`):

- `injected-javascript-url`: a `javascript:` URL. The parser must drop it.
- `injected-50kb-title`: a title over 50,000 characters. The parser must cut it to 300.

What the real data showed, which the spec did not say:

- vanshb03's `season` is a bare season word (`"Summer"`, `"Fall"`,
  `"Spring/Summer"`, and once the string `"null"`), not `"Summer 2027"`.
- Simplify's `category` mixes short names (`Software`, `AI/ML/Data`, `Hardware`,
  `Product`, `Quant`) with older long ones (`Software Engineering`,
  `Data Science, AI & Machine Learning`, `Hardware Engineering`,
  `Quantitative Finance`, `Product Management`).

## Written from vendor documentation (not yet verified)

The cloud sandbox cannot reach Greenhouse, Lever, Ashby or Workday, so these
files were written by hand. Their shapes come from the vendors' public API
docs (for Workday, from how its career pages call the undocumented endpoint).
The companies and ids in them are made up.

**Check each one against a live response on the first real scan, and update
this file and the parsers if a shape differs.**

| File | Endpoint |
|---|---|
| `greenhouse_board.json` | `GET https://boards-api.greenhouse.io/v1/boards/<token>/jobs` |
| `greenhouse_job.json` | `GET https://boards-api.greenhouse.io/v1/boards/<token>/jobs/<id>` |
| `lever_board.json` | `GET https://api.lever.co/v0/postings/<token>?mode=json` |
| `lever_job.json` | `GET https://api.lever.co/v0/postings/<token>/<id>` |
| `ashby_board.json` | `GET https://api.ashbyhq.com/posting-api/job-board/<token>` |
| `workday_jobs_page1.json`, `workday_jobs_page2.json` | `POST https://<host>/wday/cxs/<tenant>/<site>/jobs` |
| `workday_job_detail.json` | `GET https://<host>/wday/cxs/<tenant>/<site>/job/<...>` |

Things to check in particular:

- Greenhouse: whether job objects include `company_name` (the single-job parser
  falls back to the board token if not).
- Workday: `workday_jobs_page2.json` has `"total": 0`. That matches reports that
  Workday gives the real total only on the first page; the fetcher should take
  the total from the first page. Also check the `postedOn` wording
  ("Posted Today", "Posted Yesterday", "Posted 3 Days Ago", "Posted 30+ Days Ago")
  and that multi-location jobs show `locationsText` as "N Locations".

Each board fixture also holds rows a parser must drop or handle: a `javascript:`
URL or Workday `externalPath`, an empty title, a missing location, and an
unlisted Ashby job.

## Pasted pages (hand-written HTML)

- `jobposting_page.html`: a page with a malformed JSON-LD script, an
  `Organization` script, then a `JobPosting` inside `@graph`.
- `title_only_page.html`: no `JobPosting`, so only the `<title>` is used.
