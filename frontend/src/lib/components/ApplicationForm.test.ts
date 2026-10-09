import { fireEvent, render, screen } from "@testing-library/svelte";
import { get } from "svelte/store";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { applications } from "../stores/applications";
import { toasts } from "../stores/toast";
import { fakeApplication } from "../testing/fixtures";
import ApplicationForm from "./ApplicationForm.svelte";

function rawApplication(overrides: Record<string, unknown> = {}) {
  return {
    id: 7,
    company: "Globex",
    role_title: "Data Intern",
    date_applied: null,
    status: "wishlist",
    job_link: null,
    notes: null,
    resume_version: null,
    contact_person: null,
    salary_range: null,
    location: null,
    source: null,
    priority: "medium",
    follow_up_date: null,
    interview_datetime: null,
    google_doc_link: null,
    archived: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function okResponse(body: unknown) {
  return { ok: true, status: 200, json: async () => body };
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  applications.set([]);
  toasts.set([]);
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});
afterEach(() => vi.restoreAllMocks());

async function fill(label: string, value: string) {
  await fireEvent.input(screen.getByLabelText(label), { target: { value } });
}

describe("ApplicationForm", () => {
  it("renders every editable field", () => {
    render(ApplicationForm);
    for (const label of [
      "Company",
      "Role title",
      "Status",
      "Priority",
      "Date applied",
      "Follow-up date",
      "Interview date and time",
      "Job link",
      "Resume version",
      "Contact person",
      "Salary range",
      "Location",
      "Source",
      "Google Doc link",
      "Notes",
    ]) {
      expect(screen.getByLabelText(label)).toBeTruthy();
    }
  });

  it("create submits a snake_case payload and adds the result to the store", async () => {
    fetchMock.mockResolvedValue(okResponse(rawApplication()));
    const onsaved = vi.fn();
    render(ApplicationForm, { props: { onsaved } });

    await fill("Company", "  Globex ");
    await fill("Role title", "Data Intern");
    await fireEvent.change(screen.getByLabelText("Status"), { target: { value: "applied" } });
    await fireEvent.change(screen.getByLabelText("Priority"), { target: { value: "high" } });
    await fill("Date applied", "2026-03-01");
    await fill("Follow-up date", "2026-03-10");
    await fill("Interview date and time", "2026-03-12T14:30");
    await fill("Job link", "https://example.com/job");
    await fill("Notes", "Referred by Sam");
    await fireEvent.submit(screen.getByRole("form", { name: "Application" }));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/applications");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      company: "Globex",
      role_title: "Data Intern",
      status: "applied",
      priority: "high",
      date_applied: "2026-03-01",
      follow_up_date: "2026-03-10",
      interview_datetime: new Date(2026, 2, 12, 14, 30).toISOString(),
      job_link: "https://example.com/job",
      notes: "Referred by Sam",
      resume_version: null,
      contact_person: null,
      salary_range: null,
      location: null,
      source: null,
      google_doc_link: null,
    });
    await vi.waitFor(() => expect(get(applications)).toHaveLength(1));
    expect(get(applications)[0]).toMatchObject({ id: 7, company: "Globex", roleTitle: "Data Intern" });
    expect(onsaved).toHaveBeenCalledWith(expect.objectContaining({ id: 7 }));
  });

  it("create blocks a blank company or role title without calling the API", async () => {
    render(ApplicationForm);
    await fill("Role title", "Intern");
    await fireEvent.submit(screen.getByRole("form", { name: "Application" }));
    expect(screen.getByRole("alert").textContent).toMatch(/company/i);
    await fill("Company", "Acme");
    await fill("Role title", "   ");
    await fireEvent.submit(screen.getByRole("form", { name: "Application" }));
    expect(screen.getByRole("alert").textContent).toMatch(/role title/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("edit with an empty company is blocked client-side", async () => {
    const original = fakeApplication({ id: 3, company: "Initech" });
    applications.set([original]);
    render(ApplicationForm, { props: { application: original } });
    await fill("Company", "");
    await fireEvent.submit(screen.getByRole("form", { name: "Application" }));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toMatch(/company/i);
    expect(get(applications)[0].company).toBe("Initech");
  });

  it("edit prefills the fields, PATCHes the full input (blank fields become null) and replaces the store entry", async () => {
    const original = fakeApplication({
      id: 3,
      company: "Initech",
      roleTitle: "Intern",
      notes: "old note",
      followUpDate: "2026-04-01",
      interviewDatetime: new Date(2026, 3, 2, 9, 0).toISOString(),
    });
    applications.set([original]);
    fetchMock.mockResolvedValue(okResponse(rawApplication({ id: 3, company: "Initech 2", role_title: "Intern" })));
    const onsaved = vi.fn();
    render(ApplicationForm, { props: { application: original, onsaved } });

    expect((screen.getByLabelText("Company") as HTMLInputElement).value).toBe("Initech");
    expect((screen.getByLabelText("Follow-up date") as HTMLInputElement).value).toBe("2026-04-01");
    // The next interview is derived from the rounds: shown, not editable.
    expect(screen.queryByLabelText("Interview date and time")).toBeNull();
    expect(screen.getByText("Next interview")).toBeInTheDocument();
    expect(screen.getByText(new Date(2026, 3, 2, 9, 0).toLocaleString())).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Manage rounds" }).getAttribute("href")).toBe("#/interviews");

    await fill("Company", "Initech 2");
    await fill("Notes", "");
    await fireEvent.submit(screen.getByRole("form", { name: "Application" }));

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/applications/3");
    expect(init.method).toBe("PATCH");
    const body = JSON.parse(init.body);
    expect(body).toMatchObject({ company: "Initech 2", notes: null, follow_up_date: "2026-04-01" });
    expect(body).not.toHaveProperty("interview_datetime");
    await vi.waitFor(() => expect(get(applications)[0].company).toBe("Initech 2"));
    expect(get(applications)).toHaveLength(1);
    expect(onsaved).toHaveBeenCalled();
  });

  it("shows a readable toast for a 422 validation error array and stays open", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({
        detail: [{ type: "url_parsing", loc: ["body", "job_link"], msg: "Input should be a valid URL" }],
      }),
    });
    const onsaved = vi.fn();
    render(ApplicationForm, { props: { onsaved } });
    await fill("Company", "Acme");
    await fill("Role title", "Intern");
    await fireEvent.submit(screen.getByRole("form", { name: "Application" }));
    await vi.waitFor(() => expect(get(toasts)).toHaveLength(1));
    expect(get(toasts)[0].text).toBe("job_link: Input should be a valid URL");
    expect(onsaved).not.toHaveBeenCalled();
    expect(get(applications)).toHaveLength(0);
  });

  it("shows None scheduled when editing an application with no upcoming round", () => {
    render(ApplicationForm, { props: { application: fakeApplication({ id: 3 }) } });
    expect(screen.getByText("None scheduled")).toBeInTheDocument();
  });

  it("Cancel calls oncancel without calling the API", async () => {
    const oncancel = vi.fn();
    render(ApplicationForm, { props: { oncancel } });
    await fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(oncancel).toHaveBeenCalledTimes(1);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
