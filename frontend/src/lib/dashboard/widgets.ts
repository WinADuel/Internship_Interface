import type { Application, ApplicationStatus } from "../types/application";

export type Bucket = "undone" | "workingOn" | "completed";

const DAY_MS = 24 * 60 * 60 * 1000;

const ALL_STATUSES: ApplicationStatus[] = ["wishlist", "applied", "phone_screen", "interview", "offer", "rejected"];

const BUCKET_OF: Record<ApplicationStatus, Bucket> = {
  wishlist: "undone",
  applied: "workingOn",
  phone_screen: "workingOn",
  interview: "workingOn",
  offer: "completed",
  rejected: "completed",
};

/** Parses a date-only "YYYY-MM-DD" string as a local calendar date. */
export function parseLocalDate(value: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!m) return null;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
}

function startOfLocalDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function addLocalDays(d: Date, days: number): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + days, d.getHours(), d.getMinutes(), d.getSeconds(), d.getMilliseconds());
}

/** The earliest qualifying reminder time for an application, or null. */
export function reminderTime(app: Application, withinDays: number, now: Date): number | null {
  const dayStart = startOfLocalDay(now);
  const followMax = addLocalDays(dayStart, withinDays).getTime();
  const interviewMax = now.getTime() + withinDays * DAY_MS;
  const candidates: number[] = [];

  if (app.followUpDate) {
    const d = parseLocalDate(app.followUpDate);
    if (d && d.getTime() >= dayStart.getTime() && d.getTime() <= followMax) candidates.push(d.getTime());
  }
  if (app.interviewDatetime) {
    const t = new Date(app.interviewDatetime).getTime();
    if (!Number.isNaN(t) && t >= now.getTime() && t <= interviewMax) candidates.push(t);
  }
  return candidates.length ? Math.min(...candidates) : null;
}

export function upcomingReminders(apps: Application[], withinDays: number, now: Date): Application[] {
  return apps
    .filter((a) => !a.archived)
    .map((a) => ({ a, t: reminderTime(a, withinDays, now) }))
    .filter((x): x is { a: Application; t: number } => x.t !== null)
    .sort((x, y) => x.t - y.t)
    .map((x) => x.a);
}

/**
 * Follow-ups whose date (a local calendar day) is before today, oldest first.
 * Archived applications and those already at offer or rejected are skipped:
 * there is nothing left to follow up on.
 */
export function overdueFollowUps(apps: Application[], now: Date): Application[] {
  const todayStart = startOfLocalDay(now).getTime();
  return apps
    .filter((a) => !a.archived && a.status !== "offer" && a.status !== "rejected")
    .map((a) => ({ a, t: a.followUpDate ? parseLocalDate(a.followUpDate)?.getTime() ?? null : null }))
    .filter((x): x is { a: Application; t: number } => x.t !== null && x.t < todayStart)
    .sort((x, y) => x.t - y.t)
    .map((x) => x.a);
}

export function bucketApplications(apps: Application[]): Record<Bucket, Application[]> {
  const out: Record<Bucket, Application[]> = { undone: [], workingOn: [], completed: [] };
  for (const a of apps) if (!a.archived) out[BUCKET_OF[a.status]].push(a);
  return out;
}

export function countByStatus(apps: Application[]): Record<ApplicationStatus, number> {
  const out = Object.fromEntries(ALL_STATUSES.map((s) => [s, 0])) as Record<ApplicationStatus, number>;
  for (const a of apps) if (!a.archived) out[a.status] += 1;
  return out;
}

export function statusLabel(status: ApplicationStatus): string {
  const text = status.replace("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function relativeTime(iso: string, now: Date = new Date()): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const seconds = Math.round((t - now.getTime()) / 1000);
  const abs = Math.abs(seconds);
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  if (abs < 60) return rtf.format(seconds, "second");
  if (abs < 3600) return rtf.format(Math.round(seconds / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(seconds / 3600), "hour");
  return rtf.format(Math.round(seconds / 86400), "day");
}
