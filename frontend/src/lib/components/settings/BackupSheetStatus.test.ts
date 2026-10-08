import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/settings", () => ({ syncSheetNow: vi.fn() }));
vi.mock("../../stores/toast", () => ({ showToast: vi.fn() }));

import { syncSheetNow } from "../../api/settings";
import { showToast } from "../../stores/toast";
import BackupSheetStatus from "./BackupSheetStatus.svelte";

const base = { backupSheetId: null, lastSheetSyncAt: null, lastSheetSyncError: null };

beforeEach(() => vi.mocked(syncSheetNow).mockReset());

describe("BackupSheetStatus", () => {
  it("links to the sheet and shows the last sync time", () => {
    render(BackupSheetStatus, { status: { ...base, backupSheetId: "abc123", lastSheetSyncAt: "2026-10-08T07:00:00Z" } });
    const link = screen.getByRole("link", { name: "Open backup sheet" });
    expect(link.getAttribute("href")).toBe("https://docs.google.com/spreadsheets/d/abc123");
    expect(screen.getByText(new Date("2026-10-08T07:00:00Z").toLocaleString(), { exact: false })).toBeTruthy();
    expect(screen.queryByText(/Last sync failed/)).toBeNull();
  });

  it("highlights an error and offers Connect Google when Google isn't connected", () => {
    render(BackupSheetStatus, { status: { ...base, lastSheetSyncError: "google not connected" } });
    expect(screen.getByText(/Last sync failed/).textContent).toContain("google not connected");
    // A stored error is shown, not re-announced on every visit.
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("link", { name: "Connect Google" }).getAttribute("href")).toBe("/api/docs/google/authorize");
    expect(screen.queryByRole("link", { name: "Open backup sheet" })).toBeNull();
  });

  it("also offers Connect Google when the error asks to reconnect", () => {
    render(BackupSheetStatus, {
      status: { ...base, lastSheetSyncError:
        "sheet sync failed: sheets update rejected (status 403); reconnect Google to grant the drive.file permission" },
    });
    expect(screen.getByRole("link", { name: "Connect Google" })).toBeTruthy();
  });

  it("Sync now calls the API and shows the new result", async () => {
    vi.mocked(syncSheetNow).mockResolvedValue({
      ok: true, lastSheetSyncAt: "2026-10-08T12:00:00Z", lastSheetSyncError: null,
      sheetUrl: "https://docs.google.com/spreadsheets/d/new1",
    });
    render(BackupSheetStatus, { status: { ...base, lastSheetSyncError: "boom" } });
    await fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
    await vi.waitFor(() => expect(screen.queryByText(/Last sync failed/)).toBeNull());
    expect(screen.getByRole("status").textContent).toBe("Backup sheet synced.");
    expect(syncSheetNow).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("link", { name: "Open backup sheet" }).getAttribute("href")).toBe(
      "https://docs.google.com/spreadsheets/d/new1",
    );
  });

  it("says so when a sync didn't complete without recording an error", async () => {
    vi.mocked(syncSheetNow).mockResolvedValue({ ok: false, lastSheetSyncAt: null, lastSheetSyncError: null, sheetUrl: null });
    render(BackupSheetStatus, { status: base });
    await fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
    await vi.waitFor(() => expect(screen.getByRole("status").textContent).toBe("Sync didn't complete."));
  });

  it("a failed request shows a toast", async () => {
    vi.mocked(syncSheetNow).mockRejectedValueOnce(new Error("offline"));
    render(BackupSheetStatus, { status: base });
    await fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith("Couldn't sync the backup sheet."));
  });
});
