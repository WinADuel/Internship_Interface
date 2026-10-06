import { describe, it, expect, vi } from "vitest";
import { apiFetch, ApiError } from "./client";

describe("apiFetch", () => {
  it("throws ApiError with status and detail on non-2xx", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false, status: 401, json: async () => ({ detail: "invalid credentials" }),
    });
    await expect(apiFetch("/api/auth/login")).rejects.toMatchObject({
      status: 401, detail: "invalid credentials",
    });
  });

  it("returns parsed JSON on success", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) });
    const result = await apiFetch("/api/health");
    expect(result).toEqual({ ok: true });
  });

  it("always sends credentials: include", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    globalThis.fetch = fetchMock;
    await apiFetch("/api/health", { method: "POST" });
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: "include", method: "POST" });
  });
});
