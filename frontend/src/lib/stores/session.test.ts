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
    const f = vi.fn()
      .mockResolvedValueOnce(res(401))
      .mockResolvedValueOnce(res(401));
    globalThis.fetch = f;
    await expect(checkSession()).resolves.toBeUndefined();
    expect(f).toHaveBeenCalledTimes(2);
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

  it("refreshes and retries once on 401, staying logged in", async () => {
    session.set({ loggedIn: true, checked: true });
    const f = vi.fn()
      .mockResolvedValueOnce(res(401))
      .mockResolvedValueOnce(res(200))
      .mockResolvedValueOnce(res(200, { data: 1 }));
    globalThis.fetch = f;
    await expect(apiFetch("/api/applications")).resolves.toEqual({ data: 1 });
    expect(f.mock.calls.map((c) => [c[0], c[1]?.method])).toEqual([
      ["/api/applications", undefined],
      ["/api/auth/refresh", "POST"],
      ["/api/applications", undefined],
    ]);
    expect(get(session)).toEqual({ loggedIn: true, checked: true });
  });

  it("logs out and throws when refresh fails", async () => {
    session.set({ loggedIn: true, checked: true });
    const f = vi.fn().mockResolvedValue(res(401));
    globalThis.fetch = f;
    await expect(apiFetch("/api/applications")).rejects.toMatchObject({ status: 401 });
    expect(f).toHaveBeenCalledTimes(2);
    expect(get(session)).toEqual({ loggedIn: false, checked: true });
  });

  it("shares one refresh across concurrent 401s", async () => {
    session.set({ loggedIn: true, checked: true });
    const seen: Record<string, number> = {};
    const f = vi.fn(async (path: string) => {
      seen[path] = (seen[path] ?? 0) + 1;
      if (path === "/api/auth/refresh") return res(200);
      return seen[path] === 1 ? res(401) : res(200, { ok: path });
    });
    globalThis.fetch = f as unknown as typeof fetch;
    const [a, b] = await Promise.all([apiFetch("/api/a"), apiFetch("/api/b")]);
    expect(a).toEqual({ ok: "/api/a" });
    expect(b).toEqual({ ok: "/api/b" });
    expect(f.mock.calls.filter((c) => c[0] === "/api/auth/refresh")).toHaveLength(1);
  });
});
