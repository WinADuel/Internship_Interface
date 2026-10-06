import type { Application } from "../types/application";

export function fakeApplication(overrides: Partial<Application> = {}): Application {
  return {
    id: 1,
    company: "Acme",
    roleTitle: "SWE Intern",
    dateApplied: null,
    status: "wishlist",
    jobLink: null,
    notes: null,
    resumeVersion: null,
    contactPerson: null,
    salaryRange: null,
    location: null,
    source: null,
    priority: "medium",
    followUpDate: null,
    interviewDatetime: null,
    googleDocLink: null,
    archived: false,
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}
