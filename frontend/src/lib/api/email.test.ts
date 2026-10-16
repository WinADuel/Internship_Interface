import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./client";
import {
  acceptSuggestion,
  dismissSuggestion,
  getEmailHighlights,
  getEmailStatus,
  listGmailAccounts,
  listSuggestions,
  mapSuggestionFromApi,
  removeGmailAccount,
  syncEmailNow,
} from "./email";

const rawSuggestion = {
  id: 7, gmail_message_id: "m7", gmail_thread_id: "t7", gmail_url: "https://mail.google.com/mail/u/0/#all/t7",
  received_at: "2026-10-08T15:00:00Z", direction: "inbound", from_name: "Acme Recruiting", from_email: "jobs@acme.com",
  subject: "Interview with Acme", snippet: "Please share your availability", kind: "interview", state: "pending",
  application_id: 3, contact_id: null, proposed_company: null, proposed_role: null, round_kind: "technical",
  application: { id: 3, company: "Acme", role_title: "SWE Intern", status: "applied", archived: false },
  contact: null, created_at: "2026-10-08T15:01:00Z", decided_at: null, account_email: "me@gmail.com",
};

const rawAccount = {
  id: 2, email: "you@school.edu", last_sync_at: "2026-10-09T08:00:00Z", last_error: null,
  created_at: "2026-10-05T10:00:00Z",
};
const account = {
  id: 2, email: "you@school.edu", lastSyncAt: "2026-10-09T08:00:00Z", lastError: null, createdAt: "2026-10-05T10:00:00Z",
};

const rawStatus = {
  gmail_granted: true, gmail_sync_enabled: true, gmail_last_sync_at: "2026-10-09T08:00:00Z",
  gmail_last_error: null, pending_count: 2, accounts: [rawAccount],
};

