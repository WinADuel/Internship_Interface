import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { applications } from "../../stores/applications";
import { fakeApplication } from "../../testing/fixtures";

vi.mock("../../api/applications", async (orig) => {
  const actual = await orig<typeof import("../../api/applications")>();
  return { ...actual, getRecentActivity: vi.fn() };
});
vi.mock("../../api/contacts", () => ({ getContactActivity: vi.fn() }));
vi.mock("../../stores/toast", () => ({ showToast: vi.fn() }));

import { getRecentActivity } from "../../api/applications";
import { getContactActivity } from "../../api/contacts";
import { showToast } from "../../stores/toast";
import BucketPreview from "./BucketPreview.svelte";
import KanbanSnapshot from "./KanbanSnapshot.svelte";
import RecentActivityFeed from "./RecentActivityFeed.svelte";
import RemindersList from "./RemindersList.svelte";

describe("RecentActivityFeed", () => {
  beforeEach(() => {
    vi.mocked(getRecentActivity).mockReset();
    vi.mocked(getContactActivity).mockReset().mockResolvedValue([]);
    vi.mocked(showToast).mockReset();
  });

  it("renders creation and status-change entries without null", async () => {
    vi.mocked(getRecentActivity).mockResolvedValue([
      { applicationId: 1, company: "Acme", roleTitle: "SWE", oldStatus: null, newStatus: "wishlist", changedAt: new Date().toISOString() },
      { applicationId: 2, company: "Globex", roleTitle: "PM", oldStatus: "applied", newStatus: "phone_screen", changedAt: new Date().toISOString() },
    ]);
    const { container } = render(RecentActivityFeed);
    await screen.findByText(/Added Acme — SWE \(Wishlist\)/);
    expect(screen.getByText(/Moved Globex — PM to Phone screen/)).toBeTruthy();
    expect(container.textContent).not.toContain("null");
  });

  it("merges contact activity into the feed", async () => {
    const t = Date.now();
    vi.mocked(getRecentActivity).mockResolvedValue([
      { applicationId: 1, company: "Acme", roleTitle: "SWE", oldStatus: "wishlist", newStatus: "applied", changedAt: new Date(t - 60_000).toISOString() },
    ]);
    vi.mocked(getContactActivity).mockResolvedValue([
      { contactId: 4, name: "Jane", organization: "MIT", kind: "professor", oldStatus: "to_contact", newStatus: "sent", changedAt: new Date(t).toISOString() },
    ]);
    const { container } = render(RecentActivityFeed);
    await screen.findByText(/Jane \(MIT\): Sent/);
    const items = Array.from(container.querySelectorAll("li")).map((li) => li.textContent ?? "");
    expect(items[0]).toContain("Jane (MIT)");
    expect(items[1]).toContain("Moved Acme — SWE to Applied");
    expect(getContactActivity).toHaveBeenCalledWith(5);
  });

  it("uses company wording for company contacts and still shows one feed when the other fails", async () => {
    vi.mocked(getRecentActivity).mockRejectedValue(new Error("boom"));
    vi.mocked(getContactActivity).mockResolvedValue([
      { contactId: 5, name: "Sam", organization: "Acme", kind: "company", oldStatus: "replied", newStatus: "accepted", changedAt: new Date().toISOString() },
    ]);
    render(RecentActivityFeed);
    await screen.findByText(/Sam \(Acme\): Positive \(referral\/interview\)/);
    expect(showToast).toHaveBeenCalledWith("Couldn't load recent activity.");
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

  describe("RemindersList overdue group", () => {
    const FUTURE = new Date(Date.now() + 3 * 86_400_000);
    const iso = (d: Date) =>
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const PAST = new Date(Date.now() - 3 * 86_400_000);

    it("lists overdue follow-ups under an Overdue heading above Upcoming", () => {
      applications.set([
        fakeApplication({ id: 1, company: "Late Co", followUpDate: iso(PAST), status: "applied" }),
        fakeApplication({ id: 2, company: "Soon Co", followUpDate: iso(FUTURE), status: "applied" }),
      ]);
      render(RemindersList);
      const overdue = screen.getByRole("heading", { name: "Overdue" });
      const upcoming = screen.getByRole("heading", { name: "Upcoming" });
      expect(overdue.compareDocumentPosition(upcoming) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      const late = screen.getByText(/Late Co/);
      const soon = screen.getByText(/Soon Co/);
      expect(overdue.compareDocumentPosition(late) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(upcoming.compareDocumentPosition(late) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
      expect(upcoming.compareDocumentPosition(soon) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it("shows overdue items even when nothing is upcoming, and keeps the empty message for Upcoming", () => {
      applications.set([fakeApplication({ id: 1, company: "Late Co", followUpDate: iso(PAST) })]);
      render(RemindersList);
      expect(screen.getByText(/Late Co/)).toBeTruthy();
      expect(screen.getByText("No upcoming reminders.")).toBeTruthy();
    });

    it("has no Overdue heading when nothing is overdue", () => {
      applications.set([fakeApplication({ id: 2, company: "Soon Co", followUpDate: iso(FUTURE) })]);
      render(RemindersList);
      expect(screen.queryByRole("heading", { name: "Overdue" })).toBeNull();
    });

    it("does not list overdue follow-ups of offers or rejections", () => {
      applications.set([fakeApplication({ id: 1, company: "Done Co", followUpDate: iso(PAST), status: "rejected" })]);
      render(RemindersList);
      expect(screen.queryByText(/Done Co/)).toBeNull();
    });
  });
});
