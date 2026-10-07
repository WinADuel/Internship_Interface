import { describe, expect, it } from "vitest";
import { fakeApplication } from "../testing/fixtures";
import { KANBAN_COLUMNS, groupByStatus } from "./grouping";

describe("groupByStatus", () => {
  it("groups applications by status and excludes archived", () => {
    const apps = [
      fakeApplication({ id: 1, status: "wishlist", archived: false }),
      fakeApplication({ id: 2, status: "applied", archived: false }),
      fakeApplication({ id: 3, status: "wishlist", archived: true }),
    ];
    const grouped = groupByStatus(apps);
    expect(grouped.wishlist.map((a) => a.id)).toEqual([1]);
    expect(grouped.applied.map((a) => a.id)).toEqual([2]);
  });

  it("returns an empty array for columns with no applications", () => {
    const grouped = groupByStatus([]);
    expect(grouped.offer).toEqual([]);
  });

  it("lists columns in spec order", () => {
    expect(KANBAN_COLUMNS).toEqual(["wishlist", "applied", "phone_screen", "interview", "offer", "rejected"]);
  });
});
