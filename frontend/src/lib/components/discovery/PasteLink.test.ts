import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/discovery", () => ({ previewPaste: vi.fn(), confirmPaste: vi.fn() }));
vi.mock("../../stores/toast", () => ({ showToast: vi.fn() }));
vi.mock("../../stores/discovery", () => ({ refreshDiscoveryStatus: vi.fn() }));

import { ApiError } from "../../api/client";
import { confirmPaste, previewPaste } from "../../api/discovery";
import { refreshDiscoveryStatus } from "../../stores/discovery";
import { showToast } from "../../stores/toast";
import { fakePosting } from "../../testing/fixtures";
import type { PastePreview } from "../../types/discovery";
import PasteLink from "./PasteLink.svelte";

const URL = "https://boards.greenhouse.io/stripe/jobs/123";

const preview: PastePreview = {
  company: "Stripe",
  title: "SWE Intern",
  locations: ["NYC", "Remote"],
  url: URL,
  datePosted: "2026-10-01",
  source: "greenhouse",
};

beforeEach(() => {
  vi.mocked(previewPaste).mockReset().mockResolvedValue(preview);
  vi.mocked(confirmPaste).mockReset();
  vi.mocked(showToast).mockReset();
  vi.mocked(refreshDiscoveryStatus).mockReset().mockResolvedValue(null);
});

async function previewLink() {
  await fireEvent.input(screen.getByLabelText("Posting link"), { target: { value: `  ${URL} ` } });
  await fireEvent.click(screen.getByRole("button", { name: "Preview" }));
}

