import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./client";
import { getDocContent, googleDocUrl } from "./docs";

describe("getDocContent", () => {
  afterEach(() => vi.restoreAllMocks());

  it("returns doc content on success", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ content: "hello" }) });
    expect(await getDocContent("abc123")).toBe("hello");
  });

  it("url-encodes the doc_ref", async () => {
    const f = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ content: "x" }) });
    globalThis.fetch = f;
    await getDocContent("https://docs.google.com/document/d/abc/edit?x=1&y=2");
    expect(f.mock.calls[0][0]).toBe(
      `/api/docs/content?doc_ref=${encodeURIComponent("https://docs.google.com/document/d/abc/edit?x=1&y=2")}`,
    );
  });

  it("propagates ApiError", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false, status: 502, statusText: "Bad Gateway", json: async () => ({ detail: "couldn't load doc" }),
    });
    await expect(getDocContent("abc")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("googleDocUrl", () => {
  it("builds an edit url from a bare id", () => {
    expect(googleDocUrl("abc123")).toBe("https://docs.google.com/document/d/abc123/edit");
  });
  it("encodes a bare id", () => {
    expect(googleDocUrl("a b/c")).toBe("https://docs.google.com/document/d/a%20b%2Fc/edit");
  });
  it("uses a full docs url unchanged", () => {
    const u = "https://docs.google.com/document/d/abc123/edit?tab=t.0";
    expect(googleDocUrl(u)).toBe(u);
  });
});
