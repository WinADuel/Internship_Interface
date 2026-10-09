import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("svelte-spa-router", () => ({ push }));
vi.mock("../api/discovery", () => ({ getScanStatus: vi.fn() }));
vi.mock("../api/email", () => ({ getEmailStatus: vi.fn() }));

import { getScanStatus } from "../api/discovery";
import { getEmailStatus } from "../api/email";
import { discoveryStatus } from "../stores/discovery";
import { emailStatus } from "../stores/email";
import { session } from "../stores/session";
import { fakeEmailStatus, fakeScanStatus } from "../testing/fixtures";
import { toasts } from "../stores/toast";
import NavSidebar from "./NavSidebar.svelte";

beforeEach(() => {
  push.mockReset().mockResolvedValue(undefined);
  toasts.set([]);
  session.set({ loggedIn: true, checked: true });
  discoveryStatus.set(null);
  emailStatus.set(null);
  vi.mocked(getScanStatus).mockReset().mockResolvedValue(fakeScanStatus());
  vi.mocked(getEmailStatus).mockReset().mockResolvedValue(fakeEmailStatus());
});

describe("NavSidebar", () => {
  it("links to the main pages", () => {
    render(NavSidebar);
    expect(screen.getByRole("link", { name: "Dashboard" }).getAttribute("href")).toBe("#/");
    expect(screen.getByRole("link", { name: "Applications" }).getAttribute("href")).toBe("#/applications");
    expect(screen.getByRole("link", { name: "Discover" }).getAttribute("href")).toBe("#/discover");
    expect(screen.getByRole("link", { name: "Essays" }).getAttribute("href")).toBe("#/essays");
    expect(screen.getByRole("link", { name: "Contacts" }).getAttribute("href")).toBe("#/contacts");
    expect(screen.getByRole("link", { name: "Research Queue" }).getAttribute("href")).toBe("#/research-queue");
    expect(screen.getByRole("link", { name: "Settings" }).getAttribute("href")).toBe("#/settings");
    expect(screen.getByRole("link", { name: "Interview Prep" }).getAttribute("href")).toBe("#/interviews");
    expect(screen.queryByText(/Interview Prep\s*Coming soon/)).toBeNull();
    expect(screen.getByRole("link", { name: "Email updates" }).getAttribute("href")).toBe("#/email");
    expect(screen.queryByText(/Coming soon/)).toBeNull();
  });

  it("Logout calls the logout endpoint, clears the session and routes to /login", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ detail: "ok" }) });
    render(NavSidebar);
    await fireEvent.click(screen.getByRole("button", { name: "Log out" }));
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith("/login"));
    expect((globalThis.fetch as any).mock.calls[0][0]).toBe("/api/auth/logout");
    expect(get(session).loggedIn).toBe(false);
  });

  it("stays signed in and shows a toast when the logout request fails", async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new Error("offline"));
    render(NavSidebar);
    await fireEvent.click(screen.getByRole("button", { name: "Log out" }));
    await vi.waitFor(() => expect(get(toasts).map((t) => t.text)).toEqual(["Couldn't log out: offline"]));
    expect(push).not.toHaveBeenCalled();
    expect(get(session).loggedIn).toBe(true);
  });

  it("hides the Logout button when logged out", () => {
    session.set({ loggedIn: false, checked: true });
    render(NavSidebar);
    expect(screen.queryByRole("button", { name: "Log out" })).toBeNull();
  });

  it("puts Discover right after Applications and drops the Coming soon placeholder", () => {
    render(NavSidebar);
    const links = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(links.indexOf("#/discover")).toBe(links.indexOf("#/applications") + 1);
    expect(screen.queryByText("Job Discovery")).toBeNull();
  });

  it("refreshes the scan status on mount and badges the Inbox count", async () => {
    vi.mocked(getScanStatus).mockResolvedValue(fakeScanStatus({ inboxCount: 12 }));
    render(NavSidebar);
    const link = await screen.findByRole("link", { name: "Discover (12 new)" });
    expect(link.getAttribute("href")).toBe("#/discover");
    expect(link).toHaveTextContent("12");
    expect(getScanStatus).toHaveBeenCalledTimes(1);
  });

  it("follows later status updates and hides the badge at zero", async () => {
    render(NavSidebar);
    await vi.waitFor(() => expect(getScanStatus).toHaveBeenCalled());
    discoveryStatus.set(fakeScanStatus({ inboxCount: 3 }));
    expect(await screen.findByRole("link", { name: "Discover (3 new)" })).toBeInTheDocument();
    discoveryStatus.set(fakeScanStatus({ inboxCount: 0 }));
    const link = await screen.findByRole("link", { name: "Discover" });
    expect(link.textContent?.trim()).toBe("Discover");
  });

  it("badges the pending email updates and follows later changes", async () => {
    vi.mocked(getEmailStatus).mockResolvedValue(fakeEmailStatus({ pendingCount: 4 }));
    render(NavSidebar);
    const link = await screen.findByRole("link", { name: "Email updates (4 to review)" });
    expect(link.getAttribute("href")).toBe("#/email");
    expect(link).toHaveTextContent("4");
    expect(getEmailStatus).toHaveBeenCalledTimes(1);
    emailStatus.set(fakeEmailStatus({ pendingCount: 0 }));
    expect((await screen.findByRole("link", { name: "Email updates" })).textContent?.trim()).toBe("Email updates");
  });

  it("does not ask for the status while logged out", () => {
    session.set({ loggedIn: false, checked: true });
    render(NavSidebar);
    expect(getScanStatus).not.toHaveBeenCalled();
    expect(getEmailStatus).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Discover" })).toBeInTheDocument();
  });
});
