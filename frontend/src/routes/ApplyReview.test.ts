import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api/apply", () => ({ getApplication: vi.fn(), saveAnswers: vi.fn(), draftWithAi: vi.fn() }));
vi.mock("../lib/api/discovery", () => ({ applyToPosting: vi.fn() }));
vi.mock("../lib/stores/toast", () => ({ showToast: vi.fn() }));

import { draftWithAi, getApplication, saveAnswers } from "../lib/api/apply";
import { applyToPosting } from "../lib/api/discovery";
import { showToast } from "../lib/stores/toast";
import type { ApplyDraft, FormField } from "../lib/types/apply";
import ApplyReview from "./ApplyReview.svelte";

function field(overrides: Partial<FormField>): FormField {
  return {
    key: "k", label: "Label", kind: "text", required: false, options: [], section: "application",
    description: "", value: "", source: "", ...overrides,
  };
}

function draft(overrides: Partial<ApplyDraft> = {}): ApplyDraft {
  return {
    postingId: 7,
    company: "Discord",
    title: "SWE Intern",
    postingState: "saved",
    ats: "greenhouse",
    applyUrl: "https://job-boards.greenhouse.io/discord/jobs/1",
    fetchedAt: "2026-11-05T10:00:00Z",
    updatedAt: "2026-11-05T10:00:00Z",
    resumeFilename: "Resume.pdf",
    llmReady: true,
    fields: [
      field({ key: "first_name", label: "First Name", required: true, value: "Dana", source: "profile" }),
      field({ key: "why", label: "Why Discord?", kind: "textarea", required: true }),
      field({ key: "auth", label: "Authorized to work?", kind: "select", options: [{ label: "Yes", value: "1" }, { label: "No", value: "0" }], value: "Yes", source: "profile" }),
      field({ key: "resume", label: "Resume/CV", kind: "file", value: "Resume.pdf", source: "profile" }),
      field({ key: "g", label: "Gender", kind: "select", section: "demographic", options: [{ label: "Male", value: "1" }] }),
      field({ key: "langs", label: "Languages", kind: "multiselect", options: [{ label: "English", value: "en" }, { label: "Spanish", value: "es" }], value: [] }),
    ],
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(getApplication).mockReset().mockResolvedValue(draft());
  vi.mocked(saveAnswers).mockReset();
  vi.mocked(draftWithAi).mockReset();
  vi.mocked(applyToPosting).mockReset();
  vi.mocked(showToast).mockReset();
});

describe("ApplyReview", () => {
  it("shows the prefilled form with sources and what is still missing", async () => {
    render(ApplyReview, { params: { id: "7" } });
    expect(await screen.findByRole("heading", { name: "Discord: SWE Intern" })).toBeInTheDocument();
    expect(getApplication).toHaveBeenCalledWith(7, false);
    expect((screen.getByLabelText(/^First Name/) as HTMLInputElement).value).toBe("Dana");
    expect((screen.getByLabelText(/^Authorized to work/) as HTMLSelectElement).value).toBe("Yes");
    expect(screen.getAllByText("From your profile")).toHaveLength(3);
    expect(screen.getByText("3 of 6 filled.")).toBeInTheDocument();
    expect(screen.getByText("1 required still empty.")).toBeInTheDocument();
    expect(screen.getByText("Resume.pdf", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Voluntary self-identification" })).toBeInTheDocument();
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("saves only changed answers, with remember", async () => {
    vi.mocked(saveAnswers).mockResolvedValue(draft());
    render(ApplyReview, { params: { id: "7" } });
    const why = (await screen.findByLabelText(/^Why Discord/)) as HTMLTextAreaElement;
    await fireEvent.input(why, { target: { value: "I use it every day." } });
    await fireEvent.click(screen.getByLabelText(/Reuse this answer/));
    await fireEvent.click(screen.getByLabelText("Spanish"));
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await vi.waitFor(() =>
      expect(saveAnswers).toHaveBeenCalledWith(7, {
        why: { value: "I use it every day.", remember: true },
        langs: { value: ["Spanish"], remember: false },
      }),
    );
    expect(showToast).toHaveBeenCalledWith("Answers saved.", "info");
  });

  it("opens the real application page in a new tab", async () => {
    const tab = { opener: {}, location: { href: "" }, close: vi.fn() };
    const open = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    render(ApplyReview, { params: { id: "7" } });
    await fireEvent.click(await screen.findByRole("button", { name: "Open application" }));
    await vi.waitFor(() => expect(tab.location.href).toBe("https://job-boards.greenhouse.io/discord/jobs/1"));
    expect(tab.opener).toBeNull();
    expect(saveAnswers).not.toHaveBeenCalled();
    open.mockRestore();
  });

  it("drafts empty open answers with the local AI", async () => {
    const drafted = draft();
    drafted.fields[1] = { ...drafted.fields[1], value: "Because.", source: "ai" };
    vi.mocked(draftWithAi).mockResolvedValue({ drafted: ["why"], failed: [], error: null, draft: drafted });
    render(ApplyReview, { params: { id: "7" } });
    await fireEvent.click(await screen.findByRole("button", { name: "Draft empty answers with local AI" }));
    await vi.waitFor(() => expect((screen.getByLabelText(/^Why Discord/) as HTMLTextAreaElement).value).toBe("Because."));
    expect(screen.getByText("AI draft: check it")).toBeInTheDocument();
    expect(showToast).toHaveBeenCalledWith("Drafted 1 answer. Read each one before you apply.", "info");
  });

  it("hides the AI button until a local model is set, and marks applied", async () => {
    vi.mocked(getApplication).mockResolvedValue(draft({ llmReady: false }));
    vi.mocked(applyToPosting).mockResolvedValue({} as never);
    render(ApplyReview, { params: { id: "7" } });
    await screen.findByRole("heading", { name: "Discord: SWE Intern" });
    expect(screen.queryByRole("button", { name: /local AI/ })).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Mark as applied" }));
    expect(await screen.findByText("Applied")).toBeInTheDocument();
    expect(applyToPosting).toHaveBeenCalledWith(7);
  });

  it("shows why the form couldn't be read, and retries", async () => {
    const { ApiError } = await import("../lib/api/client");
    vi.mocked(getApplication).mockRejectedValueOnce(new ApiError(422, "The job board says this job no longer exists"));
    render(ApplyReview, { params: { id: "7" } });
    expect((await screen.findByRole("alert")).textContent).toContain("no longer exists");
    await fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Discord: SWE Intern" })).toBeInTheDocument();
  });
});
