import { parseLocalDate } from "../dashboard/widgets";
import type { PostingSource } from "../types/discovery";

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
