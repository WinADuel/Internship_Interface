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

describe("ApiError message", () => {
  it("uses a string detail as is", () => {
    expect(new ApiError(401, "invalid credentials").message).toBe("invalid credentials");
  });

  it("falls back to the status when the detail is not usable", () => {
    expect(new ApiError(500, undefined).message).toBe("Request failed (500)");
    expect(new ApiError(500, { oops: true }).message).toBe("Request failed (500)");
    expect(new ApiError(422, []).message).toBe("Request failed (422)");
  });

  it("formats a FastAPI 422 detail array as readable field: message text", () => {
    const detail = [
      { type: "missing", loc: ["body", "company"], msg: "Field required", input: {} },
      { type: "string_type", loc: ["body", "role_title"], msg: "Input should be a valid string" },
    ];
    expect(new ApiError(422, detail).message).toBe(
      "company: Field required; role_title: Input should be a valid string",
    );
  });

  it("joins nested locations, drops the request-part prefix and 'Value error, '", () => {
    const detail = [
      { loc: ["query", "limit"], msg: "Input should be greater than 0" },
      { loc: ["body", "items", 0, "name"], msg: "Value error, name cannot be blank" },
      { loc: ["body"], msg: "Value error, company cannot be null" },
    ];
    expect(new ApiError(422, detail).message).toBe(
      "limit: Input should be greater than 0; items.0.name: name cannot be blank; company cannot be null",
    );
  });

  it("tolerates malformed array entries", () => {
    expect(new ApiError(422, ["bad", { msg: "Only a message" }, null]).message).toBe(
      "bad; Only a message",
    );
  });

  it("is what apiFetch surfaces for a 422 response", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: [{ loc: ["body", "company"], msg: "Field required" }] }),
    });
    await expect(apiFetch("/api/applications")).rejects.toThrow("company: Field required");
  });
});
