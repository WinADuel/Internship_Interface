import { afterEach, describe, expect, it, vi } from "vitest";
import {
  mapApplicationFromApi,
  mapApplicationInputToApi,
  listApplications,
  createApplication,
  updateApplication,
  changeStatus,
  getStatusHistory,
  getRecentActivity,
} from "./applications";
import { fakeApplication } from "../testing/fixtures";
import type { ApplicationInput } from "../types/application";

const rawApp = {
  id: 1, company: "Stripe", role_title: "SWE Intern", status: "wishlist",
  date_applied: null, job_link: null, notes: null, resume_version: null,
  contact_person: null, salary_range: null, location: null, source: null,
  priority: "medium", follow_up_date: null, interview_datetime: null,
  google_doc_link: null, archived: false, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};

function mockFetch(body: unknown, status = 200) {
  const fn = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("mappers", () => {
  it("maps snake_case api fields to camelCase", () => {
    const mapped = mapApplicationFromApi(rawApp);
    expect(mapped.roleTitle).toBe("SWE Intern");
    expect(mapped.dateApplied).toBeNull();
  });

  it("maps camelCase input back to snake_case, symmetric with the from-api mapper", () => {
    const app = fakeApplication({ company: "Stripe", dateApplied: "2026-02-01", jobLink: "http://x" });
    const input: ApplicationInput = {
      company: app.company, roleTitle: app.roleTitle, dateApplied: app.dateApplied, status: app.status,
      jobLink: app.jobLink, notes: app.notes, resumeVersion: app.resumeVersion,
      contactPerson: app.contactPerson, salaryRange: app.salaryRange, location: app.location,
      source: app.source, priority: app.priority, followUpDate: app.followUpDate,
      interviewDatetime: app.interviewDatetime, googleDocLink: app.googleDocLink,
    };
    const raw = mapApplicationInputToApi(input);
    expect(raw).toMatchObject({ role_title: "SWE Intern", date_applied: "2026-02-01", job_link: "http://x" });
    expect(raw).not.toHaveProperty("roleTitle");
    const roundTrip = mapApplicationFromApi({
      ...raw, id: app.id, archived: false, created_at: app.createdAt, updated_at: app.updatedAt,
    });
    expect(roundTrip).toEqual(app);
  });

  it("only includes provided keys for partial input", () => {
    expect(mapApplicationInputToApi({ roleTitle: "X" })).toEqual({ role_title: "X" });
  });
});

describe("api calls", () => {
  it("listApplications passes include_archived", async () => {
    const f = mockFetch([rawApp]);
    const apps = await listApplications(true);
    expect(f.mock.calls[0][0]).toBe("/api/applications?include_archived=true");
    expect(apps[0].roleTitle).toBe("SWE Intern");
  });

  it("createApplication posts snake_case JSON", async () => {
    const f = mockFetch(rawApp, 201);
    await createApplication({ company: "Stripe", roleTitle: "SWE Intern" } as ApplicationInput);
    const [path, init] = f.mock.calls[0];
    expect(path).toBe("/api/applications");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ company: "Stripe", role_title: "SWE Intern" });
  });

  it("updateApplication patches only given fields", async () => {
    const f = mockFetch(rawApp);
    await updateApplication(3, { notes: "hi" });
    const [path, init] = f.mock.calls[0];
    expect(path).toBe("/api/applications/3");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ notes: "hi" });
  });

  it("changeStatus posts new_status", async () => {
    const f = mockFetch(rawApp);
    await changeStatus(3, "applied");
    const [path, init] = f.mock.calls[0];
    expect(path).toBe("/api/applications/3/status");
    expect(JSON.parse(init.body)).toEqual({ new_status: "applied" });
  });

  it("getStatusHistory preserves null old_status", async () => {
    mockFetch([{ old_status: null, new_status: "wishlist", changed_at: "t" }]);
    const h = await getStatusHistory(1);
    expect(h).toEqual([{ oldStatus: null, newStatus: "wishlist", changedAt: "t" }]);
  });

  it("getRecentActivity maps entries and passes limit", async () => {
    const f = mockFetch([
      { application_id: 2, company: "A", role_title: "R", old_status: null, new_status: "wishlist", changed_at: "t" },
    ]);
    const a = await getRecentActivity(5);
    expect(f.mock.calls[0][0]).toBe("/api/applications/activity?limit=5");
    expect(a[0]).toEqual({ applicationId: 2, company: "A", roleTitle: "R", oldStatus: null, newStatus: "wishlist", changedAt: "t" });
  });
});
