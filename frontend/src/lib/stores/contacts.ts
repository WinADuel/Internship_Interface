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

/** Undo window for a status button, matching the backend's 60 s (spec §13.3). */
export const UNDO_WINDOW_MS = 60_000;

/**
 * When each contact's last button press stops being undoable (epoch ms).
 * Kept outside the card so the Undo button survives the card moving to a
 * new board column.
 */
export const undoDeadlines = writable<Record<number, number>>({});

export function markUndoable(id: number, now = Date.now()): void {
  undoDeadlines.update((all) => ({ ...all, [id]: now + UNDO_WINDOW_MS }));
}

export function clearUndoable(id: number): void {
  undoDeadlines.update((all) => {
    const { [id]: _removed, ...rest } = all;
    return rest;
  });
}
