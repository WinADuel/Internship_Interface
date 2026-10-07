export type ApplicationStatus =
  | "wishlist"
  | "applied"
  | "phone_screen"
  | "interview"
  | "offer"
  | "rejected";

export type Priority = "low" | "medium" | "high";

export interface Application {
  id: number;
  company: string;
  roleTitle: string;
  dateApplied: string | null;
  status: ApplicationStatus;
  jobLink: string | null;
  notes: string | null;
  resumeVersion: string | null;
  contactPerson: string | null;
  salaryRange: string | null;
  location: string | null;
  source: string | null;
  priority: Priority;
  followUpDate: string | null;
  interviewDatetime: string | null;
  googleDocLink: string | null;
  archived: boolean;
  createdAt: string;
  updatedAt: string;
}

export type ApplicationInput = Omit<Application, "id" | "archived" | "createdAt" | "updatedAt">;

export interface StatusHistoryEntry {
  oldStatus: ApplicationStatus | null;
  newStatus: ApplicationStatus;
  changedAt: string;
}

export interface ActivityEntry {
  applicationId: number;
  company: string;
  roleTitle: string;
  oldStatus: ApplicationStatus | null;
  newStatus: ApplicationStatus;
  changedAt: string;
}
