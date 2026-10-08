import type { Priority } from "./application";

// String unions mirror the backend enums exactly.
export type ContactKind = "professor" | "company";
export type ContactStatus =
  | "to_contact"
  | "sent"
  | "followed_up"
  | "replied"
  | "meeting"
  | "accepted"
  | "declined";
export type EmailConfidence = "found" | "pattern_guess" | "not_found";
export type ContactOrigin = "claude" | "manual";
export type ContactAction =
  | "sent"
  | "followed_up"
  | "replied"
  | "meeting_set"
  | "accepted"
  | "declined"
  | "no_response";
export type NudgeKind = "unsent" | "followup_due" | "gone_quiet" | "replied_stale" | "meeting_outcome";
export type QueueKind = "professor_person" | "professor_search" | "company_contacts";
export type QueueState = "pending" | "done" | "failed";

export interface ContactSource {
  label: string;
  url: string;
}

export interface Contact {
  id: number;
  kind: ContactKind;
  name: string;
  organization: string;
  department: string | null;
  title: string | null;
  labName: string | null;
  email: string | null;
  emailConfidence: EmailConfidence;
  websiteUrl: string | null;
  profileUrl: string | null;
  applicationId: number | null;
  relevanceNote: string | null;
  researchSummary: string | null;
  recentWork: string | null;
  sources: ContactSource[];
  draftSubject: string | null;
  draftBody: string | null;
  draftEdited: boolean;
  followupSubject: string | null;
  followupBody: string | null;
  followupEdited: boolean;
  draftReadyAt: string | null;
  status: ContactStatus;
  closedReason: string | null;
  priority: Priority;
  sentAt: string | null;
  followedUpAt: string | null;
  repliedAt: string | null;
  meetingAt: string | null;
  nudgeSnoozedUntil: string | null;
  notes: string | null;
  origin: ContactOrigin;
  archived: boolean;
  createdAt: string;
  updatedAt: string;
  nudge: NudgeKind | null;
}

/** Fields a user may set when creating a contact. */
export interface ContactInput {
  kind: ContactKind;
  name: string;
  organization: string;
  department?: string | null;
  title?: string | null;
  labName?: string | null;
  email?: string | null;
  emailConfidence?: EmailConfidence;
  websiteUrl?: string | null;
  profileUrl?: string | null;
  priority?: Priority;
  notes?: string | null;
  applicationId?: number | null;
}

/** PATCH body: any user-editable field, including drafts. */
export type ContactUpdate = Partial<ContactInput> & {
  draftSubject?: string | null;
  draftBody?: string | null;
  followupSubject?: string | null;
  followupBody?: string | null;
};

export interface ContactHistoryEntry {
  oldStatus: ContactStatus | null;
  newStatus: ContactStatus;
  changedAt: string;
}

export interface ContactActivityEntry {
  contactId: number;
  name: string;
  organization: string;
  kind: ContactKind;
  oldStatus: ContactStatus | null;
  newStatus: ContactStatus;
  changedAt: string;
}

export interface QueueItem {
  id: number;
  kind: QueueKind;
  requestText: string;
  applicationId: number | null;
  targetCount: number;
  state: QueueState;
  resultNote: string | null;
  createdAt: string;
  completedAt: string | null;
}

export interface QueueItemInput {
  kind: "professor_person" | "professor_search";
  requestText: string;
  targetCount: number;
}

export interface AppSettings {
  outreachProfile: string;
  nudgeUnsentDays: number;
  nudgeFollowupDays: number;
  nudgeGoneQuietDays: number;
  nudgeRepliedStaleDays: number;
  claudeJobMaxItems: number;
  backupSheetId: string | null;
  lastSheetSyncAt: string | null;
  lastSheetSyncError: string | null;
}

export type AppSettingsUpdate = Partial<
  Pick<
    AppSettings,
    | "outreachProfile"
    | "nudgeUnsentDays"
    | "nudgeFollowupDays"
    | "nudgeGoneQuietDays"
    | "nudgeRepliedStaleDays"
    | "claudeJobMaxItems"
  >
>;

export interface ClaudeTokenInfo {
  id: number;
  tokenPrefix: string;
  createdAt: string;
  lastUsedAt: string | null;
  revokedAt: string | null;
}

export interface ClaudeTokenCreated extends ClaudeTokenInfo {
  token: string;
}

export interface SheetSyncResult {
  ok: boolean;
  lastSheetSyncAt: string | null;
  lastSheetSyncError: string | null;
  sheetUrl: string | null;
}