function mockFetch(body: unknown, status = 200) {
  const fn = vi.fn().mockImplementation(
    async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

function call(fn: ReturnType<typeof vi.fn>, i = 0) {
  const [url, init] = fn.mock.calls[i] as [string, RequestInit];
  return { url, method: init.method ?? "GET", body: init.body ? JSON.parse(init.body as string) : undefined };
}

afterEach(() => vi.unstubAllGlobals());

describe("mapSuggestionFromApi", () => {
  it("maps every field, including the nested application and contact", () => {
    const s = mapSuggestionFromApi({
      ...rawSuggestion,
      contact: { id: 5, name: "Dana", organization: "Acme", status: "sent" },
    });
    expect(s).toMatchObject({
      id: 7, gmailThreadId: "t7", gmailUrl: "https://mail.google.com/mail/u/0/#all/t7", direction: "inbound",
      fromName: "Acme Recruiting", fromEmail: "jobs@acme.com", subject: "Interview with Acme", kind: "interview",
      state: "pending", applicationId: 3, contactId: null, roundKind: "technical", decidedAt: null,
      accountEmail: "me@gmail.com",
    });
    expect(s.application).toEqual({ id: 3, company: "Acme", roleTitle: "SWE Intern", status: "applied", archived: false });
    expect(s.contact).toEqual({ id: 5, name: "Dana", organization: "Acme", status: "sent" });
  });

  it("tolerates missing text and links", () => {
    const s = mapSuggestionFromApi({ id: 1, kind: "offer", state: "pending", application: null, contact: null });
    expect(s).toMatchObject({
      subject: "", snippet: "", gmailUrl: "", applicationId: null, roundKind: null, accountEmail: null,
    });
  });
});

describe("listSuggestions", () => {
  it("asks for pending by default", async () => {
    const fn = mockFetch([rawSuggestion]);
    const rows = await listSuggestions();
    expect(call(fn).url).toBe("/api/email/suggestions?state=pending");
    expect(rows[0].subject).toBe("Interview with Acme");
  });

  it("passes the state, application and limit", async () => {
    const fn = mockFetch([]);
    await listSuggestions({ state: "all", applicationId: 3, limit: 50 });
    expect(call(fn).url).toBe("/api/email/suggestions?state=all&application_id=3&limit=50");
  });
});

describe("acceptSuggestion", () => {
  it("sends an empty body when there is nothing to edit", async () => {
    const fn = mockFetch({ ...rawSuggestion, state: "accepted" });
    const s = await acceptSuggestion(7);
    expect(call(fn)).toEqual({ url: "/api/email/suggestions/7/accept", method: "POST", body: {} });
    expect(s.state).toBe("accepted");
  });

  it("snake-cases the round's fields", async () => {
    const fn = mockFetch(rawSuggestion);
    await acceptSuggestion(7, {
      round: { kind: "technical", title: null, scheduledAt: "2026-10-12T17:00:00.000Z", durationMinutes: 45 },
    });
    expect(call(fn).body).toEqual({
      round: { kind: "technical", title: null, scheduled_at: "2026-10-12T17:00:00.000Z", duration_minutes: 45 },
    });
  });

  it("sends a new application's edited names", async () => {
    const fn = mockFetch(rawSuggestion);
    await acceptSuggestion(7, { company: "Rivian", roleTitle: "Software Intern" });
    expect(call(fn).body).toEqual({ company: "Rivian", role_title: "Software Intern" });
  });

  it("throws the server's 409 detail", async () => {
    mockFetch({ detail: "this suggestion no longer applies" }, 409);
    await expect(acceptSuggestion(7)).rejects.toMatchObject({
      status: 409,
      message: "this suggestion no longer applies",
    } satisfies Partial<ApiError>);
  });
});

describe("dismiss, status and sync", () => {
  it("dismisses", async () => {
    const fn = mockFetch({ ...rawSuggestion, state: "dismissed" });
    expect((await dismissSuggestion(7)).state).toBe("dismissed");
    expect(call(fn)).toMatchObject({ url: "/api/email/suggestions/7/dismiss", method: "POST" });
  });

  it("reads the status", async () => {
    mockFetch(rawStatus);
    expect(await getEmailStatus()).toEqual({
      gmailGranted: true, gmailSyncEnabled: true, gmailLastSyncAt: "2026-10-09T08:00:00Z",
      gmailLastError: null, pendingCount: 2, accounts: [account],
    });
  });

  it("reads a status without inboxes as an empty list", async () => {
    mockFetch({ ...rawStatus, accounts: undefined });
    expect((await getEmailStatus()).accounts).toEqual([]);
  });

  it("runs Sync now", async () => {
    const fn = mockFetch({ ...rawStatus, ok: true, fetched: 12, suggested: 2, auto_applied: 1, more: false });
    expect(await syncEmailNow()).toMatchObject({
      ok: true, fetched: 12, suggested: 2, autoApplied: 1, pendingCount: 2, accounts: [account],
    });
    expect(call(fn)).toMatchObject({ url: "/api/email/sync", method: "POST" });
  });
});

describe("highlights and inboxes", () => {
  it("asks for the highlights with a limit and maps every tab", async () => {
    const fn = mockFetch({
      gmail_granted: true,
      tabs: {
        replies: { count: 3, items: [{ ...rawSuggestion, kind: "contact_reply", contact_id: 5 }] },
        interview: { count: 1, items: [rawSuggestion] },
        offer: { count: 0, items: [] },
        rejection: { count: 2, items: [{ ...rawSuggestion, id: 8, kind: "rejection", state: "stale" }] },
      },
    });
    const h = await getEmailHighlights(8);
    expect(call(fn).url).toBe("/api/email/highlights?limit=8");
    expect(h.gmailGranted).toBe(true);
    expect(h.tabs.replies.count).toBe(3);
    expect(h.tabs.replies.items[0]).toMatchObject({ kind: "contact_reply", contactId: 5 });
    expect(h.tabs.interview.items[0].accountEmail).toBe("me@gmail.com");
    expect(h.tabs.offer).toEqual({ count: 0, items: [] });
    expect(h.tabs.rejection.items[0]).toMatchObject({ id: 8, state: "stale" });
  });

  it("tolerates missing tabs", async () => {
    mockFetch({ gmail_granted: false });
    const h = await getEmailHighlights();
    expect(h.gmailGranted).toBe(false);
    expect(h.tabs.replies).toEqual({ count: 0, items: [] });
    expect(h.tabs.rejection).toEqual({ count: 0, items: [] });
  });

  it("lists the inboxes", async () => {
    const fn = mockFetch([rawAccount, { ...rawAccount, id: 1, email: null }]);
    expect(await listGmailAccounts()).toEqual([account, { ...account, id: 1, email: null }]);
    expect(call(fn).url).toBe("/api/email/accounts");
  });

  it("removes an inbox", async () => {
    const fn = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fn);
    await expect(removeGmailAccount(2)).resolves.toBeUndefined();
    expect(call(fn)).toMatchObject({ url: "/api/email/accounts/2", method: "DELETE" });
  });
});
