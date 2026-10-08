import { afterEach, describe, expect, it, vi } from "vitest";
import { getBackupStatus, runBackupNow } from "./backups";

const rawStatus = {
  last_backup_at: "2026-10-08T03:00:00Z",
  last_backup_error: null,
  last_offsite_at: "2026-10-08T03:01:00Z",
  last_offsite_error: "copy uploaded, but old Drive copies were not removed: timeout",
  offsite_configured: true,
};

const status = {
  lastBackupAt: "2026-10-08T03:00:00Z",
  lastBackupError: null,
  lastOffsiteAt: "2026-10-08T03:01:00Z",
  lastOffsiteError: "copy uploaded, but old Drive copies were not removed: timeout",
  offsiteConfigured: true,
};

function mockFetch(body: unknown, status = 200) {
  const fn = vi.fn().mockImplementation(
    async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

function call(fn: ReturnType<typeof vi.fn>, i = 0) {
  const [url, init] = fn.mock.calls[i] as [string, RequestInit];
  return { url, method: init.method ?? "GET" };
}

afterEach(() => vi.unstubAllGlobals());

describe("backups api", () => {
  it("maps the status", async () => {
    const fn = mockFetch(rawStatus);
    expect(await getBackupStatus()).toEqual(status);
    expect(call(fn)).toEqual({ url: "/api/backups/status", method: "GET" });
  });

  it("Back up now posts and maps the returned status", async () => {
    const fn = mockFetch({ ...rawStatus, last_backup_error: "pg_dump exited with status 1" });
    expect(await runBackupNow()).toEqual({ ...status, lastBackupError: "pg_dump exited with status 1" });
    expect(call(fn)).toEqual({ url: "/api/backups/run", method: "POST" });
  });

  it("reports a running backup as a 409 ApiError", async () => {
    mockFetch({ detail: "a backup is already running" }, 409);
    await expect(runBackupNow()).rejects.toMatchObject({ status: 409, message: "a backup is already running" });
  });
});
