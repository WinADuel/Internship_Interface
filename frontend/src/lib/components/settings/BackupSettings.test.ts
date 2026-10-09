import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/backups", () => ({ getBackupStatus: vi.fn(), runBackupNow: vi.fn() }));
vi.mock("../../stores/toast", () => ({ showToast: vi.fn() }));

import { ApiError } from "../../api/client";
import { getBackupStatus, runBackupNow } from "../../api/backups";
import { showToast } from "../../stores/toast";
import type { BackupStatus } from "../../types/backup";
import BackupSettings from "./BackupSettings.svelte";

const HOUR = 3_600_000;
const hoursAgo = (h: number) => new Date(Date.now() - h * HOUR).toISOString();

const never: BackupStatus = {
  lastBackupAt: null,
  lastBackupError: null,
  lastOffsiteAt: null,
  lastOffsiteError: null,
  offsiteConfigured: true,
};

function status(overrides: Partial<BackupStatus> = {}): BackupStatus {
  return { ...never, ...overrides };
}

async function renderWith(s: BackupStatus) {
  vi.mocked(getBackupStatus).mockResolvedValue(s);
  const result = render(BackupSettings);
  await screen.findByText(/^Last backup:/);
  return result;
}

const backUpButton = () => screen.getByRole("button", { name: /Back up now|Backing up/ }) as HTMLButtonElement;

beforeEach(() => {
  vi.mocked(getBackupStatus).mockReset();
  vi.mocked(runBackupNow).mockReset();
  vi.mocked(showToast).mockReset();
});

