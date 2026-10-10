// String unions mirror the backend enums exactly (Phase 4 spec §3).
export type InterviewKind =
  | "recruiter_screen"
  | "technical"
  | "behavioral"
  | "case"
  | "onsite"
  | "final"
  | "other";
export type InterviewFormat = "video" | "phone" | "in_person";
export type InterviewState = "scheduled" | "done" | "cancelled";
export type InterviewOutcome = "waiting" | "passed" | "rejected";
export type InterviewScope = "upcoming" | "past" | "all";

export interface ChecklistItem {
  id: string;
  label: string;
  done: boolean;
}

/** A checklist item as sent to the API: a new item has no id yet (the server assigns one). */
export interface ChecklistItemInput {
  id?: string;
  label: string;
  done: boolean;
}

/** One interview round as stored. */
export interface InterviewRound {
  id: number;
  applicationId: number;
  kind: InterviewKind;
  title: string | null;
  scheduledAt: string | null;
  durationMinutes: number | null;
  format: InterviewFormat | null;
  location: string | null;
  interviewers: string | null;
  state: InterviewState;
  outcome: InterviewOutcome | null;
  prepNotes: string | null;
  questionsToAsk: string | null;
  reflection: string | null;
  checklist: ChecklistItem[];
  thankYouSentAt: string | null;
  createdAt: string;
  updatedAt: string;
}

/** A round in `GET /api/interviews`: the round plus its application and progress. */
export interface InterviewRoundListItem extends InterviewRound {
  company: string;
  roleTitle: string;
  checklistDone: number;
  checklistTotal: number;
  thankYouDue: boolean;
}

/** A tracked contact linked to a round as an interviewer. */
export interface RoundContact {
  id: number;
  name: string;
  email: string | null;
  title: string | null;
}

export interface RoundStory {
  id: number;
  title: string;
}

/** `GET /api/interviews/{id}`: the list fields plus linked interviewers and stories. */
export interface InterviewRoundDetail extends InterviewRoundListItem {
  contacts: RoundContact[];
  stories: RoundStory[];
}

/** Fields a user may set on a round (create and PATCH). */
export interface InterviewRoundFields {
  kind: InterviewKind;
  title: string | null;
  scheduledAt: string | null;
  durationMinutes: number | null;
  format: InterviewFormat | null;
  location: string | null;
  interviewers: string | null;
  state: InterviewState;
  outcome: InterviewOutcome | null;
  prepNotes: string | null;
  questionsToAsk: string | null;
  reflection: string | null;
  checklist: ChecklistItemInput[];
  thankYouSentAt: string | null;
}

/** POST body: an omitted checklist gets the default one. */
export type InterviewRoundInput = Partial<InterviewRoundFields> & { applicationId: number };

/** PATCH body: omitted means unchanged. */
export type InterviewRoundUpdate = Partial<InterviewRoundFields>;

export interface Story {
  id: number;
  title: string;
  situation: string | null;
  task: string | null;
  action: string | null;
  result: string | null;
  tags: string[];
  archived: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface StoryInput {
  title: string;
  situation: string | null;
  task: string | null;
  action: string | null;
  result: string | null;
  tags: string[];
}

export type StoryUpdate = Partial<StoryInput> & { archived?: boolean };

export interface BriefSource {
  label: string;
  url: string;
}

/** The Claude-written company brief for an application (untrusted text). */
export interface PrepBrief {
  body: string;
  sources: BriefSource[];
  createdAt: string;
  updatedAt: string;
}
