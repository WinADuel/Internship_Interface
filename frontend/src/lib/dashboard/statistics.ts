import type { Application, ApplicationStatus } from "../types/application";
import type { InterviewRoundListItem } from "../types/interview";
import { parseLocalDate } from "./widgets";

const DAY_MS = 86_400_000;

/** Statuses that mean the application was actually sent. */
const SENT: ReadonlySet<ApplicationStatus> = new Set(["applied", "phone_screen", "interview", "offer", "rejected"]);
/** Statuses that mean the company answered (a screen, an interview, an offer or a rejection). */
const HEARD_BACK: ReadonlySet<ApplicationStatus> = new Set(["phone_screen", "interview", "offer", "rejected"]);

export interface ApplicationStats {
  sent: number;
  sentLast7Days: number;
  heardBack: number;
  /** Whole-number percent of sent applications that heard back, or null before any were sent. */
  responseRate: number | null;
}

export function applicationStats(apps: Application[], now: Date): ApplicationStats {
  const sentApps = apps.filter((a) => !a.archived && SENT.has(a.status));
  const weekAgo = now.getTime() - 7 * DAY_MS;
  const sentLast7Days = sentApps.filter((a) => {
    const d = a.dateApplied ? parseLocalDate(a.dateApplied) : null;
    return d !== null && d.getTime() >= weekAgo && d.getTime() <= now.getTime();
  }).length;
  const heardBack = sentApps.filter((a) => HEARD_BACK.has(a.status)).length;
  return {
    sent: sentApps.length,
    sentLast7Days,
    heardBack,
    responseRate: sentApps.length ? Math.round((heardBack / sentApps.length) * 100) : null,
  };
}

/** Scheduled interview rounds still ahead of `now`, soonest first. */
export function scheduledInterviews(rounds: InterviewRoundListItem[], now: Date): InterviewRoundListItem[] {
  return rounds
    .filter((r) => r.state === "scheduled" && r.scheduledAt && new Date(r.scheduledAt).getTime() >= now.getTime())
    .sort((a, b) => new Date(a.scheduledAt as string).getTime() - new Date(b.scheduledAt as string).getTime());
}
