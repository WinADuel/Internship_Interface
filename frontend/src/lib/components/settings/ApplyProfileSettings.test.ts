import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/apply", () => ({
  getApplyProfile: vi.fn(),
  updateApplyProfile: vi.fn(),
  uploadResume: vi.fn(),
  deleteResume: vi.fn(),
  listExtensionTokens: vi.fn(),
  createExtensionToken: vi.fn(),
  revokeExtensionToken: vi.fn(),
}));
vi.mock("../../stores/toast", () => ({ showToast: vi.fn() }));

import { getApplyProfile, listExtensionTokens, updateApplyProfile, uploadResume } from "../../api/apply";
import { showToast } from "../../stores/toast";
import type { ApplyProfile, ApplyProfileFields } from "../../types/apply";
import ApplyProfileSettings from "./ApplyProfileSettings.svelte";

const BLANK = Object.fromEntries(
  [
    "first_name", "last_name", "preferred_name", "email", "phone", "city", "state", "country", "linkedin_url",
    "github_url", "website_url", "current_company", "school", "degree", "major", "gpa", "graduation_month",
    "graduation_year", "work_authorized", "needs_sponsorship", "willing_to_relocate", "how_heard", "pronouns",
    "gender", "race", "hispanic_latino", "veteran", "disability", "lgbtq",
  ].map((k) => [k, ""]),
) as unknown as ApplyProfileFields;

function profile(overrides: Partial<ApplyProfile> = {}): ApplyProfile {
  return {
    fields: { ...BLANK, first_name: "Dana" },
    savedAnswers: [{ question: "Why us?", answer: "Because." }],
    resumeFilename: null,
    resumeUploadedAt: null,
    llmUrl: "",
    llmModel: "",
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(getApplyProfile).mockReset().mockResolvedValue(profile());
  vi.mocked(updateApplyProfile).mockReset().mockImplementation(async (data) => profile({ fields: data.fields! }));
  vi.mocked(uploadResume).mockReset();
  vi.mocked(listExtensionTokens).mockReset().mockResolvedValue([]);
  vi.mocked(showToast).mockReset();
});

describe("ApplyProfileSettings", () => {
  it("loads and saves the profile, saved answers and local AI", async () => {
    render(ApplyProfileSettings);
    const first = (await screen.findByLabelText("First name")) as HTMLInputElement;
    expect(first.value).toBe("Dana");
    await fireEvent.input(screen.getByLabelText("School"), { target: { value: "University of Washington" } });
    await fireEvent.change(screen.getByLabelText("Will need visa sponsorship"), { target: { value: "no" } });
    await fireEvent.input(screen.getByLabelText("Gender"), { target: { value: "decline" } });
    await fireEvent.input(screen.getByLabelText("Address"), { target: { value: "http://10.0.0.5:11434" } });
    await fireEvent.click(screen.getByRole("button", { name: "Add an answer" }));
    await fireEvent.submit(screen.getByRole("form", { name: "Apply profile" }));
    await vi.waitFor(() => expect(updateApplyProfile).toHaveBeenCalled());
    const sent = vi.mocked(updateApplyProfile).mock.calls[0][0];
    expect(sent.fields).toMatchObject({ first_name: "Dana", school: "University of Washington", needs_sponsorship: "no", gender: "decline" });
    expect(sent.savedAnswers).toEqual([{ question: "Why us?", answer: "Because." }]); // the blank new one is dropped
    expect(sent.llmUrl).toBe("http://10.0.0.5:11434");
    expect(showToast).toHaveBeenCalledWith("Apply profile saved.", "info");
  });

  it("uploads a resume", async () => {
    vi.mocked(uploadResume).mockResolvedValue(profile({ resumeFilename: "Resume.pdf", resumeUploadedAt: "2026-11-05T10:00:00Z" }));
    render(ApplyProfileSettings);
    const input = (await screen.findByLabelText(/Upload \(PDF or Word/)) as HTMLInputElement;
    const file = new File(["%PDF"], "Resume.pdf", { type: "application/pdf" });
    await fireEvent.change(input, { target: { files: [file] } });
    await vi.waitFor(() => expect(uploadResume).toHaveBeenCalledWith(file));
    expect(await screen.findByText(/Resume\.pdf/)).toBeInTheDocument();
  });

  it("includes the extension tokens", async () => {
    render(ApplyProfileSettings);
    expect(await screen.findByRole("heading", { name: "Chrome extension tokens" })).toBeInTheDocument();
  });
});
