import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";
import { beforeEach, describe, expect, it, vi } from "vitest";

const routerState = vi.hoisted(() => ({ querystring: "" }));
vi.mock("svelte-spa-router", () => ({
  router: routerState,
  replace: vi.fn(),
}));
vi.mock("../lib/api/applications", () => ({
  updateApplication: vi.fn(),
  listApplications: vi.fn().mockResolvedValue([]),
  changeStatus: vi.fn(),
}));
vi.mock("../lib/api/docs", () => ({
  getDocContent: vi.fn().mockResolvedValue("doc text"),
  googleDocUrl: (r: string) => r,
}));
vi.mock("../lib/stores/applications", async () => {
  const { writable } = await import("svelte/store");
  return { applications: writable([]), loadApplications: vi.fn().mockResolvedValue(undefined) };
});

import { replace } from "svelte-spa-router";
import * as appsApi from "../lib/api/applications";
import { applications } from "../lib/stores/applications";
import { toasts } from "../lib/stores/toast";
import { fakeApplication } from "../lib/testing/fixtures";
import { promptTemplates } from "../lib/data/promptTemplates";
import Essays from "./Essays.svelte";

function setClipboard(writeText: unknown) {
  Object.defineProperty(navigator, "clipboard", {
    value: writeText ? { writeText } : undefined,
    configurable: true,
  });
}

describe("Essays", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routerState.querystring = "";
    toasts.set([]);
    applications.set([
      fakeApplication({ id: 1, company: "Acme" }),
      fakeApplication({ id: 2, company: "Beta" }),
    ]);
  });

  it("copies a template to the clipboard and toasts", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard(writeText);
    const { getAllByRole } = render(Essays);
    await fireEvent.click(getAllByRole("button", { name: "Copy" })[0]);
    expect(writeText).toHaveBeenCalledWith(promptTemplates[0].prompt);
    await waitFor(() =>
      expect(get(toasts).some((t) => t.text === "Copied." && t.kind === "info")).toBe(true),
    );
  });

  it("toasts an error when the clipboard fails", async () => {
    setClipboard(vi.fn().mockRejectedValue(new Error("denied")));
    const { getAllByRole, getAllByText } = render(Essays);
    await fireEvent.click(getAllByRole("button", { name: "Copy" })[0]);
    await waitFor(() => expect(get(toasts).some((t) => t.kind === "error")).toBe(true));
    expect(getAllByText(/\[PASTE THE ESSAY PROMPT HERE\]/).length).toBeGreaterThan(0);
  });

  it("toasts an error when the clipboard is unavailable", async () => {
    setClipboard(undefined);
    const { getAllByRole } = render(Essays);
    await fireEvent.click(getAllByRole("button", { name: "Copy" })[0]);
    await waitFor(() => expect(get(toasts).some((t) => t.kind === "error")).toBe(true));
  });

  it("links out to claude.ai and offers google connect", () => {
    const { getByText } = render(Essays);
    const link = getByText("claude.ai").closest("a")!;
    expect(link).toHaveAttribute("href", "https://claude.ai");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(getByText("Connect Google Docs").closest("a")).toHaveAttribute(
      "href",
      "/api/docs/google/authorize",
    );
  });

  it("shows the connected toast once and cleans the query", async () => {
    routerState.querystring = "connected=1";
    render(Essays);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/essays"));
    expect(get(toasts).filter((t) => t.text === "Google Docs connected.")).toHaveLength(1);
  });

  it("does not toast without connected=1", () => {
    render(Essays);
    expect(get(toasts)).toHaveLength(0);
    expect(replace).not.toHaveBeenCalled();
  });

  it("saves a doc link via updateApplication and updates the store", async () => {
    vi.mocked(appsApi.updateApplication).mockResolvedValue(
      fakeApplication({ id: 1, googleDocLink: "abc123" }),
    );
    const { getByLabelText, getByRole } = render(Essays);
    await fireEvent.input(getByLabelText("Google Doc link"), { target: { value: " abc123 " } });
    await fireEvent.click(getByRole("button", { name: "Save link" }));
    await waitFor(() =>
      expect(appsApi.updateApplication).toHaveBeenCalledWith(1, { googleDocLink: "abc123" }),
    );
    await waitFor(() => expect(get(applications)[0].googleDocLink).toBe("abc123"));
  });

  it("clears the link to null when saved empty", async () => {
    applications.set([fakeApplication({ id: 1, googleDocLink: "abc" })]);
    vi.mocked(appsApi.updateApplication).mockResolvedValue(
      fakeApplication({ id: 1, googleDocLink: null }),
    );
    const { getByLabelText, getByRole } = render(Essays);
    await fireEvent.input(getByLabelText("Google Doc link"), { target: { value: "  " } });
    await fireEvent.click(getByRole("button", { name: "Save link" }));
    await waitFor(() =>
      expect(appsApi.updateApplication).toHaveBeenCalledWith(1, { googleDocLink: null }),
    );
  });

  it("toasts when saving fails", async () => {
    vi.mocked(appsApi.updateApplication).mockRejectedValue(new Error("boom"));
    const { getByLabelText, getByRole } = render(Essays);
    await fireEvent.input(getByLabelText("Google Doc link"), { target: { value: "x" } });
    await fireEvent.click(getByRole("button", { name: "Save link" }));
    await waitFor(() =>
      expect(get(toasts).some((t) => t.kind === "error" && t.text.includes("boom"))).toBe(true),
    );
  });
});
