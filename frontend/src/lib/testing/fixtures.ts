import type { Application } from "../types/application";
import type { Contact } from "../types/contact";
import type { Posting, ScanStatus, WatchCompany } from "../types/discovery";

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

export function fakeContact(overrides: Partial<Contact> = {}): Contact {
  return {
    id: 1,
    kind: "professor",
    name: "Jane Lee",
    organization: "Stanford",
    department: null,
    title: null,
    labName: null,
    email: null,
    emailConfidence: "not_found",
    websiteUrl: null,
    profileUrl: null,
    applicationId: null,
    relevanceNote: null,
    researchSummary: null,
    recentWork: null,
    sources: [],
    draftSubject: null,
    draftBody: null,
    draftEdited: false,
    followupSubject: null,
    followupBody: null,
    followupEdited: false,
    draftReadyAt: null,
    status: "to_contact",
    closedReason: null,
    priority: "medium",
    sentAt: null,
    followedUpAt: null,
    repliedAt: null,
    meetingAt: null,
    nudgeSnoozedUntil: null,
    notes: null,
    origin: "manual",
    archived: false,
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    nudge: null,
    ...overrides,
  };
}

export function fakePosting(overrides: Partial<Posting> = {}): Posting {
  return {
    id: 1,
    source: "simplify",
    company: "Stripe",
    title: "SWE Intern",
    locations: ["NYC", "Remote"],
    url: "https://stripe.com/jobs/1",
    terms: ["Summer 2027"],
    category: "Software",
    sponsorship: null,
    datePosted: "2026-10-01T00:00:00Z",
    firstSeenAt: "2026-10-02T00:00:00Z",
    lastSeenAt: "2026-10-03T00:00:00Z",
    closed: false,
    state: "new",
    stateChangedAt: "2026-10-02T00:00:00Z",
    applicationId: null,
    watchCompanyId: null,
    claudeScore: null,
    claudeNote: null,
    ...overrides,
  };
}

export function fakeWatchCompany(overrides: Partial<WatchCompany> = {}): WatchCompany {
  return {
    id: 4,
    name: "Stripe",
    ats: "greenhouse",
    boardToken: "stripe",
    careersUrl: "https://boards.greenhouse.io/stripe",
    addedAt: "2026-10-01T00:00:00Z",
    lastCheckedAt: null,
    lastError: null,
    openMatches: 0,
    ...overrides,
  };
}

export function fakeScanStatus(overrides: Partial<ScanStatus> = {}): ScanStatus {
  return { lastScanAt: null, lastScanError: null, scanning: false, inboxCount: 0, ...overrides };
}
