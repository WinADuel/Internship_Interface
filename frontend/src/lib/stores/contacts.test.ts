import { get } from "svelte/store";
import { afterEach, describe, expect, it, vi } from "vitest";
import { contacts, replaceContact, runContactAction } from "./contacts";
import { toasts } from "./toast";
import { fakeContact } from "../testing/fixtures";
import { ApiError } from "../api/client";
import * as api from "../api/contacts";

afterEach(() => {
  vi.restoreAllMocks();
  contacts.set([]);
  toasts.set([]);
});

describe("contacts store", () => {
  it("replaceContact swaps by id or prepends", () => {
    contacts.set([fakeContact({ id: 1 })]);
    replaceContact(fakeContact({ id: 1, name: "New" }));
    replaceContact(fakeContact({ id: 2 }));
    expect(get(contacts).map((c) => [c.id, c.name])).toEqual([[2, "Jane Lee"], [1, "New"]]);
  });

  it("runContactAction replaces the contact on success", async () => {
    contacts.set([fakeContact({ id: 1 })]);
    vi.spyOn(api, "applyContactAction").mockResolvedValue(fakeContact({ id: 1, status: "sent" }));
    const result = await runContactAction(1, "sent");
    expect(result?.status).toBe("sent");
    expect(get(contacts)[0].status).toBe("sent");
  });

  it("runContactAction toasts the API detail and returns null", async () => {
    vi.spyOn(api, "applyContactAction").mockRejectedValue(new ApiError(422, "cannot apply 'accepted'"));
    expect(await runContactAction(1, "accepted")).toBeNull();
    expect(get(toasts).map((t) => t.text)).toEqual(["cannot apply 'accepted'"]);
  });
});
