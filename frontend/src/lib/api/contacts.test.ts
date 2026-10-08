import { afterEach, describe, expect, it, vi } from "vitest";
import {
  applyContactAction,
  listContacts,
  mapContactFromApi,
  updateContact,
} from "./contacts";
import { addQueueItem } from "./researchQueue";
import { createClaudeToken, updateSettings } from "./settings";
import { fakeContact } from "../testing/fixtures";

const rawContact = {
  id: 1, kind: "professor", name: "Jane Lee", organization: "Stanford", department: null, title: null,
  lab_name: null, email: null, email_confidence: "pattern_guess", website_url: null, profile_url: null,
  application_id: null, relevance_note: null, research_summary: null, recent_work: null,
  sources: [{ label: "Faculty page", url: "https://cs.stanford.edu/~jlee" }],
  draft_subject: null, draft_body: null, draft_edited: false, followup_subject: null, followup_body: null,
  followup_edited: false, draft_ready_at: "2026-10-01T09:00:00Z", status: "to_contact", closed_reason: null,
  priority: "medium", sent_at: null, followed_up_at: null, replied_at: null, meeting_at: null,
  nudge_snoozed_until: null, notes: null, origin: "manual", archived: false,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", nudge: null,
};

function mockFetch(body: unknown, status = 200) {
  const fn = vi.fn().mockImplementation(
    async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

function sentBody(fn: ReturnType<typeof vi.fn>) {
  return JSON.parse(fn.mock.calls[0][1].body as string);
}

afterEach(() => vi.unstubAllGlobals());

describe("contacts api", () => {
  it("maps snake_case fields including email_confidence, draft_ready_at and sources", () => {
    const c = mapContactFromApi(rawContact);
    expect(c.emailConfidence).toBe("pattern_guess");
    expect(c.draftReadyAt).toBe("2026-10-01T09:00:00Z");
    expect(c.sources).toEqual([{ label: "Faculty page", url: "https://cs.stanford.edu/~jlee" }]);
    expect(c).toEqual(
      fakeContact({
        emailConfidence: "pattern_guess",
        draftReadyAt: "2026-10-01T09:00:00Z",
        sources: [{ label: "Faculty page", url: "https://cs.stanford.edu/~jlee" }],
      }),
    );
  });

  it("builds list query params", async () => {
    const fn = mockFetch([rawContact]);
    await listContacts({ kind: "company", applicationId: 7 });
    expect(fn.mock.calls[0][0]).toBe("/api/contacts?kind=company&application_id=7");
    await listContacts();
    expect(fn.mock.calls[1][0]).toBe("/api/contacts");
  });

  it("sends actions with optional dates in snake_case", async () => {
    const fn = mockFetch(rawContact);
    await applyContactAction(1, "meeting_set", { meetingAt: "2026-10-09T15:00:00.000Z" });
    expect(fn.mock.calls[0][0]).toBe("/api/contacts/1/actions");
    expect(sentBody(fn)).toEqual({ action: "meeting_set", meeting_at: "2026-10-09T15:00:00.000Z" });
  });

  it("patches only provided fields, in snake_case", async () => {
    const fn = mockFetch(rawContact);
    await updateContact(1, { draftBody: "hi", followupSubject: "Re" });
    expect(fn.mock.calls[0][1].method).toBe("PATCH");
    expect(sentBody(fn)).toEqual({ draft_body: "hi", followup_subject: "Re" });
  });

  it("queue and settings clients map field names", async () => {
    let fn = mockFetch({ id: 3, kind: "professor_search", request_text: "x", target_count: 5 });
    const item = await addQueueItem({ kind: "professor_search", requestText: "x", targetCount: 5 });
    expect(sentBody(fn)).toEqual({ kind: "professor_search", request_text: "x", target_count: 5 });
    expect(item.requestText).toBe("x");
    fn = mockFetch({ nudge_followup_days: 7 });
    expect((await updateSettings({ nudgeFollowupDays: 7 })).nudgeFollowupDays).toBe(7);
    expect(sentBody(fn)).toEqual({ nudge_followup_days: 7 });
    mockFetch({ id: 1, token_prefix: "ct_abcde", token: "ct_secret" });
    expect((await createClaudeToken()).tokenPrefix).toBe("ct_abcde");
  });
});
