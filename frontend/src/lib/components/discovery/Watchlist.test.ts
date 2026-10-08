import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/discovery", () => ({
  listWatchlist: vi.fn(),
  addWatchCompany: vi.fn(),
  removeWatchCompany: vi.fn(),
}));
vi.mock("../../stores/toast", () => ({ showToast: vi.fn() }));

import { ApiError } from "../../api/client";
import { addWatchCompany, listWatchlist, removeWatchCompany } from "../../api/discovery";
import { showToast } from "../../stores/toast";
import { fakeWatchCompany } from "../../testing/fixtures";
import Watchlist from "./Watchlist.svelte";

const CUSTOM_SITE =
  "Google uses its own careers site, so it can't be watched. Its internships come in through the community lists, and you can paste any of its postings.";

let confirmSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  vi.mocked(listWatchlist).mockReset().mockResolvedValue([]);
  vi.mocked(addWatchCompany).mockReset();
  vi.mocked(removeWatchCompany).mockReset().mockResolvedValue(undefined);
  vi.mocked(showToast).mockReset();
  confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => {
  confirmSpy.mockRestore();
});

async function add(url: string, name = "") {
  await fireEvent.input(screen.getByLabelText("Careers page URL"), { target: { value: url } });
  if (name) await fireEvent.input(screen.getByLabelText("Name (optional)"), { target: { value: name } });
  await fireEvent.click(screen.getByRole("button", { name: "Add" }));
}

