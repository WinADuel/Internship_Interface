import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fakeApplication } from "../lib/testing/fixtures";

const { store, load } = vi.hoisted(() => ({ store: { current: null as any }, load: vi.fn() }));
vi.mock("../lib/stores/applications", async () => {
  const { writable } = await import("svelte/store");
  store.current = writable([]);
  return {
    applications: store.current,
    loadApplications: load,
    moveApplicationStatus: vi.fn(),
    upsertApplication: vi.fn(),
    archiveAndRemoveApplication: vi.fn(),
  };
});
vi.mock("../lib/api/applications", () => ({ getStatusHistory: vi.fn().mockResolvedValue([]) }));
vi.mock("../lib/stores/toast", () => ({ showToast: vi.fn() }));
vi.mock("../lib/api/interviews", () => ({ listRounds: vi.fn().mockResolvedValue([]) }));
vi.mock("../lib/api/contacts", () => ({ listContacts: vi.fn().mockResolvedValue([]) }));
vi.mock("../lib/api/email", () => ({ listSuggestions: vi.fn().mockResolvedValue([]) }));

import { listSuggestions } from "../lib/api/email";
import Applications from "./Applications.svelte";

describe("Applications route", () => {
  beforeEach(() => {
    load.mockReset().mockResolvedValue(undefined);
    store.current.set([fakeApplication({ id: 3, company: "Initech", roleTitle: "Intern" })]);
  });

  it("loads applications on mount", () => {
    render(Applications);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("opens the detail panel on card click and closes on Escape", async () => {
    render(Applications);
    expect(screen.queryByLabelText("Application details")).toBeNull();
    await fireEvent.click(screen.getByText("Initech"));
    expect(screen.getByLabelText("Application details")).toBeTruthy();
    await fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByLabelText("Application details")).toBeNull();
  });

  it("shows the Interviews section above Contacts in the panel, with the next interview", async () => {
    store.current.set([
      fakeApplication({ id: 3, company: "Initech", roleTitle: "Intern", interviewDatetime: "2026-10-12T15:00:00Z" }),
    ]);
    render(Applications);
    await fireEvent.click(screen.getByText("Initech"));
    const interviews = screen.getByRole("region", { name: "Interviews" });
    const contacts = screen.getByRole("region", { name: "Contacts" });
    expect(interviews.compareDocumentPosition(contacts) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("Next interview").nextElementSibling?.textContent).toBe(
      new Date("2026-10-12T15:00:00Z").toLocaleString(),
    );
    expect(await screen.findByText("No interview rounds yet.")).toBeInTheDocument();
  });

  it("lists the application's emails in the panel, between Interviews and Contacts", async () => {
    render(Applications);
    await fireEvent.click(screen.getByText("Initech"));
    const interviews = screen.getByRole("region", { name: "Interviews" });
    const email = screen.getByRole("region", { name: "Email" });
    const contacts = screen.getByRole("region", { name: "Contacts" });
    expect(interviews.compareDocumentPosition(email) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(email.compareDocumentPosition(contacts) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(await screen.findByText("No emails matched to this application yet.")).toBeInTheDocument();
    expect(listSuggestions).toHaveBeenCalledWith({ state: "all", applicationId: 3, limit: 50 });
  });
});
