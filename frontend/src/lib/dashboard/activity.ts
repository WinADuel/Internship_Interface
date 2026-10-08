import type { ActivityEntry } from "../types/application";
import type { ContactActivityEntry, ContactKind } from "../types/contact";

export type FeedItem = {
  kind: "application" | "contact";
  label: string;
  oldStatus: string | null;
  newStatus: string;
  changedAt: string;
  /** Contact entries only: the status wording differs for professors and company contacts. */
  contactKind?: ContactKind;
};

/** Both history feeds as one list, newest first, cut to `limit`. */
export function mergeActivity(apps: ActivityEntry[], contacts: ContactActivityEntry[], limit: number): FeedItem[] {
  const items: FeedItem[] = [
    ...apps.map((a) => ({
      kind: "application" as const,
      label: `${a.company} — ${a.roleTitle}`,
      oldStatus: a.oldStatus,
      newStatus: a.newStatus,
      changedAt: a.changedAt,
    })),
    ...contacts.map((c) => ({
      kind: "contact" as const,
      label: `${c.name} (${c.organization})`,
      oldStatus: c.oldStatus,
      newStatus: c.newStatus,
      changedAt: c.changedAt,
      contactKind: c.kind,
    })),
  ];
  return items
    .sort((x, y) => new Date(y.changedAt).getTime() - new Date(x.changedAt).getTime())
    .slice(0, limit);
}
