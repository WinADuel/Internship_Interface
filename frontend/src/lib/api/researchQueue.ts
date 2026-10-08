import { apiFetch } from "./client";
import { keysToCamel } from "./case";
import type { QueueItem, QueueItemInput, QueueState } from "../types/contact";

type Raw = Record<string, unknown>;

export async function listQueue(state?: QueueState): Promise<QueueItem[]> {
  const raw = await apiFetch<Raw[]>(`/api/research-queue${state ? `?state=${state}` : ""}`);
  return raw.map((r) => keysToCamel<QueueItem>(r));
}

export async function addQueueItem(data: QueueItemInput): Promise<QueueItem> {
  const raw = await apiFetch<Raw>("/api/research-queue", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind: data.kind, request_text: data.requestText, target_count: data.targetCount }),
  });
  return keysToCamel<QueueItem>(raw);
}

export async function findContacts(applicationId: number): Promise<QueueItem> {
  const raw = await apiFetch<Raw>(`/api/research-queue/find-contacts/${applicationId}`, { method: "POST" });
  return keysToCamel<QueueItem>(raw);
}
