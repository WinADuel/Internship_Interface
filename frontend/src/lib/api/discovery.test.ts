import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./client";
import {
  addWatchCompany,
  applyToPosting,
  confirmPaste,
  dismissAllPostings,
  dismissPosting,
  getMatchCount,
  getScanStatus,
  listPostings,
  listWatchlist,
  mapPostingFromApi,
  previewPaste,
  removeWatchCompany,
  restorePosting,
  savePosting,
  startScan,
} from "./discovery";
import { getSettings, updateSettings } from "./settings";
import { fakePosting, fakeWatchCompany } from "../testing/fixtures";

const rawPosting = {
  id: 1, source: "simplify", company: "Stripe", title: "SWE Intern", locations: ["NYC", "Remote"],
  url: "https://stripe.com/jobs/1", terms: ["Summer 2027"], category: "Software", sponsorship: null,
  date_posted: "2026-10-01T00:00:00Z", first_seen_at: "2026-10-02T00:00:00Z", last_seen_at: "2026-10-03T00:00:00Z",
  closed: false, state: "new", state_changed_at: "2026-10-02T00:00:00Z", application_id: null,
  watch_company_id: null, claude_score: null, claude_note: null,
};

const rawWatch = {
  id: 4, name: "Stripe", ats: "greenhouse", board_token: "stripe", careers_url: "https://boards.greenhouse.io/stripe",
  added_at: "2026-10-01T00:00:00Z", last_checked_at: null, last_error: null, open_matches: 0,
};

const rawApplication = {
  id: 9, company: "Stripe", role_title: "SWE Intern", date_applied: "2026-10-08", status: "applied",
  job_link: "https://stripe.com/jobs/1", notes: null, resume_version: null, contact_person: null, salary_range: null,
  location: "NYC", source: "Discover: Simplify", priority: "medium", follow_up_date: null, interview_datetime: null,
  google_doc_link: null, archived: false, created_at: "2026-10-08T00:00:00Z", updated_at: "2026-10-08T00:00:00Z",
};

