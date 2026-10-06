import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { applications } from "../../stores/applications";
import { fakeApplication } from "../../testing/fixtures";

vi.mock("../../api/applications", async (orig) => {
  const actual = await orig<typeof import("../../api/applications")>();
  return { ...actual, getRecentActivity: vi.fn() };
});
vi.mock("../../stores/toast", () => ({ showToast: vi.fn() }));

import { getRecentActivity } from "../../api/applications";
import { showToast } from "../../stores/toast";
import BucketPreview from "./BucketPreview.svelte";
import KanbanSnapshot from "./KanbanSnapshot.svelte";
import RecentActivityFeed from "./RecentActivityFeed.svelte";
import RemindersList from "./RemindersList.svelte";

describe("RecentActivityFeed", () => {
  beforeEach(() => {
    vi.mocked(getRecentActivity).mockReset();
    vi.mocked(showToast).mockReset();
  });

  it("renders creation and status-change entries without null", async () => {
    vi.mocked(getRecentActivity).mockResolvedValue([
      { applicationId: 1, company: "Acme", roleTitle: "SWE", oldStatus: null, newStatus: "wishlist", changedAt: new Date().toISOString() },
      { applicationId: 2, company: "Globex", roleTitle: "PM", oldStatus: "applied", newStatus: "phone_screen", changedAt: new Date().toISOString() },
    ]);
    const { container } = render(RecentActivityFeed);
    await screen.findByText(/Added Acme — SWE \(Wishlist\)/);
    expect(screen.getByText(/Moved Globex to Phone screen/)).toBeTruthy();
    expect(container.textContent).not.toContain("null");
  });

  it("toasts and shows empty state when fetch fails", async () => {
    vi.mocked(getRecentActivity).mockRejectedValue(new Error("boom"));
    render(RecentActivityFeed);
    await screen.findByText("No recent activity.");
    expect(showToast).toHaveBeenCalled();
  });

  it("notifies parent when the limit changes", async () => {
    vi.mocked(getRecentActivity).mockResolvedValue([]);
    const onsettingschange = vi.fn();
    render(RecentActivityFeed, { onsettingschange });
    await waitFor(() => expect(getRecentActivity).toHaveBeenCalledWith(5));
    await fireEvent.change(screen.getByLabelText("Items to show"), { target: { value: "10" } });
    expect(onsettingschange).toHaveBeenCalledWith({ limit: 10 });
  });
});

describe("store-backed widgets", () => {
  beforeEach(() => {
    applications.set([
      fakeApplication({ id: 1, company: "A", status: "wishlist" }),
      fakeApplication({ id: 2, company: "B", status: "applied" }),
      fakeApplication({ id: 3, company: "C", status: "applied" }),
    ]);
  });

  it("BucketPreview respects limit and notifies", async () => {
    const onsettingschange = vi.fn();
    render(BucketPreview, { limit: 1, onsettingschange });
    expect(screen.getByText("+1 more")).toBeTruthy();
    await fireEvent.change(screen.getByLabelText("Items per bucket"), { target: { value: "5" } });
    expect(onsettingschange).toHaveBeenCalledWith({ limit: 5 });
  });

  it("KanbanSnapshot shows counts and hides empty columns", () => {
    render(KanbanSnapshot, { hideEmpty: true });
    expect(screen.getByText("Applied")).toBeTruthy();
    expect(screen.queryByText("Offer")).toBeNull();
  });

  it("RemindersList shows empty state and notifies on change", async () => {
    const onsettingschange = vi.fn();
    render(RemindersList, { onsettingschange });
    expect(screen.getByText("No upcoming reminders.")).toBeTruthy();
    await fireEvent.change(screen.getByLabelText("Days ahead"), { target: { value: "30" } });
    expect(onsettingschange).toHaveBeenCalledWith({ withinDays: 30 });
  });
});