describe("PasteLink", () => {
  it("previews a link into editable fields, then saves the edited fields", async () => {
    const saved = fakePosting({ id: 5, state: "saved", company: "Stripe, Inc.", title: "SWE Intern" });
    vi.mocked(confirmPaste).mockResolvedValue(saved);
    const onsaved = vi.fn();
    render(PasteLink, { onsaved });
    await previewLink();
    expect(previewPaste).toHaveBeenCalledWith(URL);

    const company = (await screen.findByLabelText("Company")) as HTMLInputElement;
    expect(company.value).toBe("Stripe");
    expect((screen.getByLabelText("Title") as HTMLInputElement).value).toBe("SWE Intern");
    // One chip per location.
    expect(screen.getByText("NYC")).toBeInTheDocument();
    expect(screen.getByText("Remote")).toBeInTheDocument();
    expect(screen.getByText("Greenhouse")).toBeInTheDocument();

    await fireEvent.input(company, { target: { value: "  Stripe, Inc. " } });
    await fireEvent.click(screen.getByRole("button", { name: "Remove Remote from Locations" }));
    const locations = screen.getByLabelText("Locations");
    await fireEvent.input(locations, { target: { value: " San Francisco, CA " } });
    await fireEvent.keyDown(locations, { key: "Enter" });
    await fireEvent.click(screen.getByRole("button", { name: "Save to Saved" }));

    expect(confirmPaste).toHaveBeenCalledWith({
      url: URL,
      company: "Stripe, Inc.",
      title: "SWE Intern",
      locations: ["NYC", "San Francisco, CA"],
      datePosted: "2026-10-01",
    });
    await vi.waitFor(() => expect(onsaved).toHaveBeenCalledWith(saved));
    expect(refreshDiscoveryStatus).toHaveBeenCalledTimes(1);
    expect(showToast).toHaveBeenCalledWith("Saved Stripe, Inc. – SWE Intern.", "info");
    expect(screen.queryByLabelText("Company")).toBeNull();
    expect((screen.getByLabelText("Posting link") as HTMLInputElement).value).toBe("");
  });

  it("keeps locations that contain commas whole", async () => {
    vi.mocked(previewPaste).mockResolvedValue({ ...preview, locations: ["San Francisco, CA", "New York, NY"] });
    vi.mocked(confirmPaste).mockResolvedValue(fakePosting({ id: 6, state: "saved" }));
    render(PasteLink);
    await previewLink();
    expect(await screen.findByText("San Francisco, CA")).toBeInTheDocument();
    expect(screen.getByText("New York, NY")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Save to Saved" }));
    expect(confirmPaste).toHaveBeenCalledWith(
      expect.objectContaining({ locations: ["San Francisco, CA", "New York, NY"] }),
    );
  });

  it("saves a location typed but not yet added", async () => {
    vi.mocked(confirmPaste).mockResolvedValue(fakePosting({ id: 7, state: "saved" }));
    render(PasteLink);
    await previewLink();
    await fireEvent.input(await screen.findByLabelText("Locations"), { target: { value: "Austin, TX" } });
    await fireEvent.click(screen.getByRole("button", { name: "Save to Saved" }));
    expect(confirmPaste).toHaveBeenCalledWith(expect.objectContaining({ locations: ["NYC", "Remote", "Austin, TX"] }));
  });

  it("does not save while a typed location is refused", async () => {
    render(PasteLink);
    await previewLink();
    await fireEvent.input(await screen.findByLabelText("Locations"), { target: { value: "x".repeat(201) } });
    await fireEvent.click(screen.getByRole("button", { name: "Save to Saved" }));
    expect(confirmPaste).not.toHaveBeenCalled();
    expect(screen.getByText("Each entry can be at most 200 characters.")).toBeInTheDocument();
  });

  it("caps locations at 20, each at most 200 characters", async () => {
    vi.mocked(previewPaste).mockResolvedValue({ ...preview, locations: Array.from({ length: 20 }, (_, i) => `City ${i}`) });
    render(PasteLink);
    await previewLink();
    const input = (await screen.findByLabelText("Locations")) as HTMLInputElement;
    expect(input.maxLength).toBe(200);
    await fireEvent.input(input, { target: { value: "One more" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByText("At most 20 entries.")).toBeInTheDocument();
  });

  it("shows a preview error inline", async () => {
    vi.mocked(previewPaste).mockRejectedValue(new ApiError(422, "No job details found on that page."));
    render(PasteLink);
    await previewLink();
    expect(await screen.findByRole("alert")).toHaveTextContent("No job details found on that page.");
    expect(screen.queryByLabelText("Company")).toBeNull();
  });

  it("shows a save error inline and keeps the edits", async () => {
    vi.mocked(confirmPaste).mockRejectedValue(new ApiError(409, "posting is already saved"));
    const onsaved = vi.fn();
    render(PasteLink, { onsaved });
    await previewLink();
    await fireEvent.input(await screen.findByLabelText("Title"), { target: { value: "Backend Intern" } });
    await fireEvent.click(screen.getByRole("button", { name: "Save to Saved" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("posting is already saved");
    expect((screen.getByLabelText("Title") as HTMLInputElement).value).toBe("Backend Intern");
    expect(onsaved).not.toHaveBeenCalled();
    expect(refreshDiscoveryStatus).not.toHaveBeenCalled();
  });

  it("a network failure gets a readable message", async () => {
    vi.mocked(previewPaste).mockRejectedValue(new TypeError("Failed to fetch"));
    render(PasteLink);
    await previewLink();
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't read that link.");
  });

  it("Cancel drops the preview without saving", async () => {
    render(PasteLink);
    await previewLink();
    await screen.findByLabelText("Company");
    await fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Company")).toBeNull();
    expect(confirmPaste).not.toHaveBeenCalled();
  });

  it("shows the previewed link as plain text, never as markup", async () => {
    vi.mocked(previewPaste).mockResolvedValue({ ...preview, title: "<img src=x onerror=alert(1)>" });
    const { container } = render(PasteLink);
    await previewLink();
    const title = (await screen.findByLabelText("Title")) as HTMLInputElement;
    expect(title.value).toBe("<img src=x onerror=alert(1)>");
    expect(container.querySelector("img")).toBeNull();
  });
});