describe("Watchlist", () => {
  it("lists each company with its system, last check, open matches and last error", async () => {
    vi.mocked(listWatchlist).mockResolvedValue([
      fakeWatchCompany({ id: 1, name: "NVIDIA", ats: "workday", lastCheckedAt: null, openMatches: 1 }),
      fakeWatchCompany({
        id: 2,
        name: "Stripe",
        ats: "greenhouse",
        lastCheckedAt: "2026-09-01T10:00:00Z",
        openMatches: 3,
        lastError: "HTTP 500 from the board",
      }),
    ]);
    render(Watchlist);
    const rows = await screen.findAllByRole("listitem");
    expect(rows).toHaveLength(2);

    const nvidia = within(rows[0]);
    expect(nvidia.getByText("NVIDIA")).toBeInTheDocument();
    expect(nvidia.getByText("Workday")).toBeInTheDocument();
    expect(nvidia.getByText("Not checked yet")).toBeInTheDocument();
    expect(nvidia.getByText("1 open match")).toBeInTheDocument();

    const stripe = within(rows[1]);
    expect(stripe.getByText("Greenhouse")).toBeInTheDocument();
    expect(stripe.getByText(`Checked ${new Date("2026-09-01T10:00:00Z").toLocaleDateString()}`)).toBeInTheDocument();
    expect(stripe.getByText("3 open matches")).toBeInTheDocument();
    expect(stripe.getByText("Last check failed: HTTP 500 from the board")).toBeInTheDocument();
  });

  it("explains which big companies can't be watched", async () => {
    render(Watchlist);
    expect(
      screen.getByText(
        "Google, Microsoft, Apple, Meta and Amazon use their own sites; their internships come in through the community lists.",
      ),
    ).toBeInTheDocument();
    expect(await screen.findByText(/No companies yet/)).toBeInTheDocument();
  });

  it("adds a company by careers URL and optional name", async () => {
    const added = fakeWatchCompany({ id: 9, name: "Anthropic", ats: "ashby", openMatches: 0 });
    vi.mocked(listWatchlist).mockResolvedValue([fakeWatchCompany({ id: 1, name: "Stripe" })]);
    vi.mocked(addWatchCompany).mockResolvedValue(added);
    render(Watchlist);
    await screen.findByText("Stripe");
    await add("  https://jobs.ashbyhq.com/anthropic  ", "  Anthropic ");

    expect(addWatchCompany).toHaveBeenCalledWith({ careersUrl: "https://jobs.ashbyhq.com/anthropic", name: "Anthropic" });
    const rows = await screen.findAllByRole("listitem");
    expect(rows.map((r) => within(r).getByRole("heading").textContent)).toEqual(["Anthropic", "Stripe"]);
    expect(within(rows[0]).getByText("Ashby")).toBeInTheDocument();
    expect((screen.getByLabelText("Careers page URL") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Name (optional)") as HTMLInputElement).value).toBe("");
    expect(showToast).toHaveBeenCalledWith("Watching Anthropic. Its internships arrive with the next scan.", "info");
  });

  it("sends no name when the name is left blank", async () => {
    vi.mocked(addWatchCompany).mockResolvedValue(fakeWatchCompany({ id: 9, name: "Openai" }));
    render(Watchlist);
    await screen.findByText(/No companies yet/);
    await add("https://jobs.lever.co/openai");
    expect(addWatchCompany).toHaveBeenCalledWith({ careersUrl: "https://jobs.lever.co/openai", name: null });
  });

  it("shows the unsupported-site message inline under the form and keeps the URL", async () => {
    vi.mocked(addWatchCompany).mockRejectedValue(new ApiError(422, CUSTOM_SITE));
    render(Watchlist);
    await screen.findByText(/No companies yet/);
    await add("https://careers.google.com/jobs");
    expect(await screen.findByRole("alert")).toHaveTextContent(CUSTOM_SITE);
    expect((screen.getByLabelText("Careers page URL") as HTMLInputElement).value).toBe("https://careers.google.com/jobs");
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });

  it("shows a duplicate inline, and clears the message on the next success", async () => {
    vi.mocked(addWatchCompany)
      .mockRejectedValueOnce(new ApiError(409, "that company is already on the watchlist"))
      .mockResolvedValueOnce(fakeWatchCompany({ id: 3, name: "Figma" }));
    render(Watchlist);
    await screen.findByText(/No companies yet/);
    await add("https://boards.greenhouse.io/stripe");
    expect(await screen.findByRole("alert")).toHaveTextContent("that company is already on the watchlist");
    await add("https://boards.greenhouse.io/figma");
    await screen.findByText("Figma");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a network failure while adding gets a readable message", async () => {
    vi.mocked(addWatchCompany).mockRejectedValue(new TypeError("Failed to fetch"));
    render(Watchlist);
    await screen.findByText(/No companies yet/);
    await add("https://boards.greenhouse.io/stripe");
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't add that company.");
  });

  it("Remove asks first, then stops watching the company", async () => {
    vi.mocked(listWatchlist).mockResolvedValue([
      fakeWatchCompany({ id: 1, name: "Stripe" }),
      fakeWatchCompany({ id: 2, name: "Figma" }),
    ]);
    render(Watchlist);
    await fireEvent.click(await screen.findByRole("button", { name: "Remove Stripe from the watchlist" }));
    expect(confirmSpy).toHaveBeenCalledWith("Stop watching Stripe? Postings already found stay.");
    expect(removeWatchCompany).toHaveBeenCalledWith(1);
    await vi.waitFor(() => expect(screen.queryByText("Stripe")).toBeNull());
    expect(screen.getByText("Figma")).toBeInTheDocument();
  });

  it("does nothing when the remove confirm is declined", async () => {
    confirmSpy.mockReturnValue(false);
    vi.mocked(listWatchlist).mockResolvedValue([fakeWatchCompany({ id: 1, name: "Stripe" })]);
    render(Watchlist);
    await fireEvent.click(await screen.findByRole("button", { name: "Remove Stripe from the watchlist" }));
    expect(removeWatchCompany).not.toHaveBeenCalled();
    expect(screen.getByText("Stripe")).toBeInTheDocument();
  });

  it("a failed remove keeps the company and shows a toast", async () => {
    vi.mocked(removeWatchCompany).mockRejectedValue(new ApiError(404, "watch company not found"));
    vi.mocked(listWatchlist).mockResolvedValue([fakeWatchCompany({ id: 1, name: "Stripe" })]);
    render(Watchlist);
    await fireEvent.click(await screen.findByRole("button", { name: "Remove Stripe from the watchlist" }));
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith("Couldn't remove Stripe: watch company not found"));
    expect(screen.getByText("Stripe")).toBeInTheDocument();
  });

  it("shows a load failure with Retry", async () => {
    vi.mocked(listWatchlist).mockRejectedValueOnce(new ApiError(500, "db down"));
    vi.mocked(listWatchlist).mockResolvedValueOnce([fakeWatchCompany({ id: 1, name: "Stripe" })]);
    render(Watchlist);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load the watchlist: db down");
    await fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Stripe")).toBeInTheDocument();
  });

  it("renders company names and errors as plain text", async () => {
    vi.mocked(listWatchlist).mockResolvedValue([
      fakeWatchCompany({ id: 1, name: "<img src=x onerror=alert(1)>", lastError: "<b>boom</b>" }),
    ]);
    const { container } = render(Watchlist);
    expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(screen.getByText("Last check failed: <b>boom</b>")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
  });
});
