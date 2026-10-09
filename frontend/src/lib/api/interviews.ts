import { ApiError, apiFetch } from "./client";
import { keysToSnake } from "./case";
import type {
  BriefSource,
  ChecklistItem,
  InterviewRound,
  InterviewRoundDetail,
  InterviewRoundInput,
  InterviewRoundListItem,
  InterviewRoundUpdate,
  InterviewScope,
  PrepBrief,
  RoundContact,
  RoundStory,
} from "../types/interview";

type Raw = Record<string, unknown>;

const JSON_HEADERS = { "Content-Type": "application/json" };

// Brief caps from spec §3; the server enforces them too, this is defence in depth.
const BRIEF_BODY_MAX = 12_000;
const BRIEF_SOURCES_MAX = 20;

const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

function mapChecklist(raw: unknown): ChecklistItem[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((item): item is Raw => !!item && typeof item === "object")
    .map((item) => ({ id: String(item.id ?? ""), label: String(item.label ?? ""), done: item.done === true }));
}

export function mapRoundFromApi(raw: Raw): InterviewRound {
  return {
    id: raw.id as number,
    applicationId: raw.application_id as number,
    kind: (raw.kind as InterviewRound["kind"]) ?? "other",
    title: str(raw.title),
    scheduledAt: str(raw.scheduled_at),
    durationMinutes: num(raw.duration_minutes),
    format: (raw.format as InterviewRound["format"]) ?? null,
    location: str(raw.location),
    interviewers: str(raw.interviewers),
    state: (raw.state as InterviewRound["state"]) ?? "scheduled",
    outcome: (raw.outcome as InterviewRound["outcome"]) ?? null,
    prepNotes: str(raw.prep_notes),
    questionsToAsk: str(raw.questions_to_ask),
    reflection: str(raw.reflection),
    checklist: mapChecklist(raw.checklist),
    thankYouSentAt: str(raw.thank_you_sent_at),
    createdAt: raw.created_at as string,
    updatedAt: raw.updated_at as string,
  };
}

export function mapRoundListItemFromApi(raw: Raw): InterviewRoundListItem {
  const round = mapRoundFromApi(raw);
  return {
    ...round,
    company: String(raw.company ?? ""),
    roleTitle: String(raw.role_title ?? ""),
    checklistDone: num(raw.checklist_done) ?? round.checklist.filter((i) => i.done).length,
    checklistTotal: num(raw.checklist_total) ?? round.checklist.length,
    thankYouDue: raw.thank_you_due === true,
  };
}

export function mapRoundDetailFromApi(raw: Raw): InterviewRoundDetail {
  const contacts: RoundContact[] = (Array.isArray(raw.contacts) ? (raw.contacts as Raw[]) : []).map((c) => ({
    id: c.id as number,
    name: String(c.name ?? ""),
    email: str(c.email),
    title: str(c.title),
  }));
  const stories: RoundStory[] = (Array.isArray(raw.stories) ? (raw.stories as Raw[]) : []).map((s) => ({
    id: s.id as number,
    title: String(s.title ?? ""),
  }));
  return { ...mapRoundListItemFromApi(raw), contacts, stories };
}

export async function listRounds(
  opts: { scope?: InterviewScope; applicationId?: number } = {},
): Promise<InterviewRoundListItem[]> {
  const params = new URLSearchParams();
  params.set("scope", opts.scope ?? "all");
  if (opts.applicationId !== undefined) params.set("application_id", String(opts.applicationId));
  const raw = await apiFetch<Raw[]>(`/api/interviews?${params}`);
  return raw.map(mapRoundListItemFromApi);
}

export async function getRound(id: number): Promise<InterviewRoundDetail> {
  return mapRoundDetailFromApi(await apiFetch<Raw>(`/api/interviews/${id}`));
}

export async function createRound(data: InterviewRoundInput): Promise<InterviewRound> {
  const raw = await apiFetch<Raw>("/api/interviews", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(keysToSnake(data)),
  });
  return mapRoundFromApi(raw);
}

/** PATCH; only the keys present on `data` are sent. */
export async function updateRound(id: number, data: InterviewRoundUpdate): Promise<InterviewRound> {
  const raw = await apiFetch<Raw>(`/api/interviews/${id}`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify(keysToSnake(data)),
  });
  return mapRoundFromApi(raw);
}

export async function deleteRound(id: number): Promise<void> {
  await apiFetch<void>(`/api/interviews/${id}`, { method: "DELETE" });
}

/** Replaces the round's tracked interviewers. */
export async function setRoundContacts(id: number, contactIds: number[]): Promise<void> {
  await apiFetch<unknown>(`/api/interviews/${id}/contacts`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify({ contact_ids: contactIds }),
  });
}

/** Replaces the stories planned for the round. */
export async function setRoundStories(id: number, storyIds: number[]): Promise<void> {
  await apiFetch<unknown>(`/api/interviews/${id}/stories`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify({ story_ids: storyIds }),
  });
}

/** Same-origin download of the round as an .ics file (cookie auth, so a plain link works). */
export function calendarUrl(id: number): string {
  return `/api/interviews/${id}/calendar.ics`;
}

export function mapBriefFromApi(raw: Raw): PrepBrief {
  const sources: BriefSource[] = (Array.isArray(raw.sources) ? (raw.sources as Raw[]) : [])
    .slice(0, BRIEF_SOURCES_MAX)
    .map((s) => ({ label: String(s?.label ?? ""), url: String(s?.url ?? "") }));
  return {
    body: String(raw.body ?? "").slice(0, BRIEF_BODY_MAX),
    sources,
    createdAt: raw.created_at as string,
    updatedAt: raw.updated_at as string,
  };
}

/** The application's company brief, or null when none has been written yet. */
export async function getBrief(applicationId: number): Promise<PrepBrief | null> {
  try {
    return mapBriefFromApi(await apiFetch<Raw>(`/api/applications/${applicationId}/brief`));
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

/** Queues a brief for the daily Claude run. "pending" when one is already queued (409). */
export async function requestBrief(applicationId: number): Promise<"requested" | "pending"> {
  try {
    await apiFetch<unknown>(`/api/applications/${applicationId}/brief/request`, { method: "POST" });
    return "requested";
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) return "pending";
    throw err;
  }
}
