import { apiFetch } from "./client";
import type {
  ActivityEntry,
  Application,
  ApplicationInput,
  ApplicationStatus,
  StatusHistoryEntry,
} from "../types/application";

type Raw = Record<string, unknown>;

const FIELD_MAP: ReadonlyArray<[keyof ApplicationInput, string]> = [
  ["company", "company"],
  ["roleTitle", "role_title"],
  ["dateApplied", "date_applied"],
  ["status", "status"],
  ["jobLink", "job_link"],
  ["notes", "notes"],
  ["resumeVersion", "resume_version"],
  ["contactPerson", "contact_person"],
  ["salaryRange", "salary_range"],
  ["location", "location"],
  ["source", "source"],
  ["priority", "priority"],
  ["followUpDate", "follow_up_date"],
  ["interviewDatetime", "interview_datetime"],
  ["googleDocLink", "google_doc_link"],
];

const JSON_HEADERS = { "Content-Type": "application/json" };

export function mapApplicationFromApi(raw: Raw): Application {
  return {
    id: raw.id as number,
    company: raw.company as string,
    roleTitle: raw.role_title as string,
    dateApplied: (raw.date_applied as string | null) ?? null,
    status: raw.status as ApplicationStatus,
    jobLink: (raw.job_link as string | null) ?? null,
    notes: (raw.notes as string | null) ?? null,
    resumeVersion: (raw.resume_version as string | null) ?? null,
    contactPerson: (raw.contact_person as string | null) ?? null,
    salaryRange: (raw.salary_range as string | null) ?? null,
    location: (raw.location as string | null) ?? null,
    source: (raw.source as string | null) ?? null,
    priority: raw.priority as Application["priority"],
    followUpDate: (raw.follow_up_date as string | null) ?? null,
    interviewDatetime: (raw.interview_datetime as string | null) ?? null,
    googleDocLink: (raw.google_doc_link as string | null) ?? null,
    archived: raw.archived as boolean,
    createdAt: raw.created_at as string,
    updatedAt: raw.updated_at as string,
  };
}

/** camelCase -> snake_case; only keys present on `data` are emitted (safe for PATCH). */
export function mapApplicationInputToApi(data: Partial<ApplicationInput>): Raw {
  const out: Raw = {};
  for (const [camel, snake] of FIELD_MAP) {
    if (camel in data) out[snake] = data[camel];
  }
  return out;
}

export async function listApplications(includeArchived = false): Promise<Application[]> {
  const raw = await apiFetch<Raw[]>(`/api/applications?include_archived=${includeArchived}`);
  return raw.map(mapApplicationFromApi);
}

export async function getApplication(id: number): Promise<Application> {
  return mapApplicationFromApi(await apiFetch<Raw>(`/api/applications/${id}`));
}

export async function createApplication(data: ApplicationInput): Promise<Application> {
  const raw = await apiFetch<Raw>("/api/applications", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(mapApplicationInputToApi(data)),
  });
  return mapApplicationFromApi(raw);
}

/** `interviewDatetime` can't be edited: it is derived from the interview rounds (Phase 4). */
export async function updateApplication(
  id: number,
  data: Partial<Omit<ApplicationInput, "interviewDatetime">>,
): Promise<Application> {
  const body = mapApplicationInputToApi(data);
  delete body.interview_datetime;
  const raw = await apiFetch<Raw>(`/api/applications/${id}`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
  return mapApplicationFromApi(raw);
}

export async function changeStatus(id: number, newStatus: ApplicationStatus): Promise<Application> {
  const raw = await apiFetch<Raw>(`/api/applications/${id}/status`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ new_status: newStatus }),
  });
  return mapApplicationFromApi(raw);
}

export async function archiveApplication(id: number): Promise<Application> {
  return mapApplicationFromApi(await apiFetch<Raw>(`/api/applications/${id}/archive`, { method: "POST" }));
}

function toStatusOrNull(value: unknown): ApplicationStatus | null {
  return (value as ApplicationStatus | null) ?? null;
}

export async function getStatusHistory(id: number): Promise<StatusHistoryEntry[]> {
  const raw = await apiFetch<Raw[]>(`/api/applications/${id}/history`);
  return raw.map((r) => ({
    oldStatus: toStatusOrNull(r.old_status),
    newStatus: r.new_status as ApplicationStatus,
    changedAt: r.changed_at as string,
  }));
}

export async function getRecentActivity(limit = 10): Promise<ActivityEntry[]> {
  const raw = await apiFetch<Raw[]>(`/api/applications/activity?limit=${limit}`);
  return raw.map((r) => ({
    applicationId: r.application_id as number,
    company: r.company as string,
    roleTitle: r.role_title as string,
    oldStatus: toStatusOrNull(r.old_status),
    newStatus: r.new_status as ApplicationStatus,
    changedAt: r.changed_at as string,
  }));
}
