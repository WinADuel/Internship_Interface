import { get } from "svelte/store";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/email", () => ({ getEmailStatus: vi.fn(), syncEmailNow: vi.fn() }));
vi.mock("../api/applications", () => ({ getApplication: vi.fn() }));
vi.mock("../api/contacts", () => ({ getContact: vi.fn() }));

import { getApplication } from "../api/applications";
import { getContact } from "../api/contacts";
import { getEmailStatus, syncEmailNow } from "../api/email";
import { fakeApplication, fakeContact, fakeEmailStatus, fakeSuggestion } from "../testing/fixtures";
import type { EmailSyncResult } from "../types/email";
import { applications } from "./applications";
import { contacts } from "./contacts";
import { afterAccept, emailStatus, refreshEmailStatus, runEmailSync, syncSummary } from "./email";

const result = (overrides: Partial<EmailSyncResult> = {}): EmailSyncResult => ({
  ...fakeEmailStatus(),
  ok: true,
  fetched: 0,
  suggested: 0,
  autoApplied: 0,
  more: false,
  ...overrides,
});

beforeEach(() => {
  emailStatus.set(null);
  applications.set([]);
  contacts.set([]);
  vi.mocked(getEmailStatus).mockReset().mockResolvedValue(fakeEmailStatus({ pendingCount: 2 }));
  vi.mocked(syncEmailNow).mockReset();
  vi.mocked(getApplication).mockReset();
  vi.mocked(getContact).mockReset();
});

describe("refreshEmailStatus", () => {
  it("stores the status, and keeps the old one on failure without throwing", async () => {
    expect(await refreshEmailStatus()).toMatchObject({ pendingCount: 2 });
    expect(get(emailStatus)?.pendingCount).toBe(2);
    vi.mocked(getEmailStatus).mockRejectedValue(new Error("offline"));
    expect(await refreshEmailStatus()).toBeNull();
    expect(get(emailStatus)?.pendingCount).toBe(2);
  });
});

describe("refreshEmailStatus ordering", () => {
  function deferred<T>() {
    let resolve!: (value: T) => void;
    const promise = new Promise<T>((r) => (resolve = r));
    return { promise, resolve };
  }

  it("an older answer that lands last doesn't overwrite a newer one", async () => {
    const first = deferred<ReturnType<typeof fakeEmailStatus>>();
    const second = deferred<ReturnType<typeof fakeEmailStatus>>();
    vi.mocked(getEmailStatus).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const before = refreshEmailStatus(); // e.g. the page opening
    const after = refreshEmailStatus(); // e.g. after a Dismiss
    second.resolve(fakeEmailStatus({ pendingCount: 1 }));
    expect(await after).toMatchObject({ pendingCount: 1 });
    first.resolve(fakeEmailStatus({ pendingCount: 2 }));
    expect(await before).toBeNull();
    expect(get(emailStatus)?.pendingCount).toBe(1);
  });

  it("a status request that started before Sync now finished doesn't undo its result", async () => {
    const slow = deferred<ReturnType<typeof fakeEmailStatus>>();
    vi.mocked(getEmailStatus).mockReturnValueOnce(slow.promise);
    vi.mocked(syncEmailNow).mockResolvedValue(result({ pendingCount: 5 }));
    const refresh = refreshEmailStatus();
    await runEmailSync();
    slow.resolve(fakeEmailStatus({ pendingCount: 2 }));
    expect(await refresh).toBeNull();
    expect(get(emailStatus)?.pendingCount).toBe(5);
  });
});

describe("afterAccept", () => {
  it("refreshes the application and contact the email changed", async () => {
    applications.set([fakeApplication({ id: 3, status: "applied" })]);
    contacts.set([fakeContact({ id: 5, status: "sent" })]);
    vi.mocked(getApplication).mockResolvedValue(fakeApplication({ id: 3, status: "interview" }));
    vi.mocked(getContact).mockResolvedValue(fakeContact({ id: 5, status: "replied" }));
    await afterAccept(fakeSuggestion({ applicationId: 3, contactId: 5 }));
    expect(get(applications)[0].status).toBe("interview");
    expect(get(contacts)[0].status).toBe("replied");
    expect(get(emailStatus)?.pendingCount).toBe(2);
  });

  it("never throws", async () => {
    vi.mocked(getApplication).mockRejectedValue(new Error("gone"));
    await expect(afterAccept(fakeSuggestion({ applicationId: 3 }))).resolves.toBeUndefined();
  });
});

describe("runEmailSync and syncSummary", () => {
  it("stores the new status from the sync", async () => {
    vi.mocked(syncEmailNow).mockResolvedValue(result({ pendingCount: 6, gmailLastSyncAt: "2026-10-09T09:00:00Z" }));
    await runEmailSync();
    expect(get(emailStatus)).toEqual(fakeEmailStatus({ pendingCount: 6, gmailLastSyncAt: "2026-10-09T09:00:00Z" }));
  });

  it("summarises the outcome", () => {
    expect(syncSummary(result({ fetched: 1, suggested: 1 }))).toBe("Checked 1 email: 1 update found.");
    expect(syncSummary(result({ fetched: 40, suggested: 3, autoApplied: 2, more: true }))).toBe(
      "Checked 40 emails: 3 updates found, 2 applied automatically. More mail is left for the next sync.",
    );
    expect(syncSummary(result({ ok: false, gmailLastError: "reconnect Google and allow Gmail" }))).toBe(
      "Gmail sync failed: reconnect Google and allow Gmail",
    );
  });
});
