import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("svelte-spa-router", () => ({ push }));

import { session } from "../stores/session";
import { toasts } from "../stores/toast";
import NavSidebar from "./NavSidebar.svelte";

beforeEach(() => {
  push.mockReset().mockResolvedValue(undefined);
  toasts.set([]);
  session.set({ loggedIn: true, checked: true });
});

describe("NavSidebar", () => {
  it("links to the main pages", () => {
    render(NavSidebar);
    expect(screen.getByRole("link", { name: "Dashboard" }).getAttribute("href")).toBe("#/");
    expect(screen.getByRole("link", { name: "Applications" }).getAttribute("href")).toBe("#/applications");
    expect(screen.getByRole("link", { name: "Essays" }).getAttribute("href")).toBe("#/essays");
    expect(screen.getByRole("link", { name: "Contacts" }).getAttribute("href")).toBe("#/contacts");
    expect(screen.getByRole("link", { name: "Research Queue" }).getAttribute("href")).toBe("#/research-queue");
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
});
