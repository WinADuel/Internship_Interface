import { apiFetch } from "./client";
import { keysToCamel, keysToSnake } from "./case";
import type {
  Contact,
  ContactAction,
  ContactActivityEntry,
  ContactHistoryEntry,
  ContactInput,
  ContactKind,
  ContactSource,
  ContactStatus,
  ContactUpdate,
} from "../types/contact";

type Raw = Record<string, unknown>;

const JSON_HEADERS = { "Content-Type": "application/json" };

function post(body?: unknown): RequestInit {
  return body === undefined
    ? { method: "POST" }
    : { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) };
}

export function mapContactFromApi(raw: Raw): Contact {
  const contact = keysToCamel<Contact>(raw);
  const sources = Array.isArray(raw.sources) ? (raw.sources as ContactSource[]) : [];
  return {
    ...contact,
    sources: sources.map((s) => ({ label: String(s.label ?? ""), url: String(s.url ?? "") })),
    nudge: contact.nudge ?? null,
  };
}

export async function listContacts(
  opts: { kind?: ContactKind; applicationId?: number; includeArchived?: boolean } = {},
): Promise<Contact[]> {
  const params = new URLSearchParams();
  if (opts.kind) params.set("kind", opts.kind);
  if (opts.applicationId !== undefined) params.set("application_id", String(opts.applicationId));
  if (opts.includeArchived) params.set("include_archived", "true");
  const query = params.toString();
  const raw = await apiFetch<Raw[]>(`/api/contacts${query ? `?${query}` : ""}`);
  return raw.map(mapContactFromApi);
}

export async function getContact(id: number): Promise<Contact> {
  return mapContactFromApi(await apiFetch<Raw>(`/api/contacts/${id}`));
}

export async function createContact(data: ContactInput): Promise<Contact> {
  return mapContactFromApi(await apiFetch<Raw>("/api/contacts", post(keysToSnake(data))));
}

export async function updateContact(id: number, data: ContactUpdate): Promise<Contact> {
  const raw = await apiFetch<Raw>(`/api/contacts/${id}`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify(keysToSnake(data)),
  });
  return mapContactFromApi(raw);
}

export async function applyContactAction(
  id: number,
  action: ContactAction,
  opts: { on?: string; meetingAt?: string } = {},
): Promise<Contact> {
  const body: Raw = { action };
  if (opts.on) body.on = opts.on;
  if (opts.meetingAt) body.meeting_at = opts.meetingAt;
  return mapContactFromApi(await apiFetch<Raw>(`/api/contacts/${id}/actions`, post(body)));
}

export async function moveContactStatus(id: number, status: ContactStatus): Promise<Contact> {
  return mapContactFromApi(await apiFetch<Raw>(`/api/contacts/${id}/status`, post({ new_status: status })));
}

export async function undoContactAction(id: number): Promise<Contact> {
  return mapContactFromApi(await apiFetch<Raw>(`/api/contacts/${id}/undo`, post()));
}

export async function snoozeContact(id: number, days: number): Promise<Contact> {
  return mapContactFromApi(await apiFetch<Raw>(`/api/contacts/${id}/snooze`, post({ days })));
}

export async function archiveContact(id: number): Promise<Contact> {
  return mapContactFromApi(await apiFetch<Raw>(`/api/contacts/${id}/archive`, post()));
}

export async function getContactHistory(id: number): Promise<ContactHistoryEntry[]> {
  const raw = await apiFetch<Raw[]>(`/api/contacts/${id}/history`);
  return raw.map((r) => keysToCamel<ContactHistoryEntry>(r));
}

export async function getContactActivity(limit = 10): Promise<ContactActivityEntry[]> {
  const raw = await apiFetch<Raw[]>(`/api/contacts/activity?limit=${limit}`);
  return raw.map((r) => keysToCamel<ContactActivityEntry>(r));
}

export async function getNeedsAttention(): Promise<Contact[]> {
  const raw = await apiFetch<Raw[]>("/api/contacts/needs-attention");
  return raw.map(mapContactFromApi);
}
