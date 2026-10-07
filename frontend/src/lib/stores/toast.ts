import { writable } from "svelte/store";

export interface ToastMessage {
  id: number;
  text: string;
  kind: "error" | "info";
}

export const toasts = writable<ToastMessage[]>([]);

let nextId = 1;

export function dismissToast(id: number): void {
  toasts.update((all) => all.filter((t) => t.id !== id));
}

export function showToast(text: string, kind: ToastMessage["kind"] = "error"): void {
  const id = nextId++;
  toasts.update((all) => [...all, { id, text, kind }]);
  setTimeout(() => dismissToast(id), 5000);
}
