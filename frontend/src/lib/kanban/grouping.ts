import type { Application, ApplicationStatus } from "../types/application";

export const KANBAN_COLUMNS: ApplicationStatus[] = [
  "wishlist",
  "applied",
  "phone_screen",
  "interview",
  "offer",
  "rejected",
];

export function groupByStatus(apps: Application[]): Record<ApplicationStatus, Application[]> {
  const grouped = {} as Record<ApplicationStatus, Application[]>;
  for (const status of KANBAN_COLUMNS) grouped[status] = [];
  for (const app of apps) {
    if (app.archived) continue;
    grouped[app.status]?.push(app);
  }
  return grouped;
}