function mockFetch(body: unknown, status = 200) {
  const fn = vi.fn().mockImplementation(
    async () =>
      status === 204
        ? new Response(null, { status })
        : new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

function call(fn: ReturnType<typeof vi.fn>, i = 0) {
  const [url, init] = fn.mock.calls[i] as [string, RequestInit];
  return { url, method: init.method ?? "GET", body: init.body ? JSON.parse(init.body as string) : undefined };
}

afterEach(() => vi.unstubAllGlobals());

describe("discovery api mapping", () => {
  it("maps a posting from snake_case to camelCase", () => {
    expect(mapPostingFromApi(rawPosting)).toEqual(fakePosting());
  });

  it("defaults missing location and term arrays to empty", () => {
    const { locations: _l, terms: _t, ...rest } = rawPosting;
    const p = mapPostingFromApi(rest);
    expect(p.locations).toEqual([]);
    expect(p.terms).toEqual([]);
  });
});

describe("discovery api postings", () => {
  it("lists a view with paging and maps the page", async () => {
    const fn = mockFetch({ items: [rawPosting], total: 7 });
    const page = await listPostings("saved", { limit: 20, offset: 40 });
    expect(call(fn)).toEqual({ url: "/api/discovery/postings?view=saved&limit=20&offset=40", method: "GET", body: undefined });
    expect(page).toEqual({ items: [fakePosting()], total: 7 });
  });

  it("lists the inbox by default with 50 per page", async () => {
    const fn = mockFetch({ items: [], total: 0 });
    await listPostings();
    expect(call(fn).url).toBe("/api/discovery/postings?view=inbox&limit=50&offset=0");
  });

  it.each([
    ["save", savePosting],
    ["dismiss", dismissPosting],
    ["restore", restorePosting],
  ] as const)("posts %s for one posting and maps the result", async (action, fn) => {
    const fetchFn = mockFetch({ ...rawPosting, state: "saved" });
    const posting = await fn(1);
    expect(call(fetchFn)).toEqual({ url: `/api/discovery/postings/1/${action}`, method: "POST", body: undefined });
    expect(posting.state).toBe("saved");
    expect(posting.stateChangedAt).toBe("2026-10-02T00:00:00Z");
  });

  it("applies and maps the created application", async () => {
    const fn = mockFetch(rawApplication, 201);
    const app = await applyToPosting(1);
    expect(call(fn)).toEqual({ url: "/api/discovery/postings/1/apply", method: "POST", body: undefined });
    expect(app.roleTitle).toBe("SWE Intern");
    expect(app.jobLink).toBe("https://stripe.com/jobs/1");
    expect(app.source).toBe("Discover: Simplify");
  });

  it("dismisses all shown ids and returns the count", async () => {
    const fn = mockFetch({ dismissed: 2 });
    expect(await dismissAllPostings([3, 5])).toBe(2);
    expect(call(fn)).toEqual({ url: "/api/discovery/postings/dismiss-all", method: "POST", body: { ids: [3, 5] } });
  });

  it("surfaces a 409 as an ApiError with the detail", async () => {
    mockFetch({ detail: "only a saved posting can be applied to" }, 409);
    await expect(applyToPosting(1)).rejects.toMatchObject({ status: 409, message: "only a saved posting can be applied to" });
  });
});

describe("discovery api paste", () => {
  it("previews a URL and maps the editable fields", async () => {
    const fn = mockFetch({
      company: "Stripe", title: "SWE Intern", locations: ["NYC"], url: "https://stripe.com/jobs/1",
      date_posted: null, source: "pasted",
    });
    const preview = await previewPaste("https://stripe.com/jobs/1");
    expect(call(fn)).toEqual({ url: "/api/discovery/paste/preview", method: "POST", body: { url: "https://stripe.com/jobs/1" } });
    expect(preview).toEqual({
      company: "Stripe", title: "SWE Intern", locations: ["NYC"], url: "https://stripe.com/jobs/1",
      datePosted: null, source: "pasted",
    });
  });

  it("confirms the edited fields in snake_case and maps the saved posting", async () => {
    const fn = mockFetch({ ...rawPosting, source: "pasted", state: "saved" }, 201);
    const posting = await confirmPaste({
      url: "https://stripe.com/jobs/1", company: "Stripe", title: "SWE Intern", locations: ["NYC"],
      datePosted: "2026-10-01T00:00:00Z",
    });
    expect(call(fn)).toEqual({
      url: "/api/discovery/paste",
      method: "POST",
      body: {
        url: "https://stripe.com/jobs/1", company: "Stripe", title: "SWE Intern", locations: ["NYC"],
        date_posted: "2026-10-01T00:00:00Z",
      },
    });
    expect(posting.source).toBe("pasted");
  });

  it("surfaces a 422 unsupported-site message", async () => {
    mockFetch({ detail: "couldn't read a job posting from that page" }, 422);
    const err = await previewPaste("https://example.com").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).message).toBe("couldn't read a job posting from that page");
  });
});

describe("discovery api watchlist", () => {
  it("lists watched companies", async () => {
    const fn = mockFetch([{ ...rawWatch, open_matches: 3 }]);
    expect(await listWatchlist()).toEqual([fakeWatchCompany({ openMatches: 3 })]);
    expect(call(fn)).toEqual({ url: "/api/discovery/watchlist", method: "GET", body: undefined });
  });

  it("adds a company with an optional name in snake_case", async () => {
    const fn = mockFetch(rawWatch, 201);
    const added = await addWatchCompany({ careersUrl: "https://boards.greenhouse.io/stripe", name: "Stripe" });
    expect(call(fn)).toEqual({
      url: "/api/discovery/watchlist",
      method: "POST",
      body: { careers_url: "https://boards.greenhouse.io/stripe", name: "Stripe" },
    });
    expect(added).toEqual(fakeWatchCompany());
    await addWatchCompany({ careersUrl: "https://jobs.lever.co/x" });
    expect(call(fn, 1).body).toEqual({ careers_url: "https://jobs.lever.co/x" });
  });

  it("removes a company (204)", async () => {
    const fn = mockFetch(null, 204);
    await expect(removeWatchCompany(4)).resolves.toBeUndefined();
    expect(call(fn)).toEqual({ url: "/api/discovery/watchlist/4", method: "DELETE", body: undefined });
  });
});

