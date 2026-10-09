import { fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fakeRoundListItem } from "../../testing/fixtures";

vi.mock("../../api/interviews", () => ({ listRounds: vi.fn() }));

import { listRounds } from "../../api/interviews";
import UpcomingInterviews from "./UpcomingInterviews.svelte";

const at = (day: number, hour = 10) => new Date(2026, 9, day, hour).toISOString();

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 9, 9, 9, 0));
  vi.mocked(listRounds).mockReset();
});

afterEach(() => vi.useRealTimers());

describe("UpcomingInterviews widget", () => {
  it("shows scheduled rounds in the next 14 days, soonest first, with countdown and checklist progress", async () => {
    vi.mocked(listRounds).mockResolvedValue([
      fakeRoundListItem({ id: 1, company: "Later", scheduledAt: at(20), checklistDone: 2, checklistTotal: 6 }),
      fakeRoundListItem({ id: 2, company: "Soon", kind: "recruiter_screen", scheduledAt: at(10), checklistDone: 0, checklistTotal: 6 }),
      fakeRoundListItem({ id: 3, company: "TooFar", scheduledAt: at(24) }),
      fakeRoundListItem({ id: 4, company: "NoDate", scheduledAt: null }),
      fakeRoundListItem({ id: 5, company: "Cancelled", scheduledAt: at(11), state: "cancelled" }),
      fakeRoundListItem({ id: 6, company: "Earlier", scheduledAt: at(8), state: "done" }),
    ]);
    render(UpcomingInterviews);
    const first = await screen.findByRole("link", { name: "Soon — SWE Intern" });
    expect(listRounds).toHaveBeenCalledWith({ scope: "all" });
    expect(first.getAttribute("href")).toBe("#/interviews/2");
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toContain("Recruiter screen");
    expect(items[0].textContent).toContain("tomorrow");
    expect(items[0].textContent).toContain("Checklist 0/6");
    expect(items[1].textContent).toContain("Later");
    expect(items[1].textContent).toContain("in 11 days");
    expect(items[1].textContent).toContain("Checklist 2/6");
  });

  it("lists rounds whose thank-you is due above the upcoming ones", async () => {
    vi.mocked(listRounds).mockResolvedValue([
      fakeRoundListItem({ id: 7, company: "Soon", scheduledAt: at(12) }),
      fakeRoundListItem({ id: 8, company: "Umbrella", title: "Final", scheduledAt: at(8), state: "done", thankYouDue: true }),
    ]);
    render(UpcomingInterviews);
    const due = await screen.findByRole("link", { name: "Umbrella — Final" });
    expect(due.getAttribute("href")).toBe("#/interviews/8");
    const headings = screen.getAllByRole("heading").map((h) => h.textContent);
    expect(headings).toEqual(["Thank-you due", "Next 14 days"]);
    const links = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(links).toEqual(["#/interviews/8", "#/interviews/7"]);
  });

  it("shows an empty state linking to Interview Prep", async () => {
    vi.mocked(listRounds).mockResolvedValue([fakeRoundListItem({ scheduledAt: at(30) })]);
    render(UpcomingInterviews);
    expect(await screen.findByText(/No interviews in the next 14 days/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Interview Prep" }).getAttribute("href")).toBe("#/interviews");
  });

  it("shows a failure and retries", async () => {
    vi.mocked(listRounds).mockRejectedValueOnce(new Error("down")).mockResolvedValueOnce([fakeRoundListItem({ company: "Soon", scheduledAt: at(10) })]);
    render(UpcomingInterviews);
    await fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("link", { name: "Soon — SWE Intern" })).toBeInTheDocument();
  });
});
