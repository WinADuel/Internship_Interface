import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("svelte-spa-router", () => ({ push }));
vi.mock("../lib/api/interviews", () => ({ listRounds: vi.fn(), createRound: vi.fn(), updateRound: vi.fn() }));
vi.mock("../lib/api/stories", () => ({ listStories: vi.fn(), createStory: vi.fn(), updateStory: vi.fn() }));
vi.mock("../lib/stores/applications", async () => {
  const { writable } = await import("svelte/store");
  return { applications: writable([]), loadApplications: vi.fn().mockResolvedValue(undefined) };
});

import { createRound, listRounds } from "../lib/api/interviews";
import { createStory, listStories, updateStory } from "../lib/api/stories";
import { applications } from "../lib/stores/applications";
import { fakeApplication, fakeRound, fakeRoundListItem, fakeStory } from "../lib/testing/fixtures";
import Interviews from "./Interviews.svelte";

const at = (day: number, hour = 10) => new Date(2026, 9, day, hour).toISOString();

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 9, 9, 9, 0));
  push.mockReset();
  applications.set([fakeApplication({ id: 9, company: "Globex", roleTitle: "Data Intern" })]);
  vi.mocked(listRounds).mockReset().mockImplementation(async ({ scope } = {}) =>
    scope === "past"
      ? [
          fakeRoundListItem({ id: 20, company: "Initech", scheduledAt: at(1), state: "done", outcome: "rejected" }),
          fakeRoundListItem({ id: 21, company: "Umbrella", scheduledAt: at(7), state: "done", outcome: "waiting", thankYouDue: true }),
        ]
      : [
          fakeRoundListItem({ id: 10, company: "NoDate", scheduledAt: null }),
          fakeRoundListItem({ id: 11, company: "Later", scheduledAt: at(16), checklistDone: 1, checklistTotal: 6 }),
          fakeRoundListItem({ id: 12, company: "Soon", kind: "recruiter_screen", scheduledAt: at(11), checklistDone: 6, checklistTotal: 6 }),
        ],
  );
  vi.mocked(listStories).mockReset().mockResolvedValue([
    fakeStory({ id: 1, title: "Outage at 2am", tags: ["ownership"], situation: "Pager went off" }),
    fakeStory({ id: 2, title: "Team conflict", tags: ["conflict", "teamwork"] }),
  ]);
});

afterEach(() => vi.useRealTimers());

describe("Interview Prep page", () => {
  it("has Upcoming, Past and Story bank tabs with Upcoming open", async () => {
    render(Interviews);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.textContent?.trim())).toEqual(["Upcoming", "Past", "Story bank"]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Upcoming" })).toBeInTheDocument();
    await screen.findByText(/Soon —/);
    expect(listRounds).toHaveBeenCalledWith({ scope: "upcoming" });
  });

  it("lists upcoming rounds soonest first with countdown and checklist progress, undated last", async () => {
    render(Interviews);
    await screen.findByText(/Soon —/);
    const links = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(links).toEqual(["#/interviews/12", "#/interviews/11", "#/interviews/10"]);
    const items = screen.getAllByRole("listitem");
    expect(items[0].textContent).toContain("Recruiter screen");
    expect(items[0].textContent).toContain("in 2 days");
    expect(items[0].textContent).toContain("Checklist 6/6");
    expect(items[1].textContent).toContain("in 7 days");
    expect(items[1].textContent).toContain("Checklist 1/6");
    expect(screen.getByRole("heading", { name: "Not scheduled yet" })).toBeInTheDocument();
    expect(items[2].textContent).not.toContain("in ");
  });

  it("shows past rounds newest first with outcome and a thank-you-due flag", async () => {
    render(Interviews);
    await fireEvent.click(screen.getByRole("tab", { name: "Past" }));
    await screen.findByText(/Umbrella —/);
    expect(listRounds).toHaveBeenCalledWith({ scope: "past" });
    const items = screen.getAllByRole("listitem");
    expect(items[0].textContent).toContain("Umbrella");
    expect(items[0].textContent).toContain("Waiting to hear");
    expect(items[0].textContent).toContain("Thank-you due");
    expect(items[1].textContent).toContain("Rejected");
    expect(items[1].textContent).not.toContain("Thank-you due");
  });

  it("shows empty and error states", async () => {
    vi.mocked(listRounds).mockResolvedValueOnce([]);
    render(Interviews);
    expect(await screen.findByText(/No upcoming interviews/)).toBeInTheDocument();
  });

  it("retries after a failed load", async () => {
    vi.mocked(listRounds).mockRejectedValueOnce(new Error("down"));
    render(Interviews);
    await fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByText(/Soon —/)).toBeInTheDocument();
  });

  it("adds a round for a chosen application and opens its prep page", async () => {
    vi.mocked(createRound).mockResolvedValue(fakeRound({ id: 33, applicationId: 9 }));
    render(Interviews);
    await fireEvent.click(screen.getByRole("button", { name: "Add round" }));
    const form = screen.getByRole("form", { name: "New round" });
    await fireEvent.submit(form);
    expect(within(form).getByRole("alert").textContent).toBe("Choose the application.");
    await fireEvent.change(within(form).getByLabelText("Application"), { target: { value: "9" } });
    await fireEvent.change(within(form).getByLabelText("Kind"), { target: { value: "technical" } });
    await fireEvent.input(within(form).getByLabelText("Date and time"), { target: { value: "2026-10-12T14:30" } });
    await fireEvent.input(within(form).getByLabelText("Duration (minutes)"), { target: { value: "45" } });
    await fireEvent.change(within(form).getByLabelText("Format"), { target: { value: "video" } });
    await fireEvent.submit(form);
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith("/interviews/33"));
    expect(createRound).toHaveBeenCalledWith({
      applicationId: 9,
      kind: "technical",
      title: null,
      scheduledAt: new Date(2026, 9, 12, 14, 30).toISOString(),
      durationMinutes: 45,
      format: "video",
      location: null,
      interviewers: null,
    });
  });

  it("rejects a duration out of range", async () => {
    render(Interviews);
    await fireEvent.click(screen.getByRole("button", { name: "Add round" }));
    const form = screen.getByRole("form", { name: "New round" });
    await fireEvent.change(within(form).getByLabelText("Application"), { target: { value: "9" } });
    await fireEvent.input(within(form).getByLabelText("Duration (minutes)"), { target: { value: "2" } });
    await fireEvent.submit(form);
    expect(within(form).getByRole("alert").textContent).toMatch(/5 to 600/);
    expect(createRound).not.toHaveBeenCalled();
  });
});