describe("discovery api scan, status and match count", () => {
  it("starts a scan", async () => {
    const fn = mockFetch({ started: true }, 202);
    expect(await startScan()).toEqual({ started: true });
    expect(call(fn)).toEqual({ url: "/api/discovery/scan", method: "POST", body: undefined });
  });

  it("reports a running scan as a 409 ApiError", async () => {
    mockFetch({ detail: "already scanning" }, 409);
    await expect(startScan()).rejects.toMatchObject({ status: 409, message: "already scanning" });
  });

  it("maps the scan status", async () => {
    const fn = mockFetch({ last_scan_at: "2026-10-08T10:00:00Z", last_scan_error: "lever:x: timeout", scanning: true, inbox_count: 12 });
    expect(await getScanStatus()).toEqual({
      lastScanAt: "2026-10-08T10:00:00Z", lastScanError: "lever:x: timeout", scanning: true, inboxCount: 12,
    });
    expect(call(fn)).toEqual({ url: "/api/discovery/status", method: "GET", body: undefined });
  });

  it("sends only the filter fields, named discovery_*, for the match count", async () => {
    const fn = mockFetch({ count: 42 });
    const count = await getMatchCount({
      discoveryTerms: ["Summer 2027"], discoveryCategories: ["Software"], discoveryIncludeKeywords: ["intern"],
      discoveryWatchlistKeywords: [], discoveryExcludeKeywords: ["senior"], discoveryLocations: ["NYC"],
      discoveryHideNoSponsorship: true,
    });
    expect(count).toBe(42);
    expect(call(fn)).toEqual({
      url: "/api/discovery/match-count",
      method: "POST",
      body: {
        discovery_terms: ["Summer 2027"], discovery_categories: ["Software"], discovery_include_keywords: ["intern"],
        discovery_watchlist_keywords: [], discovery_exclude_keywords: ["senior"], discovery_locations: ["NYC"],
        discovery_hide_no_sponsorship: true,
      },
    });
  });

  it("ignores non-filter settings passed to the match count", async () => {
    const fn = mockFetch({ count: 1 });
    const filters = {
      discoveryTerms: [], discoveryCategories: [], discoveryIncludeKeywords: [], discoveryWatchlistKeywords: [],
      discoveryExcludeKeywords: [], discoveryLocations: [], discoveryHideNoSponsorship: false,
      discoveryListUrls: ["https://x.example/listings.json"], discoveryScanHours: 6,
    };
    await getMatchCount(filters);
    expect(Object.keys(call(fn).body)).not.toContain("discovery_list_urls");
    expect(Object.keys(call(fn).body)).not.toContain("discovery_scan_hours");
  });
});

describe("settings api discovery fields", () => {
  it("maps discovery settings from the API", async () => {
    mockFetch({
      outreach_profile: "", nudge_unsent_days: 5, nudge_followup_days: 10, nudge_gone_quiet_days: 10,
      nudge_replied_stale_days: 14, claude_job_max_items: 8, backup_sheet_id: null, last_sheet_sync_at: null,
      last_sheet_sync_error: null, discovery_list_urls: ["https://a.example/l.json"], discovery_terms: ["Summer 2027"],
      discovery_categories: ["Software"], discovery_include_keywords: [], discovery_watchlist_keywords: ["intern"],
      discovery_exclude_keywords: ["senior"], discovery_locations: [], discovery_hide_no_sponsorship: true,
      discovery_scan_hours: 6, last_scan_at: "2026-10-08T10:00:00Z", last_scan_error: null,
    });
    const s = await getSettings();
    expect(s.discoveryListUrls).toEqual(["https://a.example/l.json"]);
    expect(s.discoveryTerms).toEqual(["Summer 2027"]);
    expect(s.discoveryCategories).toEqual(["Software"]);
    expect(s.discoveryWatchlistKeywords).toEqual(["intern"]);
    expect(s.discoveryExcludeKeywords).toEqual(["senior"]);
    expect(s.discoveryHideNoSponsorship).toBe(true);
    expect(s.discoveryScanHours).toBe(6);
    expect(s.lastScanAt).toBe("2026-10-08T10:00:00Z");
    expect(s.lastScanError).toBeNull();
  });

  it("saves discovery settings in snake_case", async () => {
    const fn = mockFetch({ discovery_scan_hours: 12 });
    await updateSettings({
      discoveryTerms: ["Fall 2027"], discoveryIncludeKeywords: ["ml"], discoveryLocations: ["Remote"],
      discoveryHideNoSponsorship: false, discoveryScanHours: 12, discoveryListUrls: [],
    });
    expect(call(fn)).toEqual({
      url: "/api/settings",
      method: "PATCH",
      body: {
        discovery_terms: ["Fall 2027"], discovery_include_keywords: ["ml"], discovery_locations: ["Remote"],
        discovery_hide_no_sponsorship: false, discovery_scan_hours: 12, discovery_list_urls: [],
      },
    });
  });
});
