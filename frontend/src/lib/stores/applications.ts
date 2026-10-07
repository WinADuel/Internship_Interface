import { writable } from "svelte/store";
import { archiveApplication, changeStatus, listApplications } from "../api/applications";
import type { Application, ApplicationStatus } from "../types/application";

export const applications = writable<Application[]>([]);

export async function loadApplications(): Promise<void> {
  applications.set(await listApplications(false));
}

/** Replaces the application with the same id, or appends it when it is new. */
export function upsertApplication(application: Application): void {
  applications.update((all) =>
    all.some((a) => a.id === application.id)
      ? all.map((a) => (a.id === application.id ? application : a))
      : [...all, application],
  );
}

/** Archives on the server, then drops the application from the active list (the store holds active ones only). */
export async function archiveAndRemoveApplication(id: number): Promise<void> {
  await archiveApplication(id);
  applications.update((all) => all.filter((a) => a.id !== id));
}

/**
 * Optimistically moves an application to `newStatus`, then persists it.
 * On failure the previous status is restored and the error is rethrown so the
 * caller can surface it (e.g. via showToast).
 */
export async function moveApplicationStatus(id: number, newStatus: ApplicationStatus): Promise<void> {
  let previous: ApplicationStatus | undefined;
  applications.update((all) =>
    all.map((a) => {
      if (a.id !== id) return a;
      previous = a.status;
      return { ...a, status: newStatus };
    }),
  );
  try {
    const updated = await changeStatus(id, newStatus);
    applications.update((all) => all.map((a) => (a.id === id ? updated : a)));
  } catch (err) {
    // Revert only if no later move has taken over this card.
    if (previous !== undefined) {
      const restore = previous;
      applications.update((all) =>
        all.map((a) => (a.id === id && a.status === newStatus ? { ...a, status: restore } : a)),
      );
    }
    throw err;
  }
}
