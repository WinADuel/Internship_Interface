import { apiFetch } from "./client";
import { keysToCamel, keysToSnake } from "./case";
import type {
  AcceptInput,
  EmailHighlights,
  EmailStatus,
  EmailSuggestion,
  EmailSyncResult,
  GmailAccount,
  HighlightList,
  HighlightTab,
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
    accountEmail: strOrNull(raw.account_email),
  };
}

export function mapAccountFromApi(raw: Raw): GmailAccount {
  return {
    id: raw.id as number,
    email: strOrNull(raw.email),
    lastSyncAt: strOrNull(raw.last_sync_at),
    lastError: strOrNull(raw.last_error),
    createdAt: str(raw.created_at),
  };
}

const accountsFrom = (v: unknown): GmailAccount[] =>
  Array.isArray(v) ? v.filter((a) => obj(a) !== null).map((a) => mapAccountFromApi(a as Raw)) : [];

/** The status fields, with the inboxes mapped (an older server without `accounts` gives []). */
function mapStatusFromApi(raw: Raw): EmailStatus {
  return { ...keysToCamel<EmailStatus>(raw), accounts: accountsFrom(raw.accounts) };
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
  return mapStatusFromApi(await apiFetch<Raw>("/api/email/status"));
}

/** Runs a Gmail sync now (synchronously) and returns its outcome with the new status. */
export async function syncEmailNow(): Promise<EmailSyncResult> {
  const raw = await apiFetch<Raw>("/api/email/sync", { method: "POST" });
  return { ...keysToCamel<EmailSyncResult>(raw), accounts: accountsFrom(raw.accounts) };
}

const HIGHLIGHT_TABS: HighlightTab[] = ["replies", "interview", "offer", "rejection"];

function mapHighlightList(raw: Raw | null): HighlightList {
  const rows: unknown[] = raw && Array.isArray(raw.items) ? raw.items : [];
  const items = rows.filter((i) => obj(i) !== null).map((i) => mapSuggestionFromApi(i as Raw));
  return { count: typeof raw?.count === "number" ? raw.count : items.length, items };
}

/** The Dashboard's Email replies: each tab's newest `limit` emails (1–20) and its total. */
export async function getEmailHighlights(limit = 8): Promise<EmailHighlights> {
  const raw = await apiFetch<Raw>(`/api/email/highlights?limit=${limit}`);
  const tabs = obj(raw.tabs);
  return {
    gmailGranted: raw.gmail_granted === true,
    tabs: Object.fromEntries(HIGHLIGHT_TABS.map((t) => [t, mapHighlightList(obj(tabs?.[t]))])) as Record<
      HighlightTab,
      HighlightList
    >,
  };
}

/** The connected Gmail inboxes, oldest first. */
export async function listGmailAccounts(): Promise<GmailAccount[]> {
  return accountsFrom(await apiFetch<unknown>("/api/email/accounts"));
}

/** Disconnects one inbox; the server deletes its stored email updates. */
export async function removeGmailAccount(id: number): Promise<void> {
  await apiFetch<void>(`/api/email/accounts/${id}`, { method: "DELETE" });
}

/**
 * Where Connect Gmail, Add another inbox and Reconnect go: Google's account
 * chooser and consent for gmail.readonly, then back to Settings.
 */
export const CONNECT_GMAIL_URL = "/api/docs/google/authorize?gmail=1";
