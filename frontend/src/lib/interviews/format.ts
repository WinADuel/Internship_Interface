import type {
  InterviewFormat,
  InterviewKind,
  InterviewOutcome,
  InterviewRound,
  InterviewState,
} from "../types/interview";

export const KIND_LABELS: Record<InterviewKind, string> = {
  recruiter_screen: "Recruiter screen",
  technical: "Technical",
  behavioral: "Behavioral",
  case: "Case",
  onsite: "Onsite",
  final: "Final",
  other: "Interview",
};

export const FORMAT_LABELS: Record<InterviewFormat, string> = {
  video: "Video",
  phone: "Phone",
  in_person: "In person",
};

export const STATE_LABELS: Record<InterviewState, string> = {
  scheduled: "Scheduled",
  done: "Done",
  cancelled: "Cancelled",
};

export const OUTCOME_LABELS: Record<InterviewOutcome, string> = {
  waiting: "Waiting to hear",
  passed: "Passed",
  rejected: "Rejected",
};

export const INTERVIEW_KINDS = Object.keys(KIND_LABELS) as InterviewKind[];
export const INTERVIEW_FORMATS = Object.keys(FORMAT_LABELS) as InterviewFormat[];
export const INTERVIEW_OUTCOMES = Object.keys(OUTCOME_LABELS) as InterviewOutcome[];

/** The round's own title, or its kind ("Technical", "Interview" for other). */
export function roundName(round: Pick<InterviewRound, "title" | "kind">): string {
  return round.title?.trim() || KIND_LABELS[round.kind] || "Interview";
}

function dayNumber(d: Date): number {
  return Math.round(new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() / 86_400_000);
}

/**
 * How far away a round is: "in 2 hours" or "30 minutes ago" on the same day,
 * otherwise by calendar day ("tomorrow", "in 2 days", "yesterday").
 */
export function countdown(iso: string, now: Date = new Date()): string {
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return "";
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  const days = dayNumber(t) - dayNumber(now);
  if (days !== 0) return rtf.format(days, "day");
  const minutes = Math.round((t.getTime() - now.getTime()) / 60_000);
  if (minutes === 0) return "now";
  if (Math.abs(minutes) < 60) return rtf.format(minutes, "minute");
  return rtf.format(Math.round(minutes / 60), "hour");
}

/** Soonest first; rounds without a date go last (in their original order). */
export function sortByDate<T extends Pick<InterviewRound, "scheduledAt">>(rounds: T[], newestFirst = false): T[] {
  const time = (r: T) => (r.scheduledAt ? new Date(r.scheduledAt).getTime() : NaN);
  return rounds
    .map((r, i) => ({ r, i, t: time(r) }))
    .sort((a, b) => {
      const aNo = Number.isNaN(a.t);
      const bNo = Number.isNaN(b.t);
      if (aNo || bNo) return aNo === bNo ? a.i - b.i : aNo ? 1 : -1;
      return newestFirst ? b.t - a.t : a.t - b.t;
    })
    .map((x) => x.r);
}

/** "Mon, Oct 12, 2:30 PM" in the viewer's locale. */
export function formatRoundTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}
