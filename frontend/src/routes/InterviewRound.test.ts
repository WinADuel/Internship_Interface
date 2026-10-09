import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { get } from "svelte/store";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("svelte-spa-router", () => ({ push }));
vi.mock("../lib/api/interviews", () => ({
  getRound: vi.fn(),
  updateRound: vi.fn(),
  deleteRound: vi.fn(),
  setRoundContacts: vi.fn(),
  setRoundStories: vi.fn(),
  getBrief: vi.fn(),
  requestBrief: vi.fn(),
  createRound: vi.fn(),
  calendarUrl: (id: number) => `/api/interviews/${id}/calendar.ics`,
}));
vi.mock("../lib/api/stories", () => ({ listStories: vi.fn(), createStory: vi.fn(), updateStory: vi.fn() }));
vi.mock("../lib/api/contacts", () => ({ listContacts: vi.fn(), createContact: vi.fn() }));
vi.mock("../lib/api/applications", () => ({ getApplication: vi.fn() }));
vi.mock("../lib/api/settings", () => ({ getSettings: vi.fn() }));
vi.mock("../lib/api/researchQueue", () => ({ listQueue: vi.fn() }));

import { getApplication } from "../lib/api/applications";
import { ApiError } from "../lib/api/client";
import { createContact, listContacts } from "../lib/api/contacts";
import {
  deleteRound,
  getBrief,
  getRound,
  requestBrief,
  setRoundContacts,
  setRoundStories,
  updateRound,
} from "../lib/api/interviews";
import { listQueue } from "../lib/api/researchQueue";
import { getSettings } from "../lib/api/settings";
import { createStory, listStories } from "../lib/api/stories";
import { gmailComposeUrl } from "../lib/contacts/gmail";
import { thankYouDraft } from "../lib/prep/prompts";
import { toasts } from "../lib/stores/toast";
import {
  fakeApplication,
  fakeBrief,
  fakeContact,
  fakeRoundDetail,
  fakeStory,
} from "../lib/testing/fixtures";
import type { InterviewRoundDetail } from "../lib/types/interview";
import InterviewRound from "./InterviewRound.svelte";

const CHECKLIST = [
  { id: "a", label: "Research the company", done: true },
  { id: "b", label: "Pick stories", done: false },
];

function round(overrides: Partial<InterviewRoundDetail> = {}) {
  return fakeRoundDetail({
    id: 5,
    applicationId: 9,
    company: "Globex",
    roleTitle: "Data Intern",
    kind: "technical",
    title: "Coding round",
    scheduledAt: new Date(2026, 9, 11, 14, 0).toISOString(),
    durationMinutes: 45,
    format: "video",
    location: "https://meet.example.com/abc",
    interviewers: "Ana Lee",
    checklist: CHECKLIST,
    prepNotes: "Know SQL",
    contacts: [{ id: 3, name: "Ana Lee", email: "ana@globex.com", title: "Engineer" }],
    stories: [{ id: 1, title: "Outage at 2am" }],
    ...overrides,
  });
}

