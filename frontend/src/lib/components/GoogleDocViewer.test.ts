import { render } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import * as docsApi from "../api/docs";
import GoogleDocViewer from "./GoogleDocViewer.svelte";

describe("GoogleDocViewer", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows a fallback link when the doc fails to load", async () => {
    vi.spyOn(docsApi, "getDocContent").mockRejectedValue(new ApiError(502, "couldn't load doc"));
    const { findByText } = render(GoogleDocViewer, { props: { docRef: "abc123" } });
    expect(await findByText("Couldn't load doc.")).toBeInTheDocument();
    const link = await findByText("Open in Google Docs");
    expect(link).toHaveAttribute("href", "https://docs.google.com/document/d/abc123/edit");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("uses a full docs url unchanged in the fallback", async () => {
    const u = "https://docs.google.com/document/d/abc123/edit";
    vi.spyOn(docsApi, "getDocContent").mockRejectedValue(new ApiError(422, "invalid doc reference"));
    const { findByText } = render(GoogleDocViewer, { props: { docRef: u } });
    expect(await findByText("Open in Google Docs")).toHaveAttribute("href", u);
  });

  it("renders content on success", async () => {
    vi.spyOn(docsApi, "getDocContent").mockResolvedValue("my essay draft");
    const { findByText } = render(GoogleDocViewer, { props: { docRef: "abc123" } });
    expect(await findByText("my essay draft")).toBeInTheDocument();
  });

  it("shows loading while pending and fetches once", async () => {
    const spy = vi.spyOn(docsApi, "getDocContent").mockReturnValue(new Promise(() => {}));
    const { findByText } = render(GoogleDocViewer, { props: { docRef: "abc123" } });
    expect(await findByText("Loading doc…")).toBeInTheDocument();
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("renders nothing and does not fetch when docRef is null", () => {
    const spy = vi.spyOn(docsApi, "getDocContent");
    const { container } = render(GoogleDocViewer, { props: { docRef: null } });
    expect(container.textContent?.trim()).toBe("");
    expect(spy).not.toHaveBeenCalled();
  });

  it("does not interpret content as html", async () => {
    vi.spyOn(docsApi, "getDocContent").mockResolvedValue("<b>hi</b>");
    const { findByText, container } = render(GoogleDocViewer, { props: { docRef: "abc" } });
    expect(await findByText("<b>hi</b>")).toBeInTheDocument();
    expect(container.querySelector("b")).toBeNull();
  });
});
