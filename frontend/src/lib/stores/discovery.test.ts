import { get } from "svelte/store";
import { afterEach, describe, expect, it, vi } from "vitest";
import { discoveryStatus, refreshDiscoveryStatus } from "./discovery";
import { ApiError } from "../api/client";
import * as api from "../api/discovery";

const status = { lastScanAt: "2026-10-08T10:00:00Z", lastScanError: null, scanning: false, inboxCount: 4 };

afterEach(() => {
  vi.restoreAllMocks();
  discoveryStatus.set(null);
});

describe("discovery status store", () => {
  it("starts empty", () => {
    expect(get(discoveryStatus)).toBeNull();
  });

  it("refresh stores and returns the latest status", async () => {
    vi.spyOn(api, "getScanStatus").mockResolvedValue(status);
    expect(await refreshDiscoveryStatus()).toEqual(status);
    expect(get(discoveryStatus)).toEqual(status);
  });

  it("an API failure keeps the previous value, returns null and does not throw", async () => {
    discoveryStatus.set(status);
    vi.spyOn(api, "getScanStatus").mockRejectedValue(new ApiError(500, "boom"));
    await expect(refreshDiscoveryStatus()).resolves.toBeNull();
    expect(get(discoveryStatus)).toEqual(status);
  });

  it("a network failure keeps the previous value too", async () => {
    vi.spyOn(api, "getScanStatus").mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(refreshDiscoveryStatus()).resolves.toBeNull();
    expect(get(discoveryStatus)).toBeNull();
  });
});
