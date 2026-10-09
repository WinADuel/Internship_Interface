import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { get } from "svelte/store";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/interviews", () => ({ listRounds: vi.fn(), createRound: vi.fn(), updateRound: vi.fn() }));
vi.mock("../../api/applications", () => ({ getApplication: vi.fn(), changeStatus: vi.fn() }));

import { changeStatus, getApplication } from "../../api/applications";
import { createRound, listRounds } from "../../api/interviews";
import { applications } from "../../stores/applications";
import { fakeApplication, fakeRoundDetail, fakeRoundListItem } from "../../testing/fixtures";
import ApplicationInterviews from "./ApplicationInterviews.svelte";

const app = fakeApplication({ id: 9, company: "Globex", status: "applied" });

beforeEach(() => {
  applications.set([app]);
  vi.mocked(listRounds).mockReset().mockResolvedValue([
    fakeRoundListItem({ id: 2, applicationId: 9, kind: "behavioral", scheduledAt: null }),
    fakeRoundListItem({ id: 1, applicationId: 9, title: "Phone screen", scheduledAt: "2026-10-12T15:00:00Z", state: "done" }),
  ]);
  vi.mocked(createRound).mockReset();
  vi.mocked(getApplication).mockReset();
  vi.mocked(changeStatus).mockReset();
});

describe("Application panel Interviews section", () => {
  it("lists the application's rounds by date with state, linking to each prep page", async () => {
    render(ApplicationInterviews, { props: { application: app } });
    const first = await screen.findByRole("link", { name: "Phone screen" });
    expect(listRounds).toHaveBeenCalledWith({ applicationId: 9, scope: "all" });
    expect(first.getAttribute("href")).toBe("#/interviews/1");
    const items = screen.getAllByRole("listitem");
    expect(items[0].textContent).toContain("Done");
    expect(items[1].textContent).toContain("Behavioral");
    expect(items[1].textContent).toContain("Not scheduled");
  });

  it("adds a round and refreshes the application's next interview", async () => {
    vi.mocked(createRound).mockResolvedValue(fakeRoundDetail({ id: 3, applicationId: 9 }));
    vi.mocked(getApplication).mockResolvedValue({ ...app, interviewDatetime: "2026-10-20T15:00:00Z" });
    render(ApplicationInterviews, { props: { application: app } });
    await screen.findByRole("link", { name: "Phone screen" });
    await fireEvent.click(screen.getByRole("button", { name: "Add round" }));
    const form = screen.getByRole("form", { name: "New round" });
    expect(within(form).queryByLabelText("Application")).toBeNull();
    await fireEvent.input(within(form).getByLabelText("Date and time"), { target: { value: "2026-10-20T11:00" } });
    await fireEvent.submit(form);
    await vi.waitFor(() => expect(get(applications)[0].interviewDatetime).toBe("2026-10-20T15:00:00Z"));
    expect(createRound).toHaveBeenCalledWith(expect.objectContaining({ applicationId: 9, scheduledAt: new Date(2026, 9, 20, 11).toISOString() }));
    expect(listRounds).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("form", { name: "New round" })).toBeNull();
  });

  it("offers Move to Interview while the status is earlier than interview", async () => {
    vi.mocked(changeStatus).mockResolvedValue({ ...app, status: "interview" });
    render(ApplicationInterviews, { props: { application: app } });
    await fireEvent.click(await screen.findByRole("button", { name: "Move to Interview" }));
    expect(changeStatus).toHaveBeenCalledWith(9, "interview");
    await vi.waitFor(() => expect(get(applications)[0].status).toBe("interview"));
  });

  it("doesn't offer Move to Interview without rounds or once past it", async () => {
    vi.mocked(listRounds).mockResolvedValue([]);
    const view = render(ApplicationInterviews, { props: { application: app } });
    expect(await screen.findByText("No interview rounds yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Move to Interview" })).toBeNull();
    view.unmount();
    vi.mocked(listRounds).mockResolvedValue([fakeRoundListItem({ applicationId: 9 })]);
    render(ApplicationInterviews, { props: { application: { ...app, status: "offer" } } });
    await screen.findByRole("listitem");
    expect(screen.queryByRole("button", { name: "Move to Interview" })).toBeNull();
  });
});
