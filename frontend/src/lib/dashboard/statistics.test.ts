import { describe, expect, it } from "vitest";
import { fakeApplication, fakeRoundListItem } from "../testing/fixtures";
import { applicationStats, scheduledInterviews } from "./statistics";

const now = new Date(2026, 10, 6, 12, 0);

describe("applicationStats", () => {
  it("counts sent applications, the last 7 days, and the share that heard back", () => {
    const apps = [
      fakeApplication({ id: 1, status: "wishlist", dateApplied: null }),
      fakeApplication({ id: 2, status: "applied", dateApplied: "2026-11-04" }),
      fakeApplication({ id: 3, status: "applied", dateApplied: "2026-10-01" }),
      fakeApplication({ id: 4, status: "interview", dateApplied: "2026-10-20" }),
      fakeApplication({ id: 5, status: "rejected", dateApplied: "2026-11-01" }),
    ];
    expect(applicationStats(apps, now)).toEqual({ sent: 4, sentLast7Days: 2, heardBack: 2, responseRate: 50 });
  });

  it("has no response rate before anything is sent", () => {
    expect(applicationStats([fakeApplication({ status: "wishlist" })], now).responseRate).toBeNull();
  });
});

describe("scheduledInterviews", () => {
  it("keeps scheduled rounds still ahead, soonest first", () => {
    const rounds = [
      fakeRoundListItem({ id: 1, state: "scheduled", scheduledAt: "2026-11-20T17:00:00Z" }),
      fakeRoundListItem({ id: 2, state: "scheduled", scheduledAt: "2026-11-10T17:00:00Z" }),
      fakeRoundListItem({ id: 3, state: "scheduled", scheduledAt: "2026-11-01T17:00:00Z" }),
      fakeRoundListItem({ id: 4, state: "done", scheduledAt: "2026-11-12T17:00:00Z" }),
      fakeRoundListItem({ id: 5, state: "scheduled", scheduledAt: null }),
    ];
    expect(scheduledInterviews(rounds, now).map((r) => r.id)).toEqual([2, 1]);
  });
});
