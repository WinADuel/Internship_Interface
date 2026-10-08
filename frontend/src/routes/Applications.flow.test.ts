import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { get } from "svelte/store";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as storeModule from "../lib/stores/applications";
import { applications } from "../lib/stores/applications";
import { toasts } from "../lib/stores/toast";
import Applications from "./Applications.svelte";

function raw(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    company: "Initech",
    role_title: "Intern",
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

type Handler = (init: RequestInit) => { status?: number; body: unknown };
let routes: Record<string, Handler>;
let calls: Array<{ method: string; path: string; body: any }>;

beforeEach(() => {
  applications.set([]);
  toasts.set([]);
  calls = [];
  routes = {};
  globalThis.fetch = vi.fn(async (path: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    calls.push({ method, path, body: init.body ? JSON.parse(init.body as string) : undefined });
    const handler = routes[`${method} ${path}`];
    const { status = 200, body } = handler ? handler(init) : { status: 404, body: { detail: "not found" } };
    return { ok: status < 400, status, json: async () => body } as Response;
  }) as unknown as typeof fetch;
  routes["GET /api/applications?include_archived=false"] = () => ({ body: [raw()] });
  routes["GET /api/applications/1/history"] = () => ({ body: [] });
  // The detail panel's Contacts section (Phase 1b).
  for (const id of [1, 2]) routes[`GET /api/contacts?kind=company&application_id=${id}`] = () => ({ body: [] });
});
afterEach(() => vi.restoreAllMocks());

const board = () => screen.getByLabelText("Wishlist").parentElement as HTMLElement;

describe("Applications route: create, edit, status, archive", () => {
  it("New application opens the form, and the created application lands on the board", async () => {
    routes["POST /api/applications"] = () => ({
      body: raw({ id: 2, company: "Globex", role_title: "Data Intern", status: "applied" }),
    });
    routes["GET /api/applications/2/history"] = () => ({ body: [] });
    render(Applications);
    await screen.findByText("Initech");

    await fireEvent.click(screen.getByRole("button", { name: "New application" }));
    await fireEvent.input(screen.getByLabelText("Company"), { target: { value: "Globex" } });
    await fireEvent.input(screen.getByLabelText("Role title"), { target: { value: "Data Intern" } });
    await fireEvent.change(screen.getByLabelText("Status"), { target: { value: "applied" } });
    await fireEvent.submit(screen.getByRole("form", { name: "Application" }));

    await within(screen.getByLabelText("Applied")).findByText("Globex");
    expect(get(applications).map((a) => a.company)).toEqual(["Initech", "Globex"]);
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
      company: "Globex",
      role_title: "Data Intern",
      status: "applied",
    });
  });

  it("tapping a card opens the panel, whose status select calls moveApplicationStatus", async () => {
    const move = vi.spyOn(storeModule, "moveApplicationStatus").mockResolvedValue(undefined);
    render(Applications);
    await fireEvent.click(await screen.findByText("Initech"));
    const panel = screen.getByLabelText("Application details");
    await fireEvent.change(within(panel).getByLabelText("Status"), { target: { value: "interview" } });
    expect(move).toHaveBeenCalledWith(1, "interview");
  });

  it("a failed status change shows a toast and resets the select", async () => {
    vi.spyOn(storeModule, "moveApplicationStatus").mockRejectedValue(new Error("nope"));
    render(Applications);
    await fireEvent.click(await screen.findByText("Initech"));
    const select = within(screen.getByLabelText("Application details")).getByLabelText("Status") as HTMLSelectElement;
    await fireEvent.change(select, { target: { value: "offer" } });
    await vi.waitFor(() => expect(get(toasts).map((t) => t.text)).toEqual(["nope"]));
    expect(select.value).toBe("wishlist");
  });

  it("the real status change moves the card to the new column", async () => {
    routes["POST /api/applications/1/status"] = () => ({ body: raw({ status: "interview" }) });
    render(Applications);
    await fireEvent.click(await screen.findByText("Initech"));
    await fireEvent.change(within(screen.getByLabelText("Application details")).getByLabelText("Status"), {
      target: { value: "interview" },
    });
    await within(screen.getByLabelText("Interview")).findByText("Initech");
    expect(calls.find((c) => c.path === "/api/applications/1/status")?.body).toEqual({ new_status: "interview" });
  });

  it("Edit switches the panel to the form and saving updates the card", async () => {
    routes["PATCH /api/applications/1"] = () => ({ body: raw({ company: "Initech Global" }) });
    render(Applications);
    await fireEvent.click(await screen.findByText("Initech"));
    await fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect((screen.getByLabelText("Company") as HTMLInputElement).value).toBe("Initech");
    await fireEvent.input(screen.getByLabelText("Company"), { target: { value: "Initech Global" } });
    await fireEvent.submit(screen.getByRole("form", { name: "Application" }));
    await within(screen.getByLabelText("Wishlist")).findByText("Initech Global");
    expect(screen.queryByRole("form", { name: "Application" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Initech Global" })).toBeTruthy();
  });

  it("Archive (confirmed) archives on the server and removes the application from the board", async () => {
    routes["POST /api/applications/1/archive"] = () => ({ body: raw({ archived: true }) });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(Applications);
    await fireEvent.click(await screen.findByText("Initech"));
    await fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    await vi.waitFor(() => expect(within(board()).queryByText("Initech")).toBeNull());
    expect(calls.some((c) => c.method === "POST" && c.path === "/api/applications/1/archive")).toBe(true);
    expect(get(applications)).toHaveLength(0);
    expect(screen.queryByLabelText("Application details")).toBeNull();
  });

  it("Archive does nothing when the confirmation is declined", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(Applications);
    await fireEvent.click(await screen.findByText("Initech"));
    await fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    expect(calls.some((c) => c.path.endsWith("/archive"))).toBe(false);
    expect(get(applications)).toHaveLength(1);
  });

  it("an archive failure shows the error in a toast and keeps the card", async () => {
    routes["POST /api/applications/1/archive"] = () => ({ status: 500, body: { detail: "db down" } });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(Applications);
    await fireEvent.click(await screen.findByText("Initech"));
    await fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    await vi.waitFor(() => expect(get(toasts).map((t) => t.text)).toEqual(["db down"]));
    expect(get(applications)).toHaveLength(1);
  });

  it("renders timestamps in the viewer locale format", async () => {
    routes["GET /api/applications?include_archived=false"] = () => ({
      body: [raw({ interview_datetime: "2026-03-05T14:30:00Z", follow_up_date: "2026-03-10" })],
    });
    render(Applications);
    await fireEvent.click(await screen.findByText("Initech"));
    const panel = screen.getByLabelText("Application details");
    expect(within(panel).getByText(new Date("2026-03-05T14:30:00Z").toLocaleString())).toBeTruthy();
    expect(within(panel).getByText(new Date(2026, 2, 10).toLocaleDateString())).toBeTruthy();
    expect(within(panel).getAllByText(new Date("2026-01-01T00:00:00Z").toLocaleString()).length).toBeGreaterThan(0);
  });
});
