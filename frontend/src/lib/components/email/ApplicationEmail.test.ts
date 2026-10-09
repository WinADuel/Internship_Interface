import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/email", () => ({ listSuggestions: vi.fn(), acceptSuggestion: vi.fn(), dismissSuggestion: vi.fn() }));
vi.mock("../../stores/email", () => ({
  afterAccept: vi.fn().mockResolvedValue(undefined),
  refreshEmailStatus: vi.fn().mockResolvedValue(null),
}));
vi.mock("../../stores/toast", () => ({ showToast: vi.fn() }));

import { acceptSuggestion, listSuggestions } from "../../api/email";
import { fakeSuggestion } from "../../testing/fixtures";
import ApplicationEmail from "./ApplicationEmail.svelte";

beforeEach(() => {
  vi.mocked(listSuggestions).mockReset();
  vi.mocked(acceptSuggestion).mockReset();
});

describe("ApplicationEmail", () => {
  it("lists this application's pending and decided emails", async () => {
    vi.mocked(listSuggestions).mockResolvedValue([
      fakeSuggestion({ id: 1, subject: "Interview with Acme", kind: "interview" }),
      fakeSuggestion({ id: 2, subject: "Thank you for applying", state: "accepted" }),
    ]);
    render(ApplicationEmail, { applicationId: 3 });
    const section = screen.getByRole("region", { name: "Email" });
    expect(await screen.findByText("Interview with Acme")).toBeInTheDocument();
    expect(section).toHaveTextContent("Thank you for applying");
    expect(listSuggestions).toHaveBeenCalledWith({ state: "all", applicationId: 3, limit: 50 });
    expect(screen.getAllByRole("button", { name: "Accept" })).toHaveLength(1);
  });

  it("says when nothing matched", async () => {
    vi.mocked(listSuggestions).mockResolvedValue([]);
    render(ApplicationEmail, { applicationId: 3 });
    expect(await screen.findByText("No emails matched to this application yet.")).toBeInTheDocument();
  });

  it("shows a decided card as decided at once, before the reload answers", async () => {
    vi.mocked(listSuggestions)
      .mockResolvedValueOnce([fakeSuggestion({ id: 1, subject: "Interview with Acme" })])
      .mockReturnValueOnce(new Promise(() => {}));
    vi.mocked(acceptSuggestion).mockResolvedValue(
      fakeSuggestion({ id: 1, subject: "Interview with Acme", state: "accepted", decidedAt: "2026-10-09T10:00:00Z" }),
    );
    render(ApplicationEmail, { applicationId: 1 });
    await fireEvent.click(await screen.findByRole("button", { name: "Accept" }));
    await vi.waitFor(() => expect(screen.queryByRole("button", { name: "Accept" })).toBeNull());
    expect(screen.getByText("Interview with Acme")).toBeInTheDocument();
    expect(screen.getAllByText(/Accepted/).length).toBeGreaterThan(0);
  });

  it("reloads and tells the panel after a decision", async () => {
    vi.mocked(listSuggestions).mockResolvedValueOnce([fakeSuggestion()]).mockResolvedValueOnce([]);
    vi.mocked(acceptSuggestion).mockResolvedValue(fakeSuggestion({ state: "accepted" }));
    const onchanged = vi.fn();
    render(ApplicationEmail, { applicationId: 1, onchanged });
    await fireEvent.click(await screen.findByRole("button", { name: "Accept" }));
    await vi.waitFor(() => expect(onchanged).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("No emails matched to this application yet.")).toBeInTheDocument();
    expect(listSuggestions).toHaveBeenCalledTimes(2);
  });
});