describe("Story bank", () => {
  async function openBank() {
    render(Interviews);
    await fireEvent.click(screen.getByRole("tab", { name: "Story bank" }));
    await screen.findByText("Outage at 2am");
  }

  it("lists stories and filters by tag", async () => {
    await openBank();
    expect(screen.queryByRole("button", { name: "Add round" })).toBeNull();
    const select = screen.getByLabelText("Tag") as HTMLSelectElement;
    expect([...select.options].map((o) => o.value)).toEqual(["", "conflict", "ownership", "teamwork"]);
    await fireEvent.change(select, { target: { value: "conflict" } });
    expect(screen.queryByText("Outage at 2am")).toBeNull();
    expect(screen.getByText("Team conflict")).toBeInTheDocument();
  });

  it("adds a story with STAR fields and tags", async () => {
    vi.mocked(createStory).mockResolvedValue(fakeStory({ id: 3, title: "A new one", tags: ["failure"] }));
    await openBank();
    await fireEvent.click(screen.getByRole("button", { name: "Add story" }));
    const form = screen.getByRole("form", { name: "New story" });
    await fireEvent.submit(form);
    expect(within(form).getByRole("alert").textContent).toBe("Give the story a title.");
    await fireEvent.input(within(form).getByLabelText("Title"), { target: { value: " A new one " } });
    await fireEvent.input(within(form).getByLabelText("Situation"), { target: { value: "Deadline" } });
    await fireEvent.input(within(form).getByLabelText("Result"), { target: { value: "Shipped" } });
    await fireEvent.input(within(form).getByLabelText("Tags"), { target: { value: "failure" } });
    await fireEvent.submit(form);
    expect(createStory).toHaveBeenCalledWith({
      title: "A new one", situation: "Deadline", task: null, action: null, result: "Shipped", tags: ["failure"],
    });
    expect(await screen.findByText("A new one")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "New story" })).toBeNull();
  });

  it("edits a story", async () => {
    vi.mocked(updateStory).mockResolvedValue(fakeStory({ id: 1, title: "Outage, retold", tags: ["ownership"] }));
    await openBank();
    await fireEvent.click(screen.getByText("Outage at 2am"));
    expect(screen.getByText("Pager went off")).toBeInTheDocument();
    await fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
    const form = screen.getByRole("form", { name: "Edit story" });
    expect((within(form).getByLabelText("Situation") as HTMLTextAreaElement).value).toBe("Pager went off");
    await fireEvent.input(within(form).getByLabelText("Title"), { target: { value: "Outage, retold" } });
    await fireEvent.submit(form);
    expect(updateStory).toHaveBeenCalledWith(1, expect.objectContaining({ title: "Outage, retold", situation: "Pager went off", tags: ["ownership"] }));
    expect(await screen.findByText("Outage, retold")).toBeInTheDocument();
  });

  it("archives a story and shows archived ones on request", async () => {
    vi.mocked(updateStory).mockResolvedValue(fakeStory({ id: 1, title: "Outage at 2am", archived: true }));
    await openBank();
    await fireEvent.click(screen.getAllByRole("button", { name: "Archive" })[0]);
    expect(updateStory).toHaveBeenCalledWith(1, { archived: true });
    await vi.waitFor(() => expect(screen.queryByText("Outage at 2am")).toBeNull());
    vi.mocked(listStories).mockResolvedValue([fakeStory({ id: 1, title: "Outage at 2am", archived: true })]);
    await fireEvent.click(screen.getByLabelText("Show archived"));
    expect(listStories).toHaveBeenLastCalledWith({ includeArchived: true });
    expect(await screen.findByText("Outage at 2am")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restore" })).toBeInTheDocument();
  });

  it("renders story text as plain text", async () => {
    vi.mocked(listStories).mockResolvedValue([fakeStory({ title: "<img src=x onerror=alert(1)>" })]);
    render(Interviews);
    await fireEvent.click(screen.getByRole("tab", { name: "Story bank" }));
    expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });
});
