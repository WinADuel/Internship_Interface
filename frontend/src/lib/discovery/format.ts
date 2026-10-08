import { parseLocalDate } from "../dashboard/widgets";
import type { Posting, PostingSource } from "../types/discovery";

/** Display names for posting sources; mirrors backend `app/services/discovery/labels.py`. */
export const SOURCE_LABELS: Record<PostingSource, string> = {
  simplify: "Simplify",
  vanshb03: "vanshb03 list",
  list: "Community list",
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  workday: "Workday",
  pasted: "Pasted",
};

export function sourceLabel(source: PostingSource): string {
  return SOURCE_LABELS[source] ?? source;
}

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

function localDayNumber(d: Date): number {
  // Calendar day index of the local date; UTC arithmetic avoids DST-length days.
  return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / 86_400_000;
}

/**
 * How long ago a posting went up, by local calendar days: "today", "1 day ago",
 * "N days ago" under two weeks, then whole "N weeks ago". A future date reads
 * "today"; no date or an unparseable one gives "".
 */
export function postedAgo(date: string | null, now: Date = new Date()): string {
  if (!date) return "";
  const posted = DATE_ONLY.test(date) ? parseLocalDate(date) : new Date(date);
  if (!posted || Number.isNaN(posted.getTime())) return "";
  const days = Math.max(0, localDayNumber(now) - localDayNumber(posted));
  if (days === 0) return "today";
  if (days === 1) return "1 day ago";
  if (days < 14) return `${days} days ago`;
  return `${Math.floor(days / 7)} weeks ago`;
}

/** "Company – Title", used in button labels, confirms and toasts. */
export function postingLabel(posting: Pick<Posting, "company" | "title">): string {
  return `${posting.company} – ${posting.title}`;
}

/** "Posted N days ago" from the source's date, else "Found N days ago" from the first scan that saw it. */
export function postingWhen(posting: Pick<Posting, "datePosted" | "firstSeenAt">, now: Date = new Date()): string {
  const posted = postedAgo(posting.datePosted, now);
  if (posted) return `Posted ${posted}`;
  const found = postedAgo(posting.firstSeenAt, now);
  return found ? `Found ${found}` : "";
}

/** The first two locations, then "+N more" for the rest. */
export function shortLocations(locations: string[]): string {
  const shown = locations.slice(0, 2).join(", ");
  const rest = locations.length - 2;
  return rest > 0 ? `${shown} +${rest} more` : shown;
}

/** True only for an absolute http(s) URL; anything else never becomes a link. */
export function isWebUrl(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

/** Whether a list's sponsorship note is worth showing ("Other" says nothing). */
export function showsSponsorship(sponsorship: string | null): boolean {
  const note = sponsorship?.trim() ?? "";
  return note !== "" && note.toLowerCase() !== "other";
}

function plural(n: number, unit: string): string {
  return `${n} ${unit}${n === 1 ? "" : "s"} ago`;
}

/**
 * How long ago an instant was: "just now" under a minute (or in the future),
 * then whole minutes, hours and days; from a week on, the local date.
 * Unparseable input gives "".
 */
export function timeAgo(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  const minutes = Math.floor((now.getTime() - then.getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return plural(minutes, "minute");
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return plural(hours, "hour");
  const days = Math.floor(hours / 24);
  if (days < 7) return plural(days, "day");
  return then.toLocaleDateString();
}