describe("BackupSettings", () => {
  it("explains where backups live", async () => {
    await renderWith(never);
    expect(screen.getByText(/encrypted copy/).textContent).toContain('"Internship Tracker Backups"');
  });

  it("says when there is no backup yet", async () => {
    const { container } = await renderWith(never);
    expect(screen.getByText(/^Last backup:/).textContent).toBe("Last backup: No backup yet");
    expect(screen.getByText(/^Last off-site copy:/).textContent).toBe("Last off-site copy: none yet");
    expect(container.querySelector(".error, .warning")).toBeNull();
    expect(backUpButton().disabled).toBe(false);
  });

  it("shows the last backup and off-site copy as time ago, with the exact time on hover", async () => {
    const at = hoursAgo(2);
    const offAt = hoursAgo(3);
    const { container } = await renderWith(status({ lastBackupAt: at, lastOffsiteAt: offAt }));
    const backup = screen.getByText("2 hours ago");
    expect(backup.tagName).toBe("TIME");
    expect(backup.getAttribute("datetime")).toBe(at);
    expect(backup.getAttribute("title")).toBe(new Date(at).toLocaleString());
    expect(screen.getByText("3 hours ago").getAttribute("title")).toBe(new Date(offAt).toLocaleString());
    expect(container.querySelector(".error, .warning")).toBeNull();
    expect(screen.queryByText(/BACKUP_ENCRYPTION_KEY/)).toBeNull();
  });

  it("shows a backup error as plain text", async () => {
    const { container } = await renderWith(
      status({ lastBackupAt: hoursAgo(30), lastBackupError: "pg_dump failed: <b>disk full</b>" }),
    );
    const error = screen.getByText(/^Latest backup failed:/);
    expect(error.className).toContain("error");
    expect(error.textContent).toBe("Latest backup failed: pg_dump failed: <b>disk full</b>");
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByText("1 day ago")).toBeTruthy();
  });

  it("explains what off-site copies need when they aren't set up, instead of the stored error", async () => {
    await renderWith(status({ offsiteConfigured: false, lastOffsiteError: "set BACKUP_ENCRYPTION_KEY in .env" }));
    const hint = screen.getByText(/Off-site copies to Google Drive are off/);
    expect(hint.textContent).toContain("Google is connected");
    expect(hint.textContent).toContain("BACKUP_ENCRYPTION_KEY");
    expect(screen.queryByText(/set BACKUP_ENCRYPTION_KEY in .env/)).toBeNull();
    expect(screen.queryByText(/^Off-site copy (failed|warning)/)).toBeNull();
  });

  it("shows the backend's prune message as a warning: the copy itself reached Drive", async () => {
    const note = "copy uploaded, but old Drive copies were not removed: Drive request failed (status 500)";
    await renderWith(status({ lastOffsiteAt: hoursAgo(1), lastOffsiteError: note }));
    const warning = screen.getByText(/^Off-site copy warning:/);
    expect(warning.className).toContain("warning");
    expect(warning.className).not.toContain("error");
    expect(warning.textContent).toContain(note);
    expect(screen.queryByText(/^Off-site copy failed:/)).toBeNull();
  });

  it("shows an off-site error as a failure when there is no copy yet", async () => {
    await renderWith(status({ lastOffsiteError: "connect Google in Settings" }));
    const error = screen.getByText(/^Off-site copy failed:/);
    expect(error.className).toContain("error");
    expect(error.textContent).toBe("Off-site copy failed: connect Google in Settings");
    expect(screen.queryByText(/^Off-site copy warning:/)).toBeNull();
  });

  it("shows a failed upload as a failure even with an older copy, and says how old that copy is", async () => {
    const offAt = hoursAgo(24 * 4);
    await renderWith(status({ lastOffsiteAt: offAt, lastOffsiteError: "Drive request failed (status 503)" }));
    const error = screen.getByText(/^Off-site copy failed:/);
    expect(error.className).toContain("error");
    expect(error.textContent).toBe("Off-site copy failed: Drive request failed (status 503)");
    expect(screen.queryByText(/^Off-site copy warning:/)).toBeNull();
    expect(screen.getByText(/^Last off-site copy:/).textContent).toBe("Last off-site copy: 4 days ago");
  });

  it("disables the button and says Backing up… while a backup runs", async () => {
    let finish!: (s: BackupStatus) => void;
    vi.mocked(runBackupNow).mockReturnValue(new Promise((resolve) => (finish = resolve)));
    await renderWith(never);
    const section = screen.getByRole("region", { name: "Backups" });
    expect(section.getAttribute("aria-busy")).toBe("false");
    await fireEvent.click(backUpButton());
    expect(backUpButton().disabled).toBe(true);
    expect(backUpButton().textContent?.trim()).toBe("Backing up…");
    expect(section.getAttribute("aria-busy")).toBe("true");
    finish(status({ lastBackupAt: new Date().toISOString() }));
    await vi.waitFor(() => expect(backUpButton().disabled).toBe(false));
    expect(backUpButton().textContent?.trim()).toBe("Back up now");
    expect(section.getAttribute("aria-busy")).toBe("false");
  });

  it("Back up now updates the card from the returned status and confirms", async () => {
    vi.mocked(runBackupNow).mockResolvedValue(status({ lastBackupAt: new Date().toISOString() }));
    await renderWith(status({ lastBackupError: "pg_dump failed" }));
    expect(screen.getByRole("status").textContent).toBe("");
    await fireEvent.click(backUpButton());
    await vi.waitFor(() => expect(screen.getByText("just now")).toBeTruthy());
    expect(screen.queryByText(/^Latest backup failed:/)).toBeNull();
    expect(runBackupNow).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("status").textContent).toBe("Backup complete.");
    expect(showToast).not.toHaveBeenCalled();
  });

  it("announces the error when Back up now ran but the backup failed", async () => {
    vi.mocked(runBackupNow).mockResolvedValue(status({ lastBackupError: "pg_dump exited with status 1" }));
    await renderWith(never);
    await fireEvent.click(backUpButton());
    await vi.waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe("Backup failed: pg_dump exited with status 1"),
    );
    expect(screen.getByText(/^Latest backup failed:/).textContent).toContain("pg_dump exited with status 1");
  });

  it("says a backup is already running on 409, then shows what the server has now", async () => {
    vi.mocked(runBackupNow).mockRejectedValue(new ApiError(409, "a backup is already running"));
    await renderWith(never);
    vi.mocked(getBackupStatus).mockResolvedValue(status({ lastBackupAt: hoursAgo(0) }));
    await fireEvent.click(backUpButton());
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith("A backup is already running"));
    expect(backUpButton().disabled).toBe(false);
    await vi.waitFor(() => expect(screen.getByText("just now")).toBeTruthy());
    expect(getBackupStatus).toHaveBeenCalledTimes(2);
  });

  it("reloads the status after a 409 even when an earlier Back up now filled the card", async () => {
    vi.mocked(runBackupNow).mockResolvedValueOnce(status({ lastBackupAt: hoursAgo(3) }));
    vi.mocked(runBackupNow).mockRejectedValueOnce(new ApiError(409, "a backup is already running"));
    await renderWith(never);
    await fireEvent.click(backUpButton());
    await vi.waitFor(() => expect(screen.getByText("3 hours ago")).toBeTruthy());
    vi.mocked(getBackupStatus).mockResolvedValue(status({ lastBackupAt: hoursAgo(0) }));
    await fireEvent.click(backUpButton());
    await vi.waitFor(() => expect(screen.getByText("just now")).toBeTruthy());
  });

  it("reloads the status after a network error, quietly if that fails too", async () => {
    vi.mocked(runBackupNow).mockRejectedValue(new TypeError("Failed to fetch"));
    await renderWith(never);
    vi.mocked(getBackupStatus).mockResolvedValueOnce(status({ lastBackupAt: hoursAgo(0) }));
    await fireEvent.click(backUpButton());
    await vi.waitFor(() => expect(screen.getByText("just now")).toBeTruthy());
    expect(showToast).toHaveBeenCalledWith("Couldn't run the backup.");

    vi.mocked(getBackupStatus).mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await fireEvent.click(backUpButton());
    await vi.waitFor(() => expect(getBackupStatus).toHaveBeenCalledTimes(3));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(showToast).not.toHaveBeenCalledWith("Couldn't load the backup status.");
    expect(screen.getByText("just now")).toBeTruthy();
  });

  it("toasts other failures", async () => {
    vi.mocked(runBackupNow).mockRejectedValueOnce(new ApiError(500, "Internal Server Error"));
    vi.mocked(runBackupNow).mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await renderWith(never);
    await fireEvent.click(backUpButton());
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith("Internal Server Error"));
    await fireEvent.click(backUpButton());
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith("Couldn't run the backup."));
  });

  it("toasts when the status can't be loaded, and Back up now still fills the card", async () => {
    vi.mocked(getBackupStatus).mockRejectedValue(new TypeError("Failed to fetch"));
    vi.mocked(runBackupNow).mockResolvedValue(status({ lastBackupAt: hoursAgo(0) }));
    render(BackupSettings);
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith("Couldn't load the backup status."));
    expect(screen.getByText("Backup status unavailable.")).toBeTruthy();
    await fireEvent.click(backUpButton());
    await vi.waitFor(() => expect(screen.getByText("just now")).toBeTruthy());
    expect(screen.queryByText("Backup status unavailable.")).toBeNull();
  });

  it("a status load that fails after Back up now filled the card doesn't toast", async () => {
    let failLoad!: (err: unknown) => void;
    vi.mocked(getBackupStatus).mockReturnValue(new Promise((_, reject) => (failLoad = reject)));
    vi.mocked(runBackupNow).mockResolvedValue(status({ lastBackupAt: hoursAgo(0) }));
    render(BackupSettings);
    await fireEvent.click(backUpButton());
    await vi.waitFor(() => expect(screen.getByText("just now")).toBeTruthy());
    failLoad(new TypeError("Failed to fetch"));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(showToast).not.toHaveBeenCalled();
    expect(screen.queryByText("Backup status unavailable.")).toBeNull();
    expect(screen.getByText("just now")).toBeTruthy();
  });

  it("a status load that lands after Back up now doesn't overwrite the newer status", async () => {
    let loaded!: (s: BackupStatus) => void;
    vi.mocked(getBackupStatus).mockReturnValue(new Promise((resolve) => (loaded = resolve)));
    vi.mocked(runBackupNow).mockResolvedValue(status({ lastBackupAt: hoursAgo(0) }));
    render(BackupSettings);
    await fireEvent.click(backUpButton());
    await vi.waitFor(() => expect(screen.getByText("just now")).toBeTruthy());
    loaded(never);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByText("just now")).toBeTruthy();
    expect(screen.queryByText(/No backup yet/)).toBeNull();
  });
});
