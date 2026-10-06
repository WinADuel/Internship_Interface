import { describe, it, expect, vi, beforeEach } from "vitest";
import { get } from "svelte/store";
import { session, checkSession } from "./session";
import { apiFetch } from "../api/client";

function res(status: number, body: unknown = {}) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

beforeEach(() => {
  session.set({ loggedIn: false, checked: false });
});

describe("checkSession", () => {
  it("logs in when /me succeeds", async () => {
    globalThis.fetch = vi.fn().mockResolvedValueOnce(res(200, { username: "dxwu" }));
    await checkSession();
    expect(get(session)).toEqual({ loggedIn: true, checked: true });
  });

  it("refreshes once on 401 then retries /me", async () => {
    const f = vi.fn()
      .mockResolvedValueOnce(res(401, { detail: "not authenticated" }))
      .mockResolvedValueOnce(res(200))
      .mockResolvedValueOnce(res(200, { username: "dxwu" }));
    globalThis.fetch = f;
    await checkSession();
    expect(f.mock.calls.map((c) => c[0])).toEqual([
      "/api/auth/me", "/api/auth/refresh", "/api/auth/me",
    ]);
    expect(get(session)).toEqual({ loggedIn: true, checked: true });
  });

  it("ends logged out when refresh fails, without throwing", async () => {
    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(res(401))
      .mockResolvedValueOnce(res(401));
    await expect(checkSession()).resolves.toBeUndefined();
    expect(get(session)).toEqual({ loggedIn: false, checked: true });
  });

  it("ends logged out on network error without throwing", async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new TypeError("fail"));
    await expect(checkSession()).resolves.toBeUndefined();
    expect(get(session)).toEqual({ loggedIn: false, checked: true });
  });
});

describe("apiFetch 401 handling", () => {
  it("logs out the session on 401 from a non-auth path", async () => {
    session.set({ loggedIn: true, checked: true });
    globalThis.fetch = vi.fn().mockResolvedValue(res(401));
    await expect(apiFetch("/api/applications")).rejects.toMatchObject({ status: 401 });
    expect(get(session)).toEqual({ loggedIn: false, checked: true });
  });

  it("leaves the session untouched on 401 from an auth path", async () => {
    session.set({ loggedIn: true, checked: true });
    globalThis.fetch = vi.fn().mockResolvedValue(res(401));
    await expect(apiFetch("/api/auth/login")).rejects.toMatchObject({ status: 401 });
    expect(get(session)).toEqual({ loggedIn: true, checked: true });
  });
});
