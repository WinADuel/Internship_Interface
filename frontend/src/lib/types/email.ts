import type { ApplicationStatus } from "./application";
import type { ContactStatus } from "./contact";
import type { InterviewKind, InterviewRoundFields } from "./interview";

// String unions mirror the backend enums exactly (Phase 6 spec §4, §5).
export type SuggestionKind =
  | "confirmation"
  | "rejection"
  | "interview"
  | "assessment"
  | "offer"
  | "contact_reply"
  | "contact_sent"
  | "new_application";
/** `stale` (out of date) appears only in the Dashboard's email highlights; the suggestion lists leave it out. */
export type SuggestionState = "pending" | "accepted" | "dismissed" | "auto_applied" | "stale";
export type SuggestionFilter = "pending" | "decided" | "all";
export type EmailDirection = "inbound" | "sent";

export interface SuggestionApplication {
  id: number;
  company: string;
  roleTitle: string;
  status: ApplicationStatus;
  archived: boolean;
}

export interface SuggestionContact {
  id: number;
  name: string;
  organization: string;
  status: ContactStatus;
}

/** One email Gmail sync matched. Sender, subject and snippet are untrusted email text: render as text. */
export interface EmailSuggestion {
  id: number;
  gmailMessageId: string;
  gmailThreadId: string;
  gmailUrl: string;
  receivedAt: string;
  direction: EmailDirection;
  fromName: string;
  fromEmail: string;
  subject: string;
  snippet: string;
  kind: SuggestionKind;
  state: SuggestionState;
  applicationId: number | null;
  contactId: number | null;
  proposedCompany: string | null;
  proposedRole: string | null;
  /** The round kind to prefill for an interview suggestion. */
  roundKind: InterviewKind | null;
  application: SuggestionApplication | null;
  contact: SuggestionContact | null;
  createdAt: string;
  decidedAt: string | null;
  /** The connected inbox the email was found in; null when its address isn't known yet. */
  accountEmail: string | null;
}

/** Optional Accept details: an interview's round as edited, or a new application's names. */
export interface AcceptInput {
  round?: Partial<InterviewRoundFields>;
  company?: string;
  roleTitle?: string;
}

/** One connected Gmail inbox (Phase 7 spec §4). */
export interface GmailAccount {
  id: number;
  /** Null only for an inbox carried over from before Phase 7, until its next sync reads the address. */
  email: string | null;
  lastSyncAt: string | null;
  lastError: string | null;
  createdAt: string;
}

export interface EmailStatus {
  /** True when at least one inbox is connected. */
  gmailGranted: boolean;
  gmailSyncEnabled: boolean;
  gmailLastSyncAt: string | null;
  gmailLastError: string | null;
  pendingCount: number;
  /** The connected inboxes, oldest first. */
  accounts: GmailAccount[];
}

export interface EmailSyncResult extends EmailStatus {
  ok: boolean;
  fetched: number;
  suggested: number;
  autoApplied: number;
  more: boolean;
}

/** The Dashboard's Email replies tabs: replies from contacts, then three application kinds. */
export type HighlightTab = "replies" | "interview" | "offer" | "rejection";

export interface HighlightList {
  /** Every match, of which `items` are the newest few. */
  count: number;
  items: EmailSuggestion[];
}

export interface EmailHighlights {
  gmailGranted: boolean;
  tabs: Record<HighlightTab, HighlightList>;
}
