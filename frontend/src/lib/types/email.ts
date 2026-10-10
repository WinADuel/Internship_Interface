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
/** `stale` suggestions are never listed, so the frontend doesn't see that state. */
export type SuggestionState = "pending" | "accepted" | "dismissed" | "auto_applied";
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
}

/** Optional Accept details: an interview's round as edited, or a new application's names. */
export interface AcceptInput {
  round?: Partial<InterviewRoundFields>;
  company?: string;
  roleTitle?: string;
}

export interface EmailStatus {
  gmailGranted: boolean;
  gmailSyncEnabled: boolean;
  gmailLastSyncAt: string | null;
  gmailLastError: string | null;
  pendingCount: number;
}

export interface EmailSyncResult extends EmailStatus {
  ok: boolean;
  fetched: number;
  suggested: number;
  autoApplied: number;
  more: boolean;
}
