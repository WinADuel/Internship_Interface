import { afterEach, describe, expect, it, vi } from "vitest";
import {
  calendarUrl,
  createRound,
  deleteRound,
  getBrief,
  getRound,
  listRounds,
  requestBrief,
  setRoundContacts,
  setRoundStories,
  updateRound,
} from "./interviews";
import { createStory, listStories, updateStory } from "./stories";
import { fakeRoundDetail, fakeRoundListItem, fakeStory } from "../testing/fixtures";

const rawRound = {
  id: 4, application_id: 9, kind: "behavioral", title: "Team fit", scheduled_at: "2026-10-12T15:00:00Z",
  duration_minutes: 45, format: "video", location: "https://meet.example.com/x", interviewers: "Sam",
  state: "scheduled", outcome: null, prep_notes: "notes", questions_to_ask: "q", reflection: null,
  checklist: [{ id: "a", label: "Research", done: true }, { id: "b", label: "Stories", done: false }],
  thank_you_sent_at: null, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-02T00:00:00Z",
};
const rawListItem = { ...rawRound, company: "Globex", role_title: "Data Intern", checklist_done: 1, checklist_total: 2, thank_you_due: false };

function mockFetch(body: unknown, status = 200) {
  const fn = vi.fn().mockImplementation(
    async () =>
      status === 204
        ? new Response(null, { status })
        : new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

const sentBody = (fn: ReturnType<typeof vi.fn>, call = 0) => JSON.parse(fn.mock.calls[call][1].body as string);

afterEach(() => vi.unstubAllGlobals());

describe("interviews api", () => {
  it("lists rounds with scope and application filters, mapping list fields", async () => {
    const fn = mockFetch([rawListItem]);
    const [round] = await listRounds({ scope: "upcoming", applicationId: 9 });
    expect(fn.mock.calls[0][0]).toBe("/api/interviews?scope=upcoming&application_id=9");
    expect(round).toEqual(
      fakeRoundListItem({
        id: 4, applicationId: 9, kind: "behavioral", title: "Team fit", scheduledAt: "2026-10-12T15:00:00Z",
        durationMinutes: 45, format: "video", location: "https://meet.example.com/x", interviewers: "Sam",
        prepNotes: "notes", questionsToAsk: "q",
        checklist: [{ id: "a", label: "Research", done: true }, { id: "b", label: "Stories", done: false }],
        updatedAt: "2026-10-02T00:00:00Z", company: "Globex", roleTitle: "Data Intern", checklistDone: 1,
        checklistTotal: 2,
      }),
    );
    await listRounds();
    expect(fn.mock.calls[1][0]).toBe("/api/interviews?scope=all");
  });

  it("maps a single round with its interviewers and stories", async () => {
    mockFetch({ ...rawListItem, contacts: [{ id: 3, name: "Ana", email: "ana@globex.com", title: null }], stories: [{ id: 2, title: "Outage" }] });
    const round = await getRound(4);
    expect(round.contacts).toEqual([{ id: 3, name: "Ana", email: "ana@globex.com", title: null }]);
    expect(round.stories).toEqual([{ id: 2, title: "Outage" }]);
    expect(round.company).toBe("Globex");
  });

  it("defaults missing optional fields instead of leaving undefined", async () => {
    mockFetch({ id: 1, application_id: 1, kind: "technical", state: "scheduled", created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z" });
    expect(await getRound(1)).toEqual(fakeRoundDetail({ company: "", roleTitle: "" }));
  });

  it("creates and patches in snake_case, sending only the given keys", async () => {
    const fn = mockFetch(rawRound);
    await createRound({ applicationId: 9, kind: "technical", scheduledAt: "2026-10-12T15:00:00.000Z" });
    expect(fn.mock.calls[0][0]).toBe("/api/interviews");
    expect(fn.mock.calls[0][1].method).toBe("POST");
    expect(sentBody(fn)).toEqual({ application_id: 9, kind: "technical", scheduled_at: "2026-10-12T15:00:00.000Z" });
    const updated = await updateRound(4, { prepNotes: "x", thankYouSentAt: null, checklist: [{ label: "New", done: false }] });
    expect(fn.mock.calls[1][0]).toBe("/api/interviews/4");
    expect(fn.mock.calls[1][1].method).toBe("PATCH");
    expect(sentBody(fn, 1)).toEqual({ prep_notes: "x", thank_you_sent_at: null, checklist: [{ label: "New", done: false }] });
    expect(updated.prepNotes).toBe("notes");
  });

  it("deletes, replaces linked contacts and stories, and builds the calendar link", async () => {
    let fn = mockFetch(null, 204);
    await deleteRound(4);
    expect(fn.mock.calls[0]).toEqual(["/api/interviews/4", expect.objectContaining({ method: "DELETE" })]);
    fn = mockFetch(rawRound);
    await setRoundContacts(4, [3, 5]);
    expect(fn.mock.calls[0][0]).toBe("/api/interviews/4/contacts");
    expect(fn.mock.calls[0][1].method).toBe("PUT");
    expect(sentBody(fn)).toEqual({ contact_ids: [3, 5] });
    await setRoundStories(4, [2]);
    expect(fn.mock.calls[1][0]).toBe("/api/interviews/4/stories");
    expect(sentBody(fn, 1)).toEqual({ story_ids: [2] });
    expect(calendarUrl(4)).toBe("/api/interviews/4/calendar.ics");
  });

  it("returns null when an application has no brief, and caps what it maps", async () => {
    mockFetch({ detail: "no brief" }, 404);
    expect(await getBrief(9)).toBeNull();
    const fn = mockFetch({
      body: "x".repeat(20_000),
      sources: Array.from({ length: 30 }, (_, i) => ({ label: `S${i}`, url: `https://s${i}.example.com` })),
      created_at: "2026-10-05T00:00:00Z",
      updated_at: "2026-10-06T00:00:00Z",
    });
    const brief = await getBrief(9);
    expect(fn.mock.calls[0][0]).toBe("/api/applications/9/brief");
    expect(brief?.body).toHaveLength(12_000);
    expect(brief?.sources).toHaveLength(20);
    expect(brief?.updatedAt).toBe("2026-10-06T00:00:00Z");
  });

  it("rethrows other brief errors", async () => {
    mockFetch({ detail: "boom" }, 500);
    await expect(getBrief(9)).rejects.toThrow("boom");
  });

  it("requests a brief; a 409 means one is already pending", async () => {
    let fn = mockFetch({ id: 1 }, 202);
    expect(await requestBrief(9)).toBe("requested");
    expect(fn.mock.calls[0]).toEqual(["/api/applications/9/brief/request", expect.objectContaining({ method: "POST" })]);
    fn = mockFetch({ detail: "already pending" }, 409);
    expect(await requestBrief(9)).toBe("pending");
    mockFetch({ detail: "no such application" }, 404);
    await expect(requestBrief(9)).rejects.toThrow("no such application");
  });
});

describe("stories api", () => {
  const rawStory = {
    id: 2, title: "Outage", situation: "s", task: "t", action: "a", result: "r", tags: ["ownership"], archived: false,
    created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
  };

  it("lists with tag and archived filters", async () => {
    const fn = mockFetch([rawStory]);
    const [story] = await listStories();
    expect(fn.mock.calls[0][0]).toBe("/api/stories");
    expect(story).toEqual(fakeStory({ id: 2, title: "Outage", situation: "s", task: "t", action: "a", result: "r", tags: ["ownership"] }));
    await listStories({ tag: "conflict", includeArchived: true });
    expect(fn.mock.calls[1][0]).toBe("/api/stories?tag=conflict&include_archived=true");
  });

  it("creates and patches in snake_case", async () => {
    const fn = mockFetch(rawStory);
    await createStory({ title: "Outage", situation: null, task: null, action: null, result: null, tags: ["x"] });
    expect(sentBody(fn)).toEqual({ title: "Outage", situation: null, task: null, action: null, result: null, tags: ["x"] });
    await updateStory(2, { archived: true });
    expect(fn.mock.calls[1][0]).toBe("/api/stories/2");
    expect(fn.mock.calls[1][1].method).toBe("PATCH");
    expect(sentBody(fn, 1)).toEqual({ archived: true });
  });
});
