import { writable } from "svelte/store";
import { applyContactAction, listContacts } from "../api/contacts";
import { ApiError } from "../api/client";
import { showToast } from "./toast";
import type { Contact, ContactAction, ContactKind } from "../types/contact";

export const contacts = writable<Contact[]>([]);

export async function loadContacts(kind?: ContactKind): Promise<void> {
  contacts.set(await listContacts(kind ? { kind } : {}));
}

/** Replaces the contact with the same id, or prepends it when it is new. */
export function replaceContact(updated: Contact): void {
  contacts.update((all) =>
    all.some((c) => c.id === updated.id)
      ? all.map((c) => (c.id === updated.id ? updated : c))
      : [updated, ...all],
  );
}

/** Runs a status button; on an API error shows its detail and returns null. */
export async function runContactAction(
  id: number,
  action: ContactAction,
  opts?: { on?: string; meetingAt?: string },
): Promise<Contact | null> {
  try {
    const updated = await applyContactAction(id, action, opts);
    replaceContact(updated);
    return updated;
  } catch (err) {
    if (err instanceof ApiError) {
      showToast(err.message);
      return null;
    }
    throw err;
  }
}
