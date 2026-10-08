import { fireEvent, render, screen } from "@testing-library/svelte";
import { get } from "svelte/store";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/discovery", () => ({ getScanStatus: vi.fn(), startScan: vi.fn() }));
vi.mock("../../stores/toast", () => ({ showToast: vi.fn() }));

import { ApiError } from "../../api/client";
import { getScanStatus, startScan } from "../../api/discovery";
import { discoveryStatus } from "../../stores/discovery";
import { showToast } from "../../stores/toast";
import { fakeScanStatus } from "../../testing/fixtures";
import ScanHeader from "./ScanHeader.svelte";

const LAST = "2026-10-08T10:00:00Z";

beforeEach(() => {
  discoveryStatus.set(null);
  vi.mocked(getScanStatus).mockReset().mockResolvedValue(fakeScanStatus({ lastScanAt: LAST }));
  vi.mocked(startScan).mockReset();
  vi.mocked(showToast).mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("ScanHeader", () => {
  it("refreshes the status on mount and shows the last scan time", async () => {
    render(ScanHeader);
    expect(await screen.findByText(`Last scan: ${new Date(LAST).toLocaleString()}`)).toBeInTheDocument();
    expect(getScanStatus).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Scan now" })).toBeEnabled();
  });

  it("says when there has been no scan yet", async () => {
    vi.mocked(getScanStatus).mockResolvedValue(fakeScanStatus());
    render(ScanHeader);
    expect(await screen.findByText("No scan yet.")).toBeInTheDocument();
  });

  it("lists each source error from the last scan as plain text", async () => {
    vi.mocked(getScanStatus).mockResolvedValue(
      fakeScanStatus({ lastScanAt: LAST, lastScanError: "simplify: timeout; Stripe (greenhouse): <b>HTTP 500</b>" }),
    );
    const { container } = render(ScanHeader);
    expect(await screen.findByText("simplify: timeout")).toBeInTheDocument();
    expect(screen.getByText("Stripe (greenhouse): <b>HTTP 500</b>")).toBeInTheDocument();
    expect(container.querySelector("b")).toBeNull();
  });

  it("Scan now starts a scan and is disabled while it runs", async () => {
    vi.mocked(startScan).mockResolvedValue({ started: true });
    render(ScanHeader);
    await screen.findByText(/Last scan:/);
    await fireEvent.click(screen.getByRole("button", { name: "Scan now" }));
    expect(startScan).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Scanning…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Scan now" })).toBeDisabled();
    expect(get(discoveryStatus)?.scanning).toBe(true);
  });

  it("a 409 says a scan is already running and follows it", async () => {
    vi.mocked(startScan).mockRejectedValue(new ApiError(409, "already scanning"));
    render(ScanHeader);
    await screen.findByText(/Last scan:/);
    await fireEvent.click(screen.getByRole("button", { name: "Scan now" }));
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith("A scan is already running", "info"));
    expect(screen.getByRole("button", { name: "Scan now" })).toBeDisabled();
  });

  it("any other failure shows the error and re-enables the button", async () => {
    vi.mocked(startScan).mockRejectedValue(new ApiError(500, "boom"));
    render(ScanHeader);
    await screen.findByText(/Last scan:/);
    await fireEvent.click(screen.getByRole("button", { name: "Scan now" }));
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith("Couldn't start a scan: boom"));
    expect(screen.getByRole("button", { name: "Scan now" })).toBeEnabled();
  });

  it("polls every 5 s while scanning and reports once when the scan finishes", async () => {
    vi.useFakeTimers();
    vi.mocked(getScanStatus)
      .mockResolvedValueOnce(fakeScanStatus({ scanning: true }))
      .mockResolvedValueOnce(fakeScanStatus({ scanning: true }))
      .mockResolvedValue(fakeScanStatus({ lastScanAt: LAST, inboxCount: 7 }));
    const onfinished = vi.fn();
    render(ScanHeader, { onfinished });
    await vi.advanceTimersByTimeAsync(0);
    expect(getScanStatus).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Scanning…")).toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(4999);
    expect(getScanStatus).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(getScanStatus).toHaveBeenCalledTimes(2);
    expect(onfinished).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(5000);
    expect(getScanStatus).toHaveBeenCalledTimes(3);
    expect(onfinished).toHaveBeenCalledTimes(1);
    expect(get(discoveryStatus)?.inboxCount).toBe(7);
    expect(screen.getByRole("button", { name: "Scan now" })).toBeEnabled();

    await vi.advanceTimersByTimeAsync(20_000);
    expect(getScanStatus).toHaveBeenCalledTimes(3);
    expect(onfinished).toHaveBeenCalledTimes(1);
  });

  it("does not stack polls when a status request is slow", async () => {
    vi.useFakeTimers();
    let release!: () => void;
    vi.mocked(getScanStatus)
      .mockResolvedValueOnce(fakeScanStatus({ scanning: true }))
      .mockImplementationOnce(
        () => new Promise((resolve) => (release = () => resolve(fakeScanStatus({ lastScanAt: LAST })))),
      );
    const onfinished = vi.fn();
    render(ScanHeader, { onfinished });
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(15_000);
    expect(getScanStatus).toHaveBeenCalledTimes(2);
    release();
    await vi.advanceTimersByTimeAsync(0);
    expect(onfinished).toHaveBeenCalledTimes(1);
  });

  it("stops polling when unmounted", async () => {
    vi.useFakeTimers();
    vi.mocked(getScanStatus).mockResolvedValue(fakeScanStatus({ scanning: true }));
    const { unmount } = render(ScanHeader);
    await vi.advanceTimersByTimeAsync(5000);
    expect(getScanStatus).toHaveBeenCalledTimes(2);
    unmount();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(getScanStatus).toHaveBeenCalledTimes(2);
  });
});