let clipboard: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 9, 9, 9, 0));
  toasts.set([]);
  push.mockReset();
  vi.mocked(getRound).mockReset().mockResolvedValue(round());
  vi.mocked(updateRound).mockReset().mockImplementation(async (_id, data) => ({ ...round(), ...data }) as InterviewRoundDetail);
  vi.mocked(getApplication).mockReset().mockResolvedValue(fakeApplication({ id: 9, jobLink: "https://globex.example.com/job" }));
  vi.mocked(getSettings).mockReset().mockResolvedValue({ outreachProfile: "CS junior" } as never);
  vi.mocked(listContacts).mockReset().mockResolvedValue([
    fakeContact({ id: 3, name: "Ana Lee", kind: "company", applicationId: 9, email: "ana@globex.com" }),
    fakeContact({ id: 4, name: "Bo Chen", kind: "company", applicationId: 9, title: "Manager" }),
  ]);
  vi.mocked(listStories).mockReset().mockResolvedValue([
    fakeStory({ id: 1, title: "Outage at 2am", result: "Back up in 20 minutes" }),
    fakeStory({ id: 2, title: "Team conflict" }),
  ]);
  vi.mocked(getBrief).mockReset().mockResolvedValue(null);
  vi.mocked(listQueue).mockReset().mockResolvedValue([]);
  for (const fn of [requestBrief, setRoundContacts, setRoundStories, createStory, createContact, deleteRound]) vi.mocked(fn).mockReset();
  clipboard = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText: clipboard }, configurable: true });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (err: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const checked = (label: string) => (screen.getByLabelText(label) as HTMLInputElement).checked;

async function open(id = "5") {
  const view = render(InterviewRound, { props: { params: { id } } });
  await screen.findByRole("heading", { level: 1 });
  return view;
}

describe("prep page header", () => {
  it("shows the company, role, round, time with countdown, format and a meeting link", async () => {
    await open();
    expect(getRound).toHaveBeenCalledWith(5);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Globex — Data Intern");
    expect(screen.getByText(/^Coding round/)).toBeInTheDocument();
    expect(screen.getByText("(in 2 days)")).toBeInTheDocument();
    expect(screen.getByText("45 minutes")).toBeInTheDocument();
    expect(screen.getByText("Video")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "https://meet.example.com/abc" });
    expect(link.getAttribute("href")).toBe("https://meet.example.com/abc");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    const cal = screen.getByRole("link", { name: "Add to calendar" });
    expect(cal.getAttribute("href")).toBe("/api/interviews/5/calendar.ics");
    expect(cal.hasAttribute("download")).toBe(true);
  });

  it("shows a non-http location as text and no calendar link without a date", async () => {
    vi.mocked(getRound).mockResolvedValue(round({ location: "javascript:alert(1)", scheduledAt: null }));
    await open();
    expect(screen.getByText("javascript:alert(1)").tagName).toBe("DD");
    expect(screen.queryByRole("link", { name: /javascript/ })).toBeNull();
    expect(screen.getByText("Not scheduled yet")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Add to calendar" })).toBeNull();
  });

  it("says when the round doesn't exist", async () => {
    vi.mocked(getRound).mockRejectedValue(new ApiError(404, "interview round not found"));
    render(InterviewRound, { props: { params: { id: "77" } } });
    expect(await screen.findByText(/doesn't exist/)).toBeInTheDocument();
  });

  it("edits the round and deletes it", async () => {
    await open();
    await fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const form = screen.getByRole("form", { name: "Edit round" });
    expect((within(form).getByLabelText("Title") as HTMLInputElement).value).toBe("Coding round");
    await fireEvent.input(within(form).getByLabelText("Title"), { target: { value: "Coding round 2" } });
    await fireEvent.submit(form);
    await vi.waitFor(() => expect(updateRound).toHaveBeenCalledWith(5, expect.objectContaining({ title: "Coding round 2", durationMinutes: 45, format: "video" })));
    expect(await screen.findByText(/^Coding round 2/)).toBeInTheDocument();

    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(deleteRound).mockResolvedValue(undefined);
    await fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    await fireEvent.click(screen.getByRole("button", { name: "Delete round" }));
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith("/interviews"));
    expect(deleteRound).toHaveBeenCalledWith(5);
  });
});

describe("checklist and notes", () => {
  it("ticks an item, adds one without an id and removes one", async () => {
    await open();
    expect(screen.getByRole("heading", { name: /Checklist/ }).textContent).toContain("1/2");
    await fireEvent.click(screen.getByLabelText("Pick stories"));
    expect(updateRound).toHaveBeenLastCalledWith(5, {
      checklist: [
        { id: "a", label: "Research the company", done: true },
        { id: "b", label: "Pick stories", done: true },
      ],
    });
    await fireEvent.input(screen.getByLabelText("New checklist item"), { target: { value: "Charge laptop" } });
    await fireEvent.submit(screen.getByRole("form", { name: "Add checklist item" }));
    expect(vi.mocked(updateRound).mock.lastCall?.[1].checklist?.at(-1)).toEqual({ label: "Charge laptop", done: false });
    await fireEvent.click(screen.getByRole("button", { name: "Remove “Research the company”" }));
    expect(vi.mocked(updateRound).mock.lastCall?.[1].checklist?.map((i) => i.label)).not.toContain("Research the company");
  });

  it("puts a ticked item back when saving fails", async () => {
    vi.mocked(updateRound).mockRejectedValue(new Error("offline"));
    await open();
    const box = screen.getByLabelText("Pick stories") as HTMLInputElement;
    await fireEvent.click(box);
    await vi.waitFor(() => expect((screen.getByLabelText("Pick stories") as HTMLInputElement).checked).toBe(false));
    expect(get(toasts).map((t) => t.text)).toEqual(["offline"]);
  });

  it("autosaves prep notes and questions on blur", async () => {
    await open();
    const notes = screen.getByLabelText("Prep notes") as HTMLTextAreaElement;
    expect(notes.value).toBe("Know SQL");
    await fireEvent.input(notes, { target: { value: "Know SQL and Python" } });
    await fireEvent.blur(notes);
    await vi.waitFor(() => expect(updateRound).toHaveBeenCalledWith(5, { prepNotes: "Know SQL and Python" }));
    const questions = screen.getByLabelText("Questions to ask");
    await fireEvent.input(questions, { target: { value: "What does a good first month look like?" } });
    await fireEvent.blur(questions);
    await vi.waitFor(() => expect(updateRound).toHaveBeenCalledWith(5, { questionsToAsk: "What does a good first month look like?" }));
  });
});

describe("stories and interviewers", () => {
  it("adds a story from the bank and removes a linked one", async () => {
    vi.mocked(setRoundStories).mockResolvedValue(round({ stories: [{ id: 1, title: "Outage at 2am" }, { id: 2, title: "Team conflict" }] }));
    await open();
    const picker = screen.getByLabelText("Add a story from the bank") as HTMLSelectElement;
    await vi.waitFor(() => expect([...picker.options].map((o) => o.textContent)).toContain("Team conflict"));
    expect([...picker.options].map((o) => o.textContent)).not.toContain("Outage at 2am");
    await fireEvent.change(picker, { target: { value: "2" } });
    expect(setRoundStories).toHaveBeenCalledWith(5, [1, 2]);
    expect(await screen.findByText("Team conflict", { selector: "summary" })).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Remove story “Outage at 2am”" }));
    expect(setRoundStories).toHaveBeenLastCalledWith(5, [2]);
  });

  it("shows a linked story's STAR text from the bank", async () => {
    await open();
    expect(await screen.findByText("Back up in 20 minutes")).toBeInTheDocument();
  });

  it("writes a new story inline and links it", async () => {
    vi.mocked(createStory).mockResolvedValue(fakeStory({ id: 8, title: "Hackathon win" }));
    vi.mocked(setRoundStories).mockResolvedValue(round({ stories: [{ id: 1, title: "Outage at 2am" }, { id: 8, title: "Hackathon win" }] }));
    await open();
    await fireEvent.click(screen.getByRole("button", { name: "Write a new story" }));
    const form = screen.getByRole("form", { name: "New story" });
    await fireEvent.input(within(form).getByLabelText("Title"), { target: { value: "Hackathon win" } });
    await fireEvent.submit(form);
    await vi.waitFor(() => expect(setRoundStories).toHaveBeenCalledWith(5, [1, 8]));
    expect(createStory).toHaveBeenCalledWith(expect.objectContaining({ title: "Hackathon win" }));
  });

  it("links an existing contact of the application as an interviewer", async () => {
    vi.mocked(setRoundContacts).mockResolvedValue(round());
    await open();
    const picker = await screen.findByLabelText("Add an interviewer from this application's contacts");
    expect([...(picker as HTMLSelectElement).options].map((o) => o.textContent)).toEqual(["Add from contacts…", "Bo Chen — Manager"]);
    await fireEvent.change(picker, { target: { value: "4" } });
    expect(setRoundContacts).toHaveBeenCalledWith(5, [3, 4]);
  });

  it("creates a new interviewer as a company contact of the application", async () => {
    vi.mocked(createContact).mockResolvedValue(fakeContact({ id: 11, name: "Cy Park" }));
    vi.mocked(setRoundContacts).mockResolvedValue(round());
    await open();
    await fireEvent.click(screen.getByRole("button", { name: "Add interviewer" }));
    const form = screen.getByRole("form", { name: "New interviewer" });
    await fireEvent.submit(form);
    expect(within(form).getByRole("alert").textContent).toBe("Name is required.");
    await fireEvent.input(within(form).getByLabelText("Name"), { target: { value: "Cy Park" } });
    await fireEvent.input(within(form).getByLabelText("Email"), { target: { value: "cy@globex.com" } });
    await fireEvent.submit(form);
    await vi.waitFor(() => expect(setRoundContacts).toHaveBeenCalledWith(5, [3, 11]));
    expect(createContact).toHaveBeenCalledWith({
      kind: "company", name: "Cy Park", organization: "Globex", title: null, email: "cy@globex.com", applicationId: 9,
    });
    await vi.waitFor(() => expect(screen.queryByRole("form", { name: "New interviewer" })).toBeNull());
  });
});

describe("company brief", () => {
  it("renders the brief as plain text with only http(s) source links", async () => {
    vi.mocked(getBrief).mockResolvedValue(
      fakeBrief({
        body: "Globex makes widgets.\n<script>alert(1)</script><img src=x onerror=alert(1)>",
        sources: [
          { label: "About Globex", url: "https://globex.example.com/about" },
          { label: "Sneaky", url: "javascript:alert(1)" },
        ],
      }),
    );
    const { container } = await open();
    expect(await screen.findByText(/Globex makes widgets\./)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("section script")).toBeNull();
    expect(screen.getByRole("link", { name: "About Globex" }).getAttribute("href")).toBe("https://globex.example.com/about");
    expect(screen.queryByRole("link", { name: "Sneaky" })).toBeNull();
    expect(screen.getByText("Sneaky").tagName).toBe("SPAN");
    expect(screen.getByRole("button", { name: "Ask Claude for a fresh brief" })).toBeInTheDocument();
  });

  it("requests a brief and shows it as pending", async () => {
    vi.mocked(requestBrief).mockResolvedValue("requested");
    await open();
    await fireEvent.click(await screen.findByRole("button", { name: "Ask Claude for a brief" }));
    expect(requestBrief).toHaveBeenCalledWith(9);
    expect(await screen.findByText("Requested — the daily run picks it up.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Ask Claude/ })).toBeNull();
  });

  it("shows a request still waiting in the queue as pending", async () => {
    vi.mocked(listQueue).mockResolvedValue([
      { id: 1, kind: "interview_brief", requestText: "x", applicationId: 9, targetCount: 1, state: "pending", resultNote: null, createdAt: "", completedAt: null },
    ]);
    await open();
    expect(await screen.findByText("Requested — the daily run picks it up.")).toBeInTheDocument();
    expect(listQueue).toHaveBeenCalledWith("pending");
  });
});

describe("Claude prompts", () => {
  it("copies filled prompts, with the story titles in the mock interview", async () => {
    await open();
    await vi.waitFor(() => expect(getApplication).toHaveBeenCalled());
    await fireEvent.click(screen.getByRole("button", { name: "Copy Company research prompt" }));
    await vi.waitFor(() => expect(clipboard).toHaveBeenCalled());
    expect(clipboard.mock.calls[0][0]).toContain("for the Data Intern role at Globex.\nJob posting: https://globex.example.com/job");
    await fireEvent.click(screen.getByRole("button", { name: "Copy Mock interview prompt" }));
    await vi.waitFor(() => expect(clipboard).toHaveBeenCalledTimes(2));
    expect(clipboard.mock.calls[1][0]).toContain("- Outage at 2am");
    expect(clipboard.mock.calls[1][0]).not.toContain("Know SQL");
    await fireEvent.click(screen.getByRole("button", { name: "Copy Tell me about yourself prompt" }));
    await vi.waitFor(() => expect(clipboard).toHaveBeenCalledTimes(3));
    expect(clipboard.mock.calls[2][0]).toContain("My background:\nCS junior\n");
    const titles = screen.getAllByRole("button", { name: /^Copy .* prompt$/ }).map((b) => b.getAttribute("aria-label"));
    expect(titles).toHaveLength(5);
  });
});

describe("after the interview", () => {
  it("marks the round done", async () => {
    await open();
    await fireEvent.click(screen.getByRole("button", { name: "Mark done" }));
    expect(updateRound).toHaveBeenCalledWith(5, { state: "done" });
    expect(await screen.findByLabelText("Outcome")).toBeInTheDocument();
  });

  it("drafts a thank-you in Gmail per interviewer and marks it sent", async () => {
    const done = round({ state: "done", scheduledAt: new Date(2026, 9, 8, 14).toISOString() });
    vi.mocked(getRound).mockResolvedValue(done);
    vi.mocked(updateRound).mockImplementation(async (_id, data) => ({ ...done, ...data }) as InterviewRoundDetail);
    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);
    await open();
    expect(screen.getByText(/Thank-you due/)).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Draft thank-you" }));
    const draft = thankYouDraft({ company: "Globex", roleTitle: "Data Intern", contactName: "Ana Lee" });
    expect(openSpy).toHaveBeenCalledWith(gmailComposeUrl("ana@globex.com", draft.subject, draft.body), "_blank", "noopener");
    await fireEvent.click(screen.getByRole("button", { name: "Mark sent" }));
    expect(updateRound).toHaveBeenLastCalledWith(5, { thankYouSentAt: new Date(2026, 9, 9, 9, 0).toISOString() });
    expect(await screen.findByText(/Thank-you sent/)).toBeInTheDocument();
  });

  it("asks before writing to a guessed address", async () => {
    vi.mocked(getRound).mockResolvedValue(round({ state: "done" }));
    vi.mocked(listContacts).mockResolvedValue([fakeContact({ id: 3, name: "Ana Lee", emailConfidence: "pattern_guess", applicationId: 9 })]);
    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    await open();
    await vi.waitFor(() => expect(listContacts).toHaveBeenCalled());
    await vi.waitFor(async () => {
      await fireEvent.click(screen.getByRole("button", { name: "Draft thank-you" }));
      expect(confirmSpy).toHaveBeenCalled();
    });
    expect(openSpy).not.toHaveBeenCalled();
  });

  it("sets the outcome and saves the reflection", async () => {
    vi.mocked(getRound).mockResolvedValue(round({ state: "done" }));
    await open();
    await fireEvent.change(screen.getByLabelText("Outcome"), { target: { value: "passed" } });
    expect(updateRound).toHaveBeenCalledWith(5, { outcome: "passed" });
    const reflection = screen.getByLabelText("How it went");
    await fireEvent.input(reflection, { target: { value: "Went well" } });
    await fireEvent.blur(reflection);
    await vi.waitFor(() => expect(updateRound).toHaveBeenCalledWith(5, { reflection: "Went well" }));
  });
});

describe("out-of-order saves", () => {
  it("drops an older answer that comes back after a newer one", async () => {
    const first = deferred<InterviewRoundDetail>();
    const second = deferred<InterviewRoundDetail>();
    vi.mocked(updateRound).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    await open();
    await fireEvent.click(screen.getByLabelText("Pick stories")); // tick
    await fireEvent.click(screen.getByLabelText("Research the company")); // untick
    const [, sent2] = vi.mocked(updateRound).mock.calls[1];
    second.resolve(round({ checklist: sent2.checklist as typeof CHECKLIST }));
    await vi.waitFor(() => expect(updateRound).toHaveBeenCalledTimes(2));
    first.resolve(round({ checklist: [{ ...CHECKLIST[0] }, { ...CHECKLIST[1], done: true }] }));
    await new Promise((r) => setTimeout(r, 0));
    expect(checked("Research the company")).toBe(false);
    expect(checked("Pick stories")).toBe(true);
  });

  it("keeps a newer checklist edit on screen while an older save's answer arrives", async () => {
    const first = deferred<InterviewRoundDetail>();
    const second = deferred<InterviewRoundDetail>();
    vi.mocked(updateRound).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    await open();
    await fireEvent.click(screen.getByLabelText("Pick stories"));
    await fireEvent.click(screen.getByLabelText("Research the company"));
    first.resolve(round({ checklist: [{ ...CHECKLIST[0] }, { ...CHECKLIST[1], done: true }] }));
    await new Promise((r) => setTimeout(r, 0));
    expect(checked("Research the company")).toBe(false);
    expect(checked("Pick stories")).toBe(true);
    const [, sent2] = vi.mocked(updateRound).mock.calls[1];
    second.resolve(round({ checklist: sent2.checklist as typeof CHECKLIST }));
    await new Promise((r) => setTimeout(r, 0));
    expect(checked("Research the company")).toBe(false);
    expect(checked("Pick stories")).toBe(true);
  });

  it("drops an older notes answer that arrives after a newer interviewer change", async () => {
    const notes = deferred<InterviewRoundDetail>();
    vi.mocked(updateRound).mockReturnValueOnce(notes.promise);
    vi.mocked(setRoundContacts).mockResolvedValue(round({ contacts: [] }));
    await open();
    const box = screen.getByLabelText("Prep notes");
    await fireEvent.input(box, { target: { value: "More SQL" } });
    await fireEvent.blur(box);
    await fireEvent.click(screen.getByRole("button", { name: "Remove interviewer Ana Lee" }));
    await vi.waitFor(() => expect(screen.getByText(/No interviewers linked\. Add them/)).toBeInTheDocument());
    notes.resolve(round({ prepNotes: "More SQL" }));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.getByText(/No interviewers linked\. Add them/)).toBeInTheDocument();
  });
});

describe("moving to another round", () => {
  it("saves the old round's unsaved notes to it and ignores its late answers", async () => {
    const late = deferred<InterviewRoundDetail>();
    vi.mocked(updateRound).mockReturnValueOnce(late.promise);
    const view = await open();
    await fireEvent.input(screen.getByLabelText("Prep notes"), { target: { value: "Unsaved for round 5" } });
    vi.mocked(getRound).mockResolvedValue(round({ id: 6, company: "Initech", prepNotes: "Round 6 notes" }));
    await view.rerender({ params: { id: "6" } });
    expect(updateRound).toHaveBeenCalledWith(5, { prepNotes: "Unsaved for round 5" });
    await vi.waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Initech — Data Intern"));
    expect(getRound).toHaveBeenLastCalledWith(6);
    late.resolve(round({ prepNotes: "Unsaved for round 5" }));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Initech — Data Intern");
    expect((screen.getByLabelText("Prep notes") as HTMLTextAreaElement).value).toBe("Round 6 notes");
  });
});

describe("after the interview: failures", () => {
  it("shows the saved outcome again when setting it fails", async () => {
    vi.mocked(getRound).mockResolvedValue(round({ state: "done", outcome: "waiting" }));
    vi.mocked(updateRound).mockRejectedValue(new Error("offline"));
    await open();
    const select = screen.getByLabelText("Outcome") as HTMLSelectElement;
    expect(select.value).toBe("waiting");
    await fireEvent.change(select, { target: { value: "passed" } });
    await vi.waitFor(() => expect(get(toasts).map((t) => t.text)).toEqual(["offline"]));
    expect(select.value).toBe("waiting");
  });

  it("offers a draft too long for a Gmail link for copying", async () => {
    const long = "Very Long Company Name ".repeat(100).trim();
    vi.mocked(getRound).mockResolvedValue(round({ state: "done", company: long }));
    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);
    await open();
    await fireEvent.click(screen.getByRole("button", { name: "Draft thank-you" }));
    expect(openSpy).not.toHaveBeenCalled();
    expect(get(toasts).map((t) => t.text)).toEqual(["Too long for a Gmail link — copy the draft and paste it into Gmail."]);
    const draft = thankYouDraft({ company: long, roleTitle: "Data Intern", contactName: "Ana Lee" });
    expect((screen.getByLabelText("Thank-you draft") as HTMLTextAreaElement).value).toBe(`Subject: ${draft.subject}\n\n${draft.body}`);
    await fireEvent.click(screen.getByRole("button", { name: "Copy draft" }));
    await vi.waitFor(() => expect(clipboard).toHaveBeenCalledWith(`Subject: ${draft.subject}\n\n${draft.body}`));
  });

  it("retries only the link after a new interviewer was created but not linked", async () => {
    vi.mocked(createContact).mockResolvedValue(fakeContact({ id: 11, name: "Cy Park" }));
    vi.mocked(setRoundContacts).mockRejectedValueOnce(new Error("offline")).mockResolvedValue(round());
    await open();
    await fireEvent.click(screen.getByRole("button", { name: "Add interviewer" }));
    const form = screen.getByRole("form", { name: "New interviewer" });
    await fireEvent.input(within(form).getByLabelText("Name"), { target: { value: "Cy Park" } });
    await fireEvent.submit(form);
    await vi.waitFor(() => expect(get(toasts).map((t) => t.text)).toEqual(["offline"]));
    expect(within(form).getByRole("status").textContent).toMatch(/not linked to this round yet/);
    await fireEvent.submit(form);
    await vi.waitFor(() => expect(setRoundContacts).toHaveBeenCalledTimes(2));
    expect(createContact).toHaveBeenCalledTimes(1);
    expect(setRoundContacts).toHaveBeenLastCalledWith(5, [3, 11]);
    await vi.waitFor(() => expect(screen.queryByRole("form", { name: "New interviewer" })).toBeNull());
  });
});

