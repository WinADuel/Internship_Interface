import { apiFetch } from "./client";
import { keysToCamel, keysToSnake } from "./case";
import type {
  AcceptInput,
  EmailStatus,
  EmailSuggestion,
  EmailSyncResult,
  SuggestionApplication,
  SuggestionContact,
  SuggestionFilter,
} from "../types/email";

type Raw = Record<string, unknown>;

const JSON_HEADERS = { "Content-Type": "application/json" };
const str = (v: unknown): string => (typeof v === "string" ? v : "");
const strOrNull = (v: unknown): string | null => (typeof v === "string" ? v : null);
const idOrNull = (v: unknown): number | null => (typeof v === "number" ? v : null);
const obj = (v: unknown): Raw | null => (v && typeof v === "object" ? (v as Raw) : null);

export function mapSuggestionFromApi(raw: Raw): EmailSuggestion {
  const application = obj(raw.application);
  const contact = obj(raw.contact);
  return {
    id: raw.id as number,
    gmailMessageId: str(raw.gmail_message_id),
    gmailThreadId: str(raw.gmail_thread_id),
    gmailUrl: str(raw.gmail_url),
    receivedAt: str(raw.received_at),
    direction: raw.direction === "sent" ? "sent" : "inbound",
    fromName: str(raw.from_name),
    fromEmail: str(raw.from_email),
    subject: str(raw.subject),
    snippet: str(raw.snippet),
    kind: raw.kind as EmailSuggestion["kind"],
    state: raw.state as EmailSuggestion["state"],
    applicationId: idOrNull(raw.application_id),
    contactId: idOrNull(raw.contact_id),
    proposedCompany: strOrNull(raw.proposed_company),
    proposedRole: strOrNull(raw.proposed_role),
    roundKind: (raw.round_kind as EmailSuggestion["roundKind"]) ?? null,
    application: application ? keysToCamel<SuggestionApplication>(application) : null,
    contact: contact ? keysToCamel<SuggestionContact>(contact) : null,
    createdAt: str(raw.created_at),
    decidedAt: strOrNull(raw.decided_at),
  };
}

export async function listSuggestions(
  opts: { state?: SuggestionFilter; applicationId?: number; limit?: number } = {},
): Promise<EmailSuggestion[]> {
  const params = new URLSearchParams();
  params.set("state", opts.state ?? "pending");
  if (opts.applicationId !== undefined) params.set("application_id", String(opts.applicationId));
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  const raw = await apiFetch<Raw[]>(`/api/email/suggestions?${params}`);
  return raw.map(mapSuggestionFromApi);
}

/** Accept; `data` carries an interview's round or a new application's edited names. */
export async function acceptSuggestion(id: number, data: AcceptInput = {}): Promise<EmailSuggestion> {
  const body: Raw = keysToSnake({ company: data.company, roleTitle: data.roleTitle });
  if (data.round) body.round = keysToSnake(data.round);
  const raw = await apiFetch<Raw>(`/api/email/suggestions/${id}/accept`, {
    method: "POST",
    headers: JSON_HEADERS,
    // undefined values drop out of the JSON, so only the fields given are sent.
    body: JSON.stringify(body),
  });
  return mapSuggestionFromApi(raw);
}

export async function dismissSuggestion(id: number): Promise<EmailSuggestion> {
  return mapSuggestionFromApi(await apiFetch<Raw>(`/api/email/suggestions/${id}/dismiss`, { method: "POST" }));
}

export async function getEmailStatus(): Promise<EmailStatus> {
  return keysToCamel<EmailStatus>(await apiFetch<Raw>("/api/email/status"));
}

/** Runs a Gmail sync now (synchronously) and returns its outcome with the new status. */
export async function syncEmailNow(): Promise<EmailSyncResult> {
  return keysToCamel<EmailSyncResult>(await apiFetch<Raw>("/api/email/sync", { method: "POST" }));
}

/** Where Connect Gmail goes: Google's consent for gmail.readonly, then back to Settings. */
export const CONNECT_GMAIL_URL = "/api/docs/google/authorize?gmail=1";
