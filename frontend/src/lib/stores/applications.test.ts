import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import * as apiModule from "../api/applications";
import { applications, loadApplications, moveApplicationStatus } from "./applications";
import { fakeApplication } from "../testing/fixtures";
import type { Application } from "../types/application";

beforeEach(() => {
  applications.set([]);
});
afterEach(() => vi.restoreAllMocks());

describe("applications store", () => {
  it("loadApplications populates the store excluding archived", async () => {
    vi.spyOn(apiModule, "listApplications").mockResolvedValue([fakeApplication({ id: 1 })]);
    await loadApplications();
    expect(get(applications)).toHaveLength(1);
    expect(apiModule.listApplications).toHaveBeenCalledWith(false);
  });

  it("moveApplicationStatus applies optimistically then syncs the server result", async () => {
    applications.set([fakeApplication({ id: 1, status: "wishlist" })]);
    let resolve!: (a: Application) => void;
    vi.spyOn(apiModule, "changeStatus").mockReturnValue(new Promise<Application>((r) => (resolve = r)));
    const p = moveApplicationStatus(1, "applied");
    expect(get(applications)[0].status).toBe("applied");
    resolve(fakeApplication({ id: 1, status: "applied", updatedAt: "2026-02-02T00:00:00Z" }));
    await p;
    expect(get(applications)[0].updatedAt).toBe("2026-02-02T00:00:00Z");
  });

  it("moveApplicationStatus reverts the optimistic update on failure", async () => {
    applications.set([fakeApplication({ id: 1, status: "wishlist" })]);
    vi.spyOn(apiModule, "changeStatus").mockRejectedValue(new Error("boom"));
    await expect(moveApplicationStatus(1, "applied")).rejects.toThrow();
    expect(get(applications)[0].status).toBe("wishlist");
  });
});
