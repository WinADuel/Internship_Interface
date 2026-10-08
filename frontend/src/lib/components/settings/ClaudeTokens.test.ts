import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/settings", () => ({
  listClaudeTokens: vi.fn(),
  createClaudeToken: vi.fn(),
  revokeClaudeToken: vi.fn(),
}));
vi.mock("../../stores/toast", () => ({ showToast: vi.fn() }));

import { createClaudeToken, listClaudeTokens, revokeClaudeToken } from "../../api/settings";
import { showToast } from "../../stores/toast";
import type { ClaudeTokenInfo } from "../../types/contact";
import ClaudeTokens from "./ClaudeTokens.svelte";

const SECRET = "ct_" + "x".repeat(43);

function info(overrides: Partial<ClaudeTokenInfo> = {}): ClaudeTokenInfo {
  return {
    id: 1, tokenPrefix: "ct_abcde", createdAt: "2026-10-01T09:00:00Z", lastUsedAt: null, revokedAt: null,
    ...overrides,
  };
}

beforeEach(() => {
  // A leaked plaintext in the list response must never reach the DOM.
  vi.mocked(listClaudeTokens).mockReset().mockResolvedValue([
    { ...info(), token: "ct_should_never_render" } as ClaudeTokenInfo,
    info({ id: 2, tokenPrefix: "ct_zzzzz", revokedAt: "2026-10-02T09:00:00Z" }),
  ]);
  vi.mocked(createClaudeToken).mockReset().mockResolvedValue({ ...info({ id: 3, tokenPrefix: "ct_xxxxx" }), token: SECRET });
  vi.mocked(revokeClaudeToken).mockReset();
  vi.mocked(showToast).mockReset();
});

describe("ClaudeTokens", () => {
  it("lists tokens by prefix with their revoked state and never renders a token field", async () => {
    const { container } = render(ClaudeTokens);
    await screen.findByText("ct_abcde…");
    expect(screen.getByText("ct_zzzzz…")).toBeTruthy();
    expect(screen.getByText("Revoked")).toBeTruthy();
    expect(screen.getAllByText("Never used")).toHaveLength(2);
    expect(container.innerHTML).not.toContain("ct_should_never_render");
    // Only the active token can be revoked.
    expect(screen.getAllByRole("button", { name: /^Revoke/ })).toHaveLength(1);
  });

  it("shows a new token once, then removes it from the DOM on dismiss", async () => {
    const { container } = render(ClaudeTokens);
    await screen.findByText("ct_abcde…");
    await fireEvent.click(screen.getByRole("button", { name: "Create token" }));
    const field = (await screen.findByLabelText("New token")) as HTMLInputElement;
    expect(field.value).toBe(SECRET);
    expect(field.readOnly).toBe(true);
    expect(screen.getByText("Copy this now — it won't be shown again.")).toBeTruthy();
    expect(screen.getByText("ct_xxxxx…")).toBeTruthy();

    await fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByLabelText("New token")).toBeNull();
    expect(container.innerHTML).not.toContain(SECRET);
  });

  it("drops the plaintext when the page is hidden (leaving the app)", async () => {
    render(ClaudeTokens);
    await screen.findByText("ct_abcde…");
    await fireEvent.click(screen.getByRole("button", { name: "Create token" }));
    await screen.findByLabelText("New token");
    await fireEvent(window, new Event("pagehide"));
    expect(screen.queryByLabelText("New token")).toBeNull();
    expect(document.body.innerHTML).not.toContain(SECRET);
  });

  it("focuses the new token, and Done returns focus to Create token", async () => {
    render(ClaudeTokens);
    await screen.findByText("ct_abcde…");
    await fireEvent.click(screen.getByRole("button", { name: "Create token" }));
    const field = await screen.findByLabelText("New token");
    await vi.waitFor(() => expect(document.activeElement).toBe(field));
    await fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Create token" }));
  });

  it("revokes a token that arrives after the user navigated away", async () => {
    let resolve!: (v: Awaited<ReturnType<typeof createClaudeToken>>) => void;
    vi.mocked(createClaudeToken).mockReturnValue(new Promise((r) => (resolve = r)));
    vi.mocked(revokeClaudeToken).mockResolvedValue(info({ id: 3 }));
    const view = render(ClaudeTokens);
    await screen.findByText("ct_abcde…");
    await fireEvent.click(screen.getByRole("button", { name: "Create token" }));
    view.unmount();
    resolve({ ...info({ id: 3 }), token: SECRET });
    await vi.waitFor(() => expect(revokeClaudeToken).toHaveBeenCalledWith(3));
  });

  it("a failed revoke shows a toast and keeps the token active", async () => {
    vi.mocked(revokeClaudeToken).mockRejectedValue(new Error("gone"));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(ClaudeTokens);
    await screen.findByText("ct_abcde…");
    await fireEvent.click(screen.getByRole("button", { name: "Revoke ct_abcde…" }));
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith("Couldn't revoke the token."));
    expect(screen.getAllByText("Active")).toHaveLength(1);
    vi.mocked(window.confirm).mockRestore();
  });

  it("Copy writes the token to the clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(ClaudeTokens);
    await screen.findByText("ct_abcde…");
    await fireEvent.click(screen.getByRole("button", { name: "Create token" }));
    await fireEvent.click(await screen.findByRole("button", { name: "Copy" }));
    expect(writeText).toHaveBeenCalledWith(SECRET);
  });

  it("Revoke asks first and only calls the API once confirmed", async () => {
    vi.mocked(revokeClaudeToken).mockResolvedValue(info({ revokedAt: "2026-10-08T09:00:00Z" }));
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    render(ClaudeTokens);
    await screen.findByText("ct_abcde…");
    await fireEvent.click(screen.getByRole("button", { name: "Revoke ct_abcde…" }));
    expect(revokeClaudeToken).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole("button", { name: "Revoke ct_abcde…" }));
    expect(confirm).toHaveBeenCalledTimes(2);
    await vi.waitFor(() => expect(revokeClaudeToken).toHaveBeenCalledWith(1));
    await vi.waitFor(() => expect(screen.getAllByText("Revoked")).toHaveLength(2));
    confirm.mockRestore();
  });

  it("a failed create shows a toast and no token field", async () => {
    vi.mocked(createClaudeToken).mockRejectedValue(new Error("boom"));
    render(ClaudeTokens);
    await screen.findByText("ct_abcde…");
    await fireEvent.click(screen.getByRole("button", { name: "Create token" }));
    await vi.waitFor(() => expect(showToast).toHaveBeenCalled());
    expect(screen.queryByLabelText("New token")).toBeNull();
  });
});
